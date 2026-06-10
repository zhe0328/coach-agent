from __future__ import annotations

from functools import lru_cache

from rq import Queue

from app.queue.connection import get_redis_connection

QUEUE_HIGH = "coach_high"
QUEUE_MEDIUM = "coach_medium"
QUEUE_LOW = "coach_low"


@lru_cache(maxsize=3)
def get_queue(name: str) -> Queue:
    return Queue(name, connection=get_redis_connection())
