from __future__ import annotations

from typing import Any

from app.agent.intent.intent_state import IntentState
from app.agent.intent.matching import contains_phrase
from app.agent.policy.joint_sensitive_terms import JOINT_SENSITIVE_TERMS
from app.agent.policy.joint_term_loader import get_joint_sensitive_terms
from app.agent.policy.routing_keywords import SAFETY_PHRASES
from app.models.schema import MacroPlanSchema, ToolCallIntent


def _contains_any(text: str, keywords: frozenset[str]) -> bool:
    return contains_phrase(text, keywords)


def _sql_task_ids(tools: list[ToolCallIntent]) -> list[str]:
    return [tool.task_id for tool in tools if tool.tool_name == "sql_tool"]


def ensure_unique_macro_task_ids(
    macro_plan: MacroPlanSchema,
) -> tuple[MacroPlanSchema, list[str]]:
    """Rename duplicate task_id values and widen graph SQL dependencies."""
    actions: list[str] = []
    seen_counts: dict[str, int] = {}
    renamed_tools: list[ToolCallIntent] = []

    for intent in macro_plan.selected_tools:
        tid = intent.task_id
        count = seen_counts.get(tid, 0) + 1
        seen_counts[tid] = count
        if count == 1:
            renamed_tools.append(intent)
            continue
        new_tid = f"{tid}_{count}"
        renamed_tools.append(intent.model_copy(update={"task_id": new_tid}))
        actions.append(f"renamed_duplicate_task_id:{tid}->{new_tid}")

    sql_ids = _sql_task_ids(renamed_tools)
    final_tools: list[ToolCallIntent] = []
    for intent in renamed_tools:
        if (
            intent.tool_name == "graph_tool"
            and intent.depends_on
            and len(sql_ids) > 1
            and any("sql" in dep.lower() for dep in intent.depends_on)
        ):
            non_sql_deps = [dep for dep in intent.depends_on if "sql" not in dep.lower()]
            new_deps = list(dict.fromkeys(non_sql_deps + sql_ids))
            if new_deps != intent.depends_on:
                actions.append("expanded_graph_depends_on:all_sql_tasks")
                intent = intent.model_copy(update={"depends_on": new_deps})
        final_tools.append(intent)

    if not actions:
        return macro_plan, []
    return macro_plan.model_copy(update={"selected_tools": final_tools}), actions


def has_graph_tool(macro_plan: MacroPlanSchema) -> bool:
    return any(tool.tool_name == "graph_tool" for tool in macro_plan.selected_tools)


def requires_graph_for_safety(
    user_input: str,
    intent_state: IntentState | None = None,
) -> bool:
    if _contains_any(user_input, SAFETY_PHRASES) or "痛" in user_input or "伤" in user_input:
        return True
    if intent_state and "safety" in intent_state.slots:
        return True
    return False


def injured_joints_triggered(
    user_input: str,
    semantic_profile: list[dict[str, Any]] | None,
) -> list[str]:
    if not semantic_profile:
        return []
    injuries = semantic_profile[0].get("injuries") or []
    triggered: list[str] = []
    for joint in injuries:
        terms = get_joint_sensitive_terms().get(str(joint), frozenset())
        if terms and _contains_any(user_input, terms):
            triggered.append(str(joint))
    return triggered


def requires_graph_for_injured_joints(
    user_input: str,
    semantic_profile: list[dict[str, Any]] | None,
) -> bool:
    return bool(injured_joints_triggered(user_input, semantic_profile))


def inject_graph_tool(
    macro_plan: MacroPlanSchema,
    user_input: str,
    policy_reason: str,
) -> MacroPlanSchema:
    if has_graph_tool(macro_plan):
        return macro_plan

    sql_tasks = [
        tool for tool in macro_plan.selected_tools if tool.tool_name == "sql_tool"
    ]
    depends_on = _sql_task_ids(sql_tasks)

    graph_intent = ToolCallIntent(
        task_id="task_graph_policy",
        tool_name="graph_tool",
        reason=f"[policy] {policy_reason}",
        focused_query=user_input,
        depends_on=depends_on,
    )
    selected_tools = list(macro_plan.selected_tools) + [graph_intent]
    return macro_plan.model_copy(
        update={
            "selected_tools": selected_tools,
            "routing_mode": "standard",
            "routing_reason": (
                f"{macro_plan.routing_reason} | policy: {policy_reason}"
            ),
        }
    )


def should_force_chat_only(intent_state: IntentState | None) -> bool:
    if intent_state is None:
        return False
    return intent_state.routing_hint == "chat_only_candidate" and intent_state.fitness_score == 0


def apply_chat_only_gate(
    macro_plan: MacroPlanSchema,
    intent_state: IntentState | None,
) -> tuple[MacroPlanSchema, list[str]]:
    if not should_force_chat_only(intent_state):
        return macro_plan, []
    if macro_plan.routing_mode == "chat_only" and not macro_plan.selected_tools:
        return macro_plan, []

    return (
        MacroPlanSchema(
            routing_mode="chat_only",
            selected_tools=[],
            routing_reason=(
                f"fitness_score=0 chat_only gate | prior: {macro_plan.routing_reason}"
            ),
        ),
        ["forced_chat_only:fitness_score"],
    )


def validate_and_patch_macro_plan(
    user_input: str,
    macro_plan: MacroPlanSchema,
    semantic_profile: list[dict[str, Any]] | None,
    intent_state: IntentState | None = None,
) -> tuple[MacroPlanSchema, list[str]]:
    """
    Post-macro policy enforcement. Returns patched plan and audit action labels.
    """
    plan, actions = apply_chat_only_gate(macro_plan, intent_state)
    if plan.routing_mode == "chat_only":
        return plan, actions

    if not plan.selected_tools:
        return plan, actions

    plan, id_actions = ensure_unique_macro_task_ids(plan)
    actions.extend(id_actions)

    if not plan.selected_tools:
        return plan, actions

    if requires_graph_for_safety(user_input, intent_state) and not has_graph_tool(plan):
        plan = inject_graph_tool(
            plan,
            user_input,
            "safety keyword or safety slot requires graph_tool",
        )
        actions.append("injected_graph_tool:safety")

    triggered_joints = injured_joints_triggered(user_input, semantic_profile)
    if triggered_joints and not has_graph_tool(plan):
        joints_label = ",".join(triggered_joints)
        plan = inject_graph_tool(
            plan,
            user_input,
            f"profile injuries [{joints_label}] + sensitive training requires graph_tool",
        )
        actions.append(f"injected_graph_tool:joints:{joints_label}")

    return plan, actions
