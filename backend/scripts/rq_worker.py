#!/usr/bin/env python3
"""Start RQ workers for coach-agent background jobs.

Usage (from backend/ with venv active):
    export PYTHONPATH=.
    python scripts/rq_worker.py
"""

from __future__ import annotations

import sys

from rq.worker import Worker

from app.config import settings
from app.queue.connection import get_redis_connection
from app.queue.queues import QUEUE_HIGH, QUEUE_LOW, QUEUE_MEDIUM


def main() -> int:
    conn = get_redis_connection()
    worker = Worker(
        [QUEUE_HIGH, QUEUE_MEDIUM, QUEUE_LOW],
        connection=conn,
        name="coach-agent-worker",
    )
    print(
        f"Listening on [{QUEUE_HIGH}, {QUEUE_MEDIUM}, {QUEUE_LOW}] "
        f"via {settings.REDIS_URL}",
        flush=True,
    )
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
