from app.agent.intent.intent_state import project_intent
from app.agent.policy.intent_validators import (
    ensure_unique_macro_task_ids,
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


def test_inject_graph_depends_on_all_sql_tasks():
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="multi sql",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_back",
                tool_name="sql_tool",
                reason="练背",
                focused_query="练背",
                limit=3,
            ),
            ToolCallIntent(
                task_id="task_sql_glute",
                tool_name="sql_tool",
                reason="练臀",
                focused_query="练臀",
                limit=3,
            ),
        ],
    )

    patched = inject_graph_tool(plan, "练背练臀", "policy test")

    graph_tasks = [t for t in patched.selected_tools if t.tool_name == "graph_tool"]
    assert graph_tasks[0].depends_on == ["task_sql_back", "task_sql_glute"]


def test_ensure_unique_macro_task_ids_renames_duplicates_and_expands_graph_deps():
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="duplicate ids",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_base",
                tool_name="sql_tool",
                reason="练背",
                focused_query="练背",
                limit=3,
            ),
            ToolCallIntent(
                task_id="task_sql_base",
                tool_name="sql_tool",
                reason="练臀",
                focused_query="练臀",
                limit=3,
            ),
            ToolCallIntent(
                task_id="task_graph_injury",
                tool_name="graph_tool",
                reason="伤病规避",
                focused_query="腕关节",
                depends_on=["task_sql_base"],
            ),
        ],
    )

    patched, actions = ensure_unique_macro_task_ids(plan)
    sql_tasks = [t for t in patched.selected_tools if t.tool_name == "sql_tool"]
    graph_task = next(
        t for t in patched.selected_tools if t.tool_name == "graph_tool"
    )

    assert [t.task_id for t in sql_tasks] == ["task_sql_base", "task_sql_base_2"]
    assert graph_task.depends_on == ["task_sql_base", "task_sql_base_2"]
    assert any(a.startswith("renamed_duplicate_task_id:") for a in actions)
    assert "expanded_graph_depends_on:all_sql_tasks" in actions


def test_validate_patches_duplicate_task_ids_from_llm_output():
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="llm duplicate ids",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_base",
                tool_name="sql_tool",
                reason="练背",
                focused_query="练背",
            ),
            ToolCallIntent(
                task_id="task_sql_base",
                tool_name="sql_tool",
                reason="练大腿",
                focused_query="练大腿",
            ),
            ToolCallIntent(
                task_id="task_graph_injury",
                tool_name="graph_tool",
                reason="伤病规避",
                focused_query="腕关节",
                depends_on=["task_sql_base"],
            ),
        ],
    )

    patched, actions = validate_and_patch_macro_plan(
        "3个练背+3个练大腿动作",
        plan,
        semantic_profile=[{"injuries": ["腕关节"], "equipment_list": ["哑铃"]}],
    )

    sql_ids = [t.task_id for t in patched.selected_tools if t.tool_name == "sql_tool"]
    assert sql_ids == ["task_sql_base", "task_sql_base_2"]
    assert any(a.startswith("renamed_duplicate_task_id:") for a in actions)


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
