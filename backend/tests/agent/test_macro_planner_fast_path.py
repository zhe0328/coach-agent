"""Tests for deterministic macro planner fast-path."""

from __future__ import annotations

from app.agent.intent.intent_state import IntentState, project_intent
from app.agent.macro_planner_fast_path import try_macro_fast_path


def _intent(user_input: str, *, profile=None) -> IntentState:
    return project_intent(user_input, semantic_profile=profile)


def _profile(*, injuries=None, equipment=None, level="intermediate"):
    return [
        {
            "level": level,
            "injuries": injuries or [],
            "equipment_list": equipment or ["哑铃", "自重"],
        }
    ]


def test_fast_path_action_sql_with_profile_injuries():
    user_input = "推荐两个练上肢的动作，我一起练"
    profile = _profile(injuries=["腕关节"])
    intent = _intent(user_input, profile=profile)

    result = try_macro_fast_path(user_input, intent, profile)

    assert result is not None
    plan, reason = result
    assert reason == "action_sql_graph"
    tools = {t.tool_name: t for t in plan.selected_tools}
    assert "sql_tool" in tools
    assert "graph_tool" in tools
    assert tools["graph_tool"].depends_on == ["task_sql_base"]
    assert tools["sql_tool"].limit == 2


def test_fast_path_action_sql_only_when_healthy():
    user_input = "推荐三个练腿动作"
    intent = _intent(user_input)

    result = try_macro_fast_path(user_input, intent, None)

    assert result is not None
    plan, reason = result
    assert reason == "action_sql"
    assert len(plan.selected_tools) == 1
    assert plan.selected_tools[0].tool_name == "sql_tool"
    assert plan.selected_tools[0].limit == 3


def test_fast_path_knowledge_rag_only():
    user_input = "先做高翻还是先做深蹲？"
    intent = _intent(user_input)

    result = try_macro_fast_path(user_input, intent, None)

    assert result is not None
    plan, reason = result
    assert reason == "knowledge_rag"
    assert len(plan.selected_tools) == 1
    assert plan.selected_tools[0].tool_name == "rag_tool"
    assert plan.selected_tools[0].rag_intent == "knowledge"


def test_fast_path_recovery_stretch_query_with_injury_graph():
    user_input = "练完之后怎么拉伸和休息？"
    profile = _profile(injuries=["腕关节"])
    intent = _intent(user_input, profile=profile)

    result = try_macro_fast_path(user_input, intent, profile)

    assert result is not None
    plan, reason = result
    assert reason == "recovery_rag_graph"
    tool_names = [t.tool_name for t in plan.selected_tools]
    assert tool_names == ["rag_tool", "graph_tool"]
    assert plan.selected_tools[1].depends_on == ["task_rag_stretch"]


def test_fast_path_rejects_compound_multi_target_and_knowledge():
    user_input = "推荐两个练上肢的动作，三个练腹肌的动作，划船注意事项"
    intent = _intent(user_input)

    assert try_macro_fast_path(user_input, intent, None) is None


def test_fast_path_rejects_action_plus_knowledge_companion():
    user_input = "推荐两个划船动作，注意事项有哪些"
    intent = _intent(user_input)

    assert try_macro_fast_path(user_input, intent, None) is None


def test_fast_path_rejects_multi_instance_split():
    user_input = "我想用哑铃练胸，还要用弹力带练背"
    intent = _intent(user_input)

    assert try_macro_fast_path(user_input, intent, None) is None


def test_fast_path_rejects_progression_queries():
    user_input = "深蹲太难了，换一个简单点的"
    intent = _intent(user_input)

    assert try_macro_fast_path(user_input, intent, None) is None


def test_fast_path_safety_gets_graph():
    user_input = "深蹲膝盖痛，推荐替代动作"
    intent = _intent(user_input)

    result = try_macro_fast_path(user_input, intent, None)
    assert result is not None
    plan, reason = result
    assert reason == "action_sql_graph"
    assert any(t.tool_name == "graph_tool" for t in plan.selected_tools)


def test_fast_path_action_sql_graph_includes_graph_when_profile_injured():
    user_input = "推荐哑铃练胸"
    profile = _profile(injuries=["肩关节"])
    intent = _intent(user_input, profile=profile)

    result = try_macro_fast_path(user_input, intent, profile)

    assert result is not None
    plan, reason = result
    assert reason == "action_sql_graph"
    assert any(t.tool_name == "graph_tool" for t in plan.selected_tools)
