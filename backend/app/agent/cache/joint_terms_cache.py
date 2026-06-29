from __future__ import annotations

import json
from functools import lru_cache

import redis.asyncio as aioredis

from app.agent.utils.logger import logger
from app.config import settings

_JOINT_TERMS_KEY = "global:joint_sensitive_terms"


@lru_cache(maxsize=1)
def _get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _serialize_terms(terms: dict[str, frozenset[str]]) -> str:
    payload = {joint: sorted(values) for joint, values in terms.items()}
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_terms(raw: str) -> dict[str, frozenset[str]]:
    data = json.loads(raw)
    return {joint: frozenset(values) for joint, values in data.items()}


async def read_joint_terms_cache() -> dict[str, frozenset[str]] | None:
    ttl = settings.JOINT_TERMS_CACHE_TTL_SECONDS
    if ttl <= 0:
        return None
    try:
        raw = await _get_async_redis().get(_JOINT_TERMS_KEY)
        if raw is None:
            return None
        logger.debug("[JointTermsCache] hit")
        return _deserialize_terms(raw)
    except Exception as exc:
        logger.warning(f"[JointTermsCache] read failed: {exc}")
        return None


async def write_joint_terms_cache(terms: dict[str, frozenset[str]]) -> None:
    ttl = settings.JOINT_TERMS_CACHE_TTL_SECONDS
    if ttl <= 0:
        return
    try:
        await _get_async_redis().setex(_JOINT_TERMS_KEY, ttl, _serialize_terms(terms))
        logger.debug(f"[JointTermsCache] stored ttl={ttl}s")
    except Exception as exc:
        logger.warning(f"[JointTermsCache] write failed: {exc}")


async def invalidate_joint_terms_cache() -> None:
    if settings.JOINT_TERMS_CACHE_TTL_SECONDS <= 0:
        return
    try:
        await _get_async_redis().delete(_JOINT_TERMS_KEY)
        logger.debug("[JointTermsCache] invalidated")
    except Exception as exc:
        logger.warning(f"[JointTermsCache] invalidate failed: {exc}")
