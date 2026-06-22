from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncIterator

import redis.asyncio as aioredis

from app.agent.utils.logger import logger
from app.config import settings

_LOCK_KEY_TEMPLATE = "session:{session_id}:lock"
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class SessionLockNotAcquired(Exception):
    """Raised when another in-flight request already holds the session lock."""

    def __init__(self, session_id: str, *, retry_after: int) -> None:
        self.session_id = session_id
        self.retry_after = retry_after
        super().__init__(
            f"Session {session_id} is processing another request; "
            f"retry after {retry_after}s"
        )


@lru_cache(maxsize=1)
def _get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _lock_key(session_id: str) -> str:
    return _LOCK_KEY_TEMPLATE.format(session_id=session_id)


async def is_session_locked(session_id: str) -> bool:
    if not settings.SESSION_LOCK_ENABLED:
        return False
    redis = _get_async_redis()
    return bool(await redis.exists(_lock_key(session_id)))


class SessionLock:
    """Redis SET NX lock — one in-flight turn per session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.retry_after_seconds = settings.SESSION_LOCK_RETRY_AFTER_SECONDS
        self._token: str | None = None

    @property
    def key(self) -> str:
        return _lock_key(self.session_id)

    async def acquire(self) -> bool:
        if not settings.SESSION_LOCK_ENABLED:
            self._token = "disabled"
            return True

        self._token = uuid.uuid4().hex
        redis = _get_async_redis()
        acquired = await redis.set(
            self.key,
            self._token,
            nx=True,
            ex=settings.SESSION_LOCK_TTL_SECONDS,
        )
        if acquired:
            logger.info(f"[SessionLock] acquired session={self.session_id}")
            return True

        self._token = None
        logger.warning(
            f"[SessionLock] busy session={self.session_id} "
            f"retry_after={self.retry_after_seconds}s"
        )
        return False

    async def release(self) -> None:
        if not settings.SESSION_LOCK_ENABLED or not self._token:
            return
        if self._token == "disabled":
            return

        redis = _get_async_redis()
        released = await redis.eval(_RELEASE_SCRIPT, 1, self.key, self._token)
        if released:
            logger.info(f"[SessionLock] released session={self.session_id}")
        self._token = None


@asynccontextmanager
async def acquire_session_lock(session_id: str) -> AsyncIterator[SessionLock]:
    lock = SessionLock(session_id)
    if not await lock.acquire():
        raise SessionLockNotAcquired(
            session_id,
            retry_after=lock.retry_after_seconds,
        )
    try:
        yield lock
    finally:
        await lock.release()
