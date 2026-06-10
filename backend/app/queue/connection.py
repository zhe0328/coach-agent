from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.config import settings


@lru_cache(maxsize=1)
def get_redis_connection() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)
