"""E2E integration tests: memory consolidation triggers at max turn threshold."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent.memory.memory_policy import CONSOLIDATION_TURN_THRESHOLD
from app.agent.orchestrator import CoachOrchestrator
from app.models.memory import InjurySnifferSchema, WorkingMemory
from app.models.schema import CoachResponse
from app.queue import jobs


pytestmark = pytest.mark.asyncio(loop_scope="function")


@dataclass
class CapturedEnqueue:
    queue_name: str
    func: Any
    job_id: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@pytest.fixture
def captured_enqueues(monkeypatch):
    captured: list[CapturedEnqueue] = []

    def fake_enqueue(
        queue_name,
        func,
        *,
        job_id,
        args=(),
        kwargs=None,
        retry=None,
    ):
        captured.append(
            CapturedEnqueue(
                queue_name=queue_name,
                func=func,
                job_id=job_id,
                args=args,
                kwargs=kwargs or {},
            )
        )
        return job_id

    monkeypatch.setattr("app.queue.enqueue._enqueue", fake_enqueue)
    monkeypatch.setattr("app.config.settings.QUEUE_ENABLED", True)
    return captured


def _quiet_sniff() -> InjurySnifferSchema:
    return InjurySnifferSchema(
        has_new_injury=False,
        joint=None,
        severity="none",
        reason="普通训练交流",
        has_new_equipment=False,
        equipment_name=None,
    )


def _coach_response() -> CoachResponse:
    return CoachResponse(
        response_type="knowledge",
        greeting="你好",
        detailed_guidance="继续按计划训练。",
        summary="保持训练节奏",
        selected_tools=["rag_tool"],
    )


def _persist_state(
    *,
    session_id: str = "e2e-session",
    user_id: int = 42,
    turn_count: int = 0,
    user_input: str = "今天练什么？",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "user_input": user_input,
        "memory": WorkingMemory(session_id=session_id, turn_count=turn_count),
        "coach_response": _coach_response(),
        "semantic_profile": [],
    }


@pytest.fixture
def orchestrator() -> CoachOrchestrator:
    return CoachOrchestrator(client=None)


def _consolidation_jobs(captured: list[CapturedEnqueue]) -> list[CapturedEnqueue]:
    return [item for item in captured if item.func == jobs.consolidate_to_graph]


@pytest.fixture(autouse=True)
def _patch_persist_side_effects(monkeypatch):
    async def noop_save(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        "app.agent.orchestrator.WorkingMemoryManager.save_session_memory",
        noop_save,
    )


class TestMemoryConsolidationMaxTurnsE2E:
    async def test_persist_schedules_consolidation_at_max_turns(
        self, orchestrator, captured_enqueues, monkeypatch
    ):
        quiet = _quiet_sniff()
        monkeypatch.setattr(
            orchestrator.memory_consolidator,
            "sniff_delta",
            AsyncMock(return_value=quiet),
        )

        state = _persist_state(
            turn_count=CONSOLIDATION_TURN_THRESHOLD - 1,
            user_input="第六轮：帮我安排背训",
        )
        result = await orchestrator._node_persist(state)

        memory = result["memory"]
        assert memory.turn_count == CONSOLIDATION_TURN_THRESHOLD

        consolidation = _consolidation_jobs(captured_enqueues)
        assert len(consolidation) == 1
        assert consolidation[0].kwargs["user_id"] == 42
        assert consolidation[0].kwargs["user_query"] == "第六轮：帮我安排背训"
        assert consolidation[0].kwargs["sniff"]["has_new_injury"] is False

    async def test_persist_does_not_consolidate_before_max_turns(
        self, orchestrator, captured_enqueues, monkeypatch
    ):
        monkeypatch.setattr(
            orchestrator.memory_consolidator,
            "sniff_delta",
            AsyncMock(return_value=_quiet_sniff()),
        )

        state = _persist_state(turn_count=CONSOLIDATION_TURN_THRESHOLD - 2)
        result = await orchestrator._node_persist(state)

        assert result["memory"].turn_count == CONSOLIDATION_TURN_THRESHOLD - 1
        assert _consolidation_jobs(captured_enqueues) == []

    async def test_six_persist_cycles_trigger_consolidation_once_at_threshold(
        self, orchestrator, captured_enqueues, monkeypatch
    ):
        monkeypatch.setattr(
            orchestrator.memory_consolidator,
            "sniff_delta",
            AsyncMock(return_value=_quiet_sniff()),
        )

        state = _persist_state(turn_count=0)
        memory = state["memory"]

        for turn in range(1, CONSOLIDATION_TURN_THRESHOLD + 1):
            state["memory"] = memory
            state["user_input"] = f"第{turn}轮用户消息"
            result = await orchestrator._node_persist(state)
            memory = result["memory"]
            assert memory.turn_count == turn

        consolidation = _consolidation_jobs(captured_enqueues)
        assert len(consolidation) == 1
        assert consolidation[0].kwargs["user_query"] == (
            f"第{CONSOLIDATION_TURN_THRESHOLD}轮用户消息"
        )

    async def test_persist_still_logs_chat_without_consolidation(
        self, orchestrator, captured_enqueues, monkeypatch
    ):
        monkeypatch.setattr(
            orchestrator.memory_consolidator,
            "sniff_delta",
            AsyncMock(return_value=_quiet_sniff()),
        )

        await orchestrator._node_persist(_persist_state(turn_count=0))

        funcs = [item.func for item in captured_enqueues]
        assert jobs.log_chat_transaction in funcs
        assert jobs.save_training_log in funcs
        assert _consolidation_jobs(captured_enqueues) == []
