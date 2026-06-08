import time

import pytest

from app.agent.memory.memory_manager import WorkingMemoryManager
from app.agent.memory.memory_policy import (
    CONSOLIDATION_TURN_THRESHOLD,
    should_consolidate,
)
from app.agent.memory.session_summarizer import merge_session_summary
from app.models.memory import ChatMessage, InjurySnifferSchema, WorkingMemory


def _make_history(n_messages: int) -> list[ChatMessage]:
    history: list[ChatMessage] = []
    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        history.append(ChatMessage(role=role, content=f"message-{i}"))
    return history


@pytest.fixture
def memory_manager() -> WorkingMemoryManager:
    return WorkingMemoryManager(max_history_turns=4)


class TestWorkingMemoryPruning:
    def test_prune_excess_returns_removed_messages(self, memory_manager):
        memory = WorkingMemory(
            session_id="s1",
            chat_history=_make_history(10),
        )
        pruned = memory_manager.prune_excess_messages(memory)

        assert len(pruned) == 2
        assert len(memory.chat_history) == 8
        assert pruned[0].content == "message-0"

    def test_prune_excess_noop_when_within_window(self, memory_manager):
        memory = WorkingMemory(session_id="s1", chat_history=_make_history(6))
        pruned = memory_manager.prune_excess_messages(memory)

        assert pruned == []
        assert len(memory.chat_history) == 6


class TestSessionSummary:
    @pytest.mark.asyncio
    async def test_save_appends_summary_on_prune(self, memory_manager, monkeypatch):
        captured: dict[str, str] = {}

        async def fake_save(session_id, payload, ex=None):
            captured["payload"] = payload

        monkeypatch.setattr(memory_manager.redis, "set", fake_save)

        memory = WorkingMemory(session_id="s1", chat_history=_make_history(10))

        async def fake_summarize(messages):
            return "用户关注练背；教练推荐了划船。"

        await memory_manager.save_session_memory(
            "s1",
            memory,
            summarize_fn=fake_summarize,
        )

        assert "练背" in memory.session_summary
        assert "练背" in captured["payload"]

    def test_merge_session_summary_appends_and_truncates(self):
        merged = merge_session_summary("第一轮摘要", "第二轮摘要", max_chars=20)
        assert "第二轮摘要" in merged
        assert len(merged) <= 20


class TestConsolidationPolicy:
    def test_should_consolidate_on_turn_threshold(self):
        memory = WorkingMemory(
            session_id="s1",
            turn_count=CONSOLIDATION_TURN_THRESHOLD,
        )
        assert should_consolidate(memory) is True

    def test_should_consolidate_on_high_signal_sniff(self):
        memory = WorkingMemory(session_id="s1", turn_count=1)
        sniff = InjurySnifferSchema(
            has_new_injury=True,
            joint=["膝关节"],
            severity="temporary_pain",
            reason="膝盖痛",
            has_new_equipment=False,
            equipment_name=None,
        )
        assert should_consolidate(memory, sniff=sniff) is True

    def test_should_not_consolidate_on_quiet_turn(self):
        memory = WorkingMemory(session_id="s1", turn_count=1)
        sniff = InjurySnifferSchema(
            has_new_injury=False,
            joint=None,
            severity="none",
            reason="普通训练交流",
            has_new_equipment=False,
            equipment_name=None,
        )
        assert should_consolidate(memory, sniff=sniff) is False


class TestWorkingMemoryPerformance:
    @pytest.mark.parametrize("n_messages", [100, 1000, 10000])
    def test_prune_excess_scales_linearly(self, memory_manager, n_messages: int):
        memory = WorkingMemory(
            session_id="perf",
            chat_history=_make_history(n_messages),
        )
        start = time.perf_counter()
        memory_manager.prune_excess_messages(memory)
        elapsed = time.perf_counter() - start

        assert len(memory.chat_history) == memory_manager.max_history_len
        assert elapsed < 0.05, f"prune took {elapsed:.4f}s for {n_messages} messages"

    @pytest.mark.parametrize("n_messages", [100, 1000, 10000])
    def test_records_to_chat_history_performance(self, memory_manager, n_messages: int):
        records = [
            {"id": i, "role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
            for i in range(n_messages)
        ]
        start = time.perf_counter()
        history = memory_manager.records_to_chat_history(records)
        elapsed = time.perf_counter() - start

        assert len(history) == n_messages
        assert elapsed < 0.1, f"records_to_chat_history took {elapsed:.4f}s"

    def test_serialize_deserialize_performance(self):
        memory = WorkingMemory(
            session_id="perf",
            chat_history=_make_history(1000),
            session_summary="x" * 2000,
            turn_count=500,
        )
        start = time.perf_counter()
        for _ in range(200):
            raw = memory.model_dump_json()
            WorkingMemory.model_validate_json(raw)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"200 serialize cycles took {elapsed:.4f}s"
