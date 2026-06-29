"""Tests for post-persist job enqueueing."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from app.models.fitness import AgentPlansLog, ChatRecord, TrainingLog
from app.models.memory import InjurySnifferSchema
from app.models.schema import FullPlan, ToolCallIntent
from app.queue import jobs
from app.queue.enqueue import AfterTurnPayload, enqueue_after_turn


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


def _payload(**overrides) -> AfterTurnPayload:
    base = AfterTurnPayload(
        session_id="sess-1",
        turn_id=3,
        user_id=7,
        user_record=ChatRecord(session_id="sess-1", role="user", content="hi"),
        coach_record=ChatRecord(session_id="sess-1", role="assistant", content="{}"),
        training_log=TrainingLog(
            user_id=7,
            session_id="sess-1",
            coach_reply_summary="summary",
            generated_plan_json=[],
        ),
        run_consolidation=False,
        user_query="hi",
        semantic_profile=[],
        sniff=None,
        agent_plans_log=None,
    )
    return replace(base, **overrides)


def _agent_plans_log() -> AgentPlansLog:
    return AgentPlansLog(
        id=None,
        session_id="sess-1",
        user_query="hi",
        loop_retry_count=1,
        macro_blueprint=[
            ToolCallIntent(
                task_id="t1",
                tool_name="rag_tool",
                reason="test",
                focused_query="q",
                limit=3,
            )
        ],
        native_full_plan=FullPlan(logic_chain="chain", tasks=[]),
        executed_results="[]",
        analyzer_final_reason="retry",
    )


class TestEnqueueAfterTurn:
    def test_enqueues_chat_and_training_jobs(self, captured_enqueues):
        enqueue_after_turn(_payload())

        funcs = [item.func for item in captured_enqueues]
        assert jobs.log_chat_transaction in funcs
        assert jobs.save_training_log in funcs
        assert jobs.consolidate_to_graph not in funcs

        chat = next(c for c in captured_enqueues if c.func == jobs.log_chat_transaction)
        assert chat.job_id == "sess-1__3__log_chat"
        assert chat.queue_name == "coach_high"

        training = next(c for c in captured_enqueues if c.func == jobs.save_training_log)
        assert training.job_id == "sess-1__3__training_log"
        assert training.queue_name == "coach_medium"

    def test_enqueues_consolidation_when_flagged(self, captured_enqueues):
        sniff = InjurySnifferSchema(
            has_new_injury=True,
            joint=["膝关节"],
            severity="temporary_pain",
            reason="膝盖痛",
            has_new_equipment=False,
            equipment_name=None,
        )
        enqueue_after_turn(_payload(run_consolidation=True, sniff=sniff))

        consolidation = next(
            c for c in captured_enqueues if c.func == jobs.consolidate_to_graph
        )
        assert consolidation.job_id == "7__sess-1__3__consolidate"
        assert consolidation.kwargs["user_id"] == 7
        assert consolidation.kwargs["sniff"]["has_new_injury"] is True

    def test_enqueues_memory_summarize_when_pruned(self, captured_enqueues):
        from app.models.memory import ChatMessage

        pruned = [ChatMessage(role="user", content="old message")]
        enqueue_after_turn(
            _payload(pruned_messages=pruned, turn_range="turn_3")
        )

        summarize = next(
            c for c in captured_enqueues if c.func == jobs.memory_summarize
        )
        assert summarize.job_id == "sess-1__turn_3__memory_summarize"
        assert summarize.kwargs["session_id"] == "sess-1"

    def test_enqueues_agent_plans_log(self, captured_enqueues):
        enqueue_after_turn(_payload(agent_plans_log=_agent_plans_log()))

        plan_log = next(c for c in captured_enqueues if c.func == jobs.agent_plans_log)
        assert plan_log.job_id == "sess-1__3__retry_1__plan_log"


class TestEnqueueSniffAfterTurn:
    def test_enqueues_sniff_job(self, captured_enqueues, monkeypatch):
        from app.queue.enqueue import enqueue_sniff_after_turn

        enqueue_sniff_after_turn(
            user_id=7,
            session_id="sess-1",
            turn_id=3,
            user_query="hi",
            semantic_profile=[],
        )

        sniff = next(
            c
            for c in captured_enqueues
            if c.func == jobs.sniff_profile_and_maybe_consolidate
        )
        assert sniff.job_id == "7__sess-1__3__sniff_profile"
        assert sniff.queue_name == "coach_medium"
        assert sniff.kwargs["user_query"] == "hi"
