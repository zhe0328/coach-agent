from __future__ import annotations

import asyncio

import pytest

from app.serving.session_lock import (
    SessionLock,
    SessionLockNotAcquired,
    acquire_session_lock,
    is_session_locked,
)


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def exists(self, key: str) -> int:
        return int(key in self._store)

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        if self._store.get(key) == token:
            del self._store[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr("app.serving.session_lock._get_async_redis", lambda: redis)
    monkeypatch.setattr("app.config.settings.SESSION_LOCK_ENABLED", True)
    monkeypatch.setattr("app.config.settings.SESSION_LOCK_TTL_SECONDS", 90)
    monkeypatch.setattr("app.config.settings.SESSION_LOCK_RETRY_AFTER_SECONDS", 2)
    return redis


@pytest.mark.asyncio
async def test_acquire_and_release(fake_redis):
    lock = SessionLock("sess-a")
    assert await lock.acquire() is True
    assert await is_session_locked("sess-a") is True
    await lock.release()
    assert await is_session_locked("sess-a") is False


@pytest.mark.asyncio
async def test_second_acquire_fails_while_held(fake_redis):
    first = SessionLock("sess-a")
    second = SessionLock("sess-a")

    assert await first.acquire() is True
    assert await second.acquire() is False

    await first.release()
    assert await second.acquire() is True
    await second.release()


@pytest.mark.asyncio
async def test_context_manager_raises_when_busy(fake_redis):
    holder = SessionLock("sess-a")
    assert await holder.acquire() is True

    with pytest.raises(SessionLockNotAcquired) as exc_info:
        async with acquire_session_lock("sess-a"):
            pass

    assert exc_info.value.session_id == "sess-a"
    assert exc_info.value.retry_after == 2
    await holder.release()


@pytest.mark.asyncio
async def test_context_manager_releases_on_exception(fake_redis):
    with pytest.raises(RuntimeError):
        async with acquire_session_lock("sess-a"):
            raise RuntimeError("boom")

    assert await is_session_locked("sess-a") is False


@pytest.mark.asyncio
async def test_concurrent_acquire_only_one_succeeds(fake_redis):
    results: list[bool] = []

    async def worker() -> None:
        lock = SessionLock("sess-a")
        acquired = await lock.acquire()
        results.append(acquired)
        if acquired:
            await asyncio.sleep(0.05)
            await lock.release()

    await asyncio.gather(worker(), worker())

    assert results.count(True) == 1
    assert results.count(False) == 1
    assert await is_session_locked("sess-a") is False


@pytest.mark.asyncio
async def test_lock_disabled_is_noop(monkeypatch, fake_redis):
    monkeypatch.setattr("app.config.settings.SESSION_LOCK_ENABLED", False)

    async with acquire_session_lock("sess-a"):
        async with acquire_session_lock("sess-a"):
            pass

    assert await is_session_locked("sess-a") is False
