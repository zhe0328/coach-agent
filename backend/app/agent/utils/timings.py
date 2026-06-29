"""Per-turn node latency tracking for orchestrator."""

from __future__ import annotations

import time
from typing import Any

from app.agent.utils.logger import logger


def merge_node_timing(
    state: dict[str, Any],
    node: str,
    started: float,
) -> dict[str, Any]:
    timings = dict(state.get("timings_ms") or {})
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    timings[node] = timings.get(node, 0) + elapsed_ms
    return {"timings_ms": timings}


def finalize_turn_timings(
    state: dict[str, Any],
    turn_started: float,
) -> dict[str, Any]:
    timings = dict(state.get("timings_ms") or {})
    total_ms = int((time.perf_counter() - turn_started) * 1000)
    timings["total"] = total_ms
    return {"timings_ms": timings, "timings_total_ms": total_ms}


def log_turn_timings(session_id: str, timings_ms: dict[str, int] | None) -> None:
    if not timings_ms:
        return
    total = timings_ms.get("total")
    logger.info(
        f"[Timings] session={session_id} total_ms={total} breakdown={timings_ms}"
    )
