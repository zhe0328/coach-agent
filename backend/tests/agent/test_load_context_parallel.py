from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.orchestrator import CoachOrchestrator
from app.models.memory import WorkingMemory


@pytest.mark.asyncio
async def test_load_context_runs_memory_profile_and_intent_in_parallel(monkeypatch):
    order: list[str] = []

    async def slow_memory(_session_id: str):
        order.append("memory_start")
        await asyncio.sleep(0.05)
        order.append("memory_end")
        return WorkingMemory(session_id="sess-1")

    async def slow_profile(_user_id: int):
        order.append("profile_start")
        await asyncio.sleep(0.05)
        order.append("profile_end")
        return [{"injuries": [], "equipment_list": []}]

    async def slow_prefetch(_sql, _graph):
        order.append("intent_start")
        await asyncio.sleep(0.05)
        order.append("intent_end")
        from app.agent.intent.fitness_lexicon import FitnessLexicon

        return FitnessLexicon.bootstrap(), {"knee": frozenset()}

    async def slow_session(_session):
        order.append("session_start")
        await asyncio.sleep(0.05)
        order.append("session_end")

    monkeypatch.setattr(
        "app.config.settings.EVAL_NO_PERSIST", False
    )
    monkeypatch.setattr(
        "app.agent.orchestrator.fetch_semantic_profile_cached",
        lambda uid, fn: slow_profile(uid),
    )
    monkeypatch.setattr(
        "app.agent.orchestrator.prefetch_intent_resources",
        slow_prefetch,
    )

    orch = CoachOrchestrator(MagicMock())
    orch.memory_manager = MagicMock()
    orch.memory_manager.get_session_memory = AsyncMock(side_effect=slow_memory)
    orch.sql_tool = MagicMock()
    orch.sql_tool.create_or_ignore_session = AsyncMock(side_effect=slow_session)

    state = {"user_id": 1, "session_id": "sess-1", "turn_started_perf": 0.0}
    updates = await orch._node_load_context(state)

    assert updates["semantic_profile"]
    assert orch._fitness_lexicon is not None
    assert orch._joint_terms_loaded is True

    starts = [i for i, tag in enumerate(order) if tag.endswith("_start")]
    ends = [i for i, tag in enumerate(order) if tag.endswith("_end")]
    assert max(starts) < min(ends), f"expected overlap, got order={order}"
