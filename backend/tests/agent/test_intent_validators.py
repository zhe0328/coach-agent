from app.agent.intent.intent_state import project_intent
from app.agent.policy.intent_validators import (
    has_graph_tool,
    inject_graph_tool,
    should_force_chat_only,
    validate_and_patch_macro_plan,
)
from app.models.schema import MacroPlanSchema, ToolCallIntent


def _sql_only_plan() -> MacroPlanSchema:
    return MacroPlanSchema(
        routing_mode="standard",
        routing_reason="test sql only",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_base",
                tool_name="sql_tool",
                reason="筛选动作",
                focused_query="哑铃练胸",
            )
        ],
    )


def test_validate_injects_graph_for_safety_keywords():
    plan = _sql_only_plan()
    intent = project_intent("深蹲时膝盖痛，推荐几个替代动作")

    patched, actions = validate_and_patch_macro_plan(
        "深蹲时膝盖痛，推荐几个替代动作",
        plan,
        semantic_profile=[],
        intent_state=intent,
    )

    assert has_graph_tool(patched)
    assert "injected_graph_tool:safety" in actions
    graph_tasks = [t for t in patched.selected_tools if t.tool_name == "graph_tool"]
    assert graph_tasks[0].task_id == "task_graph_policy"
    assert graph_tasks[0].depends_on == ["task_sql_base"]


def test_validate_injects_graph_for_spine_profile_and_lower_body_training():
    plan = _sql_only_plan()
    profile = [{"injuries": ["脊柱"], "equipment_list": ["哑铃"], "level": "beginner"}]

    patched, actions = validate_and_patch_macro_plan(
        "我想练大腿和臀部",
        plan,
        semantic_profile=profile,
    )

    assert has_graph_tool(patched)
    assert "injected_graph_tool:joints:脊柱" in actions


def test_validate_skips_chat_only_plans():
    plan = MacroPlanSchema(
        routing_mode="chat_only",
        routing_reason="greeting",
        selected_tools=[],
    )

    patched, actions = validate_and_patch_macro_plan("你好", plan, semantic_profile=[])

    assert patched.routing_mode == "chat_only"
    assert actions == []


def test_inject_graph_does_not_duplicate_existing_graph_task():
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="already has graph",
        selected_tools=[
            ToolCallIntent(
                task_id="task_graph_injury",
                tool_name="graph_tool",
                reason="伤病规避",
                focused_query="肩痛",
            )
        ],
    )

    patched = inject_graph_tool(plan, "肩痛", "should not duplicate")

    assert len([t for t in patched.selected_tools if t.tool_name == "graph_tool"]) == 1
