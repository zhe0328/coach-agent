from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from app.agent.utils.logger import logger
from app.config import settings

_PROFILE_KEY_TEMPLATE = "user:{user_id}:semantic_profile"


@lru_cache(maxsize=1)
def _get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _profile_key(user_id: int) -> str:
    return _PROFILE_KEY_TEMPLATE.format(user_id=user_id)


async def fetch_semantic_profile_cached(
    user_id: int,
    fetch_fn: Callable[[int], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Return Neo4j semantic profile, using Redis when enabled."""
    ttl = settings.SEMANTIC_PROFILE_CACHE_TTL_SECONDS
    if ttl <= 0:
        return await _fetch_or_empty(user_id, fetch_fn)

    key = _profile_key(user_id)
    redis = _get_async_redis()
    try:
        raw = await redis.get(key)
        if raw is not None:
            logger.debug(f"[SemanticProfileCache] hit user_id={user_id}")
            return json.loads(raw)
    except Exception as exc:
        logger.warning(f"[SemanticProfileCache] read failed user_id={user_id}: {exc}")

    profile = await _fetch_or_empty(user_id, fetch_fn)
    try:
        await redis.setex(key, ttl, json.dumps(profile, ensure_ascii=False))
        logger.debug(f"[SemanticProfileCache] stored user_id={user_id} ttl={ttl}s")
    except Exception as exc:
        logger.warning(f"[SemanticProfileCache] write failed user_id={user_id}: {exc}")
    return profile


async def _fetch_or_empty(
    user_id: int,
    fetch_fn: Callable[[int], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    try:
        return await fetch_fn(user_id) or []
    except Exception as exc:
        logger.warning(
            f"[SemanticProfileCache] Neo4j fetch failed user_id={user_id}: {exc}"
        )
        return []


async def invalidate_semantic_profile(user_id: int) -> None:
    if settings.SEMANTIC_PROFILE_CACHE_TTL_SECONDS <= 0:
        return
    try:
        await _get_async_redis().delete(_profile_key(user_id))
        logger.debug(f"[SemanticProfileCache] invalidated user_id={user_id}")
    except Exception as exc:
        logger.warning(
            f"[SemanticProfileCache] invalidate failed user_id={user_id}: {exc}"
        )


async def prime_semantic_profile_cache(
    user_id: int,
    *,
    level: str,
    injuries: list[str],
    equipment_list: list[str],
) -> None:
    """Write profile snapshot to Redis immediately (e.g. after MySQL profile update)."""
    ttl = settings.SEMANTIC_PROFILE_CACHE_TTL_SECONDS
    if ttl <= 0:
        return

    profile = [
        {
            "level": level,
            "injuries": injuries,
            "equipment_list": equipment_list,
        }
    ]
    try:
        await _get_async_redis().setex(
            _profile_key(user_id),
            ttl,
            json.dumps(profile, ensure_ascii=False),
        )
        logger.info(
            f"[SemanticProfileCache] primed user_id={user_id} "
            f"injuries={injuries} equipment={equipment_list}"
        )
    except Exception as exc:
        logger.warning(
            f"[SemanticProfileCache] prime failed user_id={user_id}: {exc}"
        )
