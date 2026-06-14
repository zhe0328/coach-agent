"""Context Builder unit tests — P0–P3 budget invariants (IC-P2 #12)."""

from app.agent.context.context_builder import (
    build_planner_context,
    compile_macro_messages,
    compile_macro_user_content,
    estimate_tokens,
    fit_context_to_budget,
)
from app.agent.context.context_builder import ContextSegment, PlannerContextBundle
from app.agent.intent.intent_state import project_intent
from app.models.memory import SessionStatePatch, WorkingMemory


def _memory(**kwargs) -> WorkingMemory:
    defaults = {"session_id": "sess-test"}
    defaults.update(kwargs)
    return WorkingMemory(**defaults)


def test_p0_segments_never_dropped_under_budget_pressure():
    long_summary = "摘要 " * 2000
    memory = _memory(
        session_summary=long_summary,
        latest_analyzer_feedback="请重新选装 graph_tool",
    )
    intent = project_intent("我想练深蹲")
    history = [
        {"role": "user", "content": "上一轮问题 " * 50},
        {"role": "assistant", "content": "上一轮回答 " * 50},
    ]

    bundle = build_planner_context(
        user_input="我想练深蹲",
        memory=memory,
        semantic_profile=[{"injuries": ["膝关节"], "equipment_list": ["自重"], "level": "beginner"}],
        intent_state=intent,
        planner_history_messages=history,
        budget_max_tokens=200,
    )

    included_ids = {s.segment_id for s in bundle.segments if s.included}
    assert "current_request" in included_ids
    assert "semantic_profile" in included_ids
    assert "analyzer_feedback" in included_ids
    assert "intent_state" in included_ids

    summary_seg = next(s for s in bundle.segments if s.segment_id == "session_summary")
    assert summary_seg.included is False

    for seg in bundle.segments:
        if seg.priority in ("P0", "P1") and not seg.droppable:
            assert seg.included, f"{seg.segment_id} must never drop"


def test_p3_session_summary_dropped_before_p2_history():
    summary_tokens = estimate_tokens("旧摘要 " * 400)
    history_tokens = estimate_tokens("历史 " * 100) * 2
    budget = summary_tokens + history_tokens + 50

    bundle = PlannerContextBundle(
        current_request="练胸",
        segments=[
            ContextSegment(
                segment_id="current_request",
                priority="P0",
                source="current_input",
                reason="must keep",
                content="【当前用户的最新发问】：\n\"练胸\"\n",
                estimated_tokens=20,
                droppable=False,
            ),
            ContextSegment(
                segment_id="recent_history",
                priority="P2",
                source="chat_history",
                reason="history",
                content="",
                estimated_tokens=history_tokens,
                droppable=True,
            ),
            ContextSegment(
                segment_id="session_summary",
                priority="P3",
                source="session_summary",
                reason="drop first",
                content="旧摘要 " * 400,
                estimated_tokens=summary_tokens,
                droppable=True,
            ),
        ],
        history_messages=[
            {"role": "user", "content": "历史 " * 100},
            {"role": "assistant", "content": "历史 " * 100},
        ],
        budget_max_tokens=budget - summary_tokens // 2,
    )

    fitted = fit_context_to_budget(bundle)
    summary_seg = next(s for s in fitted.segments if s.segment_id == "session_summary")
    assert summary_seg.included is False


def test_compile_macro_messages_includes_intent_and_history():
    memory = _memory(state_patch=SessionStatePatch(user_goal="练背"))
    intent = project_intent("用哑铃练背")
    history = [
        {"role": "user", "content": "之前问过肩"},
        {"role": "assistant", "content": "建议轻重量"},
    ]

    bundle = build_planner_context(
        user_input="用哑铃练背",
        memory=memory,
        semantic_profile=None,
        intent_state=intent,
        planner_history_messages=history,
    )
    messages = compile_macro_messages(bundle, system_prompt="SYS")

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "SYS"
    assert any(m["role"] == "user" and "IntentState" in m["content"] for m in messages)
    assert any(m["content"] == "之前问过肩" for m in messages)


def test_compile_macro_user_content_skips_dropped_segments():
    bundle = PlannerContextBundle(
        current_request="hi",
        segments=[
            ContextSegment(
                segment_id="current_request",
                priority="P0",
                source="current_input",
                reason="keep",
                content="CURRENT\n",
                estimated_tokens=5,
            ),
            ContextSegment(
                segment_id="session_summary",
                priority="P3",
                source="session_summary",
                reason="dropped",
                content="DROPPED\n",
                estimated_tokens=5,
                droppable=True,
                included=False,
            ),
        ],
    )
    content = compile_macro_user_content(bundle)
    assert "CURRENT" in content
    assert "DROPPED" not in content
