"""Deterministic macro planner fast-path — skip LLM for common routing patterns."""

from __future__ import annotations

import re
from typing import Any

from app.agent.analyzer_fast_path import extract_requested_action_count
from app.agent.intent.intent_state import IntentState, profile_has_spine_injury
from app.agent.policy.intent_validators import requires_graph_for_safety
from app.agent.policy.routing_keywords import SPINE_TRAINING_KEYWORDS
from app.models.schema import MacroPlanSchema, ToolCallIntent

_MULTI_SPLIT_MARKERS = ("还要", "同时", "以及", "另外", "再者", "并且", "顺便")
_ACTION_LIMIT_RE = re.compile(
    r"(?:推荐\s*)?(?:[一二两三四五六七八九十\d]+)\s*个"
)
_TRAINING_TARGET_RE = re.compile(r"练[\u4e00-\u9fff]{1,8}")
_COMPOUND_KNOWLEDGE_PHRASES = frozenset(
    {
        "注意事项",
        "注意点",
        "要点",
        "怎么做",
        "怎么练",
        "为什么",
        "原理",
        "会不会",
        "可以吗",
        "顺序",
        "先后",
    }
)
_PROGRESSION_KEYWORDS = frozenset(
    {"太难", "太易", "换一个", "进阶", "退阶", "协同", "退化", "升级"}
)
_RECOVERY_KEYWORDS = frozenset({"拉伸", "休息", "恢复", "放松", "热身", "冷身"})


def _profile_row(semantic_profile: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not semantic_profile:
        return {}
    return semantic_profile[0]


def _profile_injuries(semantic_profile: list[dict[str, Any]] | None) -> list[str]:
    injuries = _profile_row(semantic_profile).get("injuries") or []
    return [str(item) for item in injuries if item]


def _needs_graph_for_action(
    user_input: str,
    intent_state: IntentState | None,
    semantic_profile: list[dict[str, Any]] | None,
) -> bool:
    if requires_graph_for_safety(user_input, intent_state):
        return True
    if intent_state and "safety" in intent_state.slots:
        return True
    injuries = _profile_injuries(semantic_profile)
    if injuries and intent_state and "action_search" in intent_state.slots:
        return True
    if profile_has_spine_injury(semantic_profile):
        lowered = user_input.lower()
        if any(kw in user_input or kw in lowered for kw in SPINE_TRAINING_KEYWORDS):
            return True
    return False


def _count_action_limit_clauses(user_input: str) -> int:
    return len(_ACTION_LIMIT_RE.findall(user_input.strip()))


def _distinct_training_targets(user_input: str) -> set[str]:
    return set(_TRAINING_TARGET_RE.findall(user_input.strip()))


def _has_knowledge_companion(
    user_input: str,
    intent_state: IntentState | None,
) -> bool:
    if intent_state:
        slots = set(intent_state.slots)
        if "knowledge" in slots or "planning" in slots:
            return True
    return any(phrase in user_input for phrase in _COMPOUND_KNOWLEDGE_PHRASES)


def _needs_llm_macro_plan(
    user_input: str,
    intent_state: IntentState | None,
) -> bool:
    """Compound or multi-task queries must use the macro LLM."""
    if _looks_like_multi_instance_split(user_input):
        return True
    if _count_action_limit_clauses(user_input) >= 2:
        return True
    if len(_distinct_training_targets(user_input)) >= 2:
        return True
    if _is_explicit_action_search(user_input) and _has_knowledge_companion(
        user_input, intent_state
    ):
        return True
    return False


def _looks_like_multi_instance_split(user_input: str) -> bool:
    text = user_input.strip()
    if not text:
        return False
    if re.search(r"用.+练.+还.+用.+练", text):
        return True
    if any(marker in text for marker in _MULTI_SPLIT_MARKERS) and text.count("练") >= 2:
        return True
    equipment_targets = re.findall(r"(哑铃|弹力带|杠铃|自重).{0,12}练", text)
    if len(set(equipment_targets)) >= 2:
        return True
    return False


def _needs_progression_graph(user_input: str) -> bool:
    return any(kw in user_input for kw in _PROGRESSION_KEYWORDS)


def _is_recovery_guidance_query(user_input: str) -> bool:
    if extract_requested_action_count(user_input) is not None:
        return False
    if any(kw in user_input for kw in ("推荐", "筛选", "找动作", "给我")):
        return False
    return any(kw in user_input for kw in _RECOVERY_KEYWORDS)


def _is_explicit_action_search(user_input: str) -> bool:
    if extract_requested_action_count(user_input) is not None:
        return True
    return any(kw in user_input for kw in ("推荐", "筛选", "找几个", "给我", "来个"))


def _build_sql_focused_query(
    user_input: str,
    intent_state: IntentState | None,
    semantic_profile: list[dict[str, Any]] | None,
) -> str:
    goal = (intent_state.user_goal if intent_state else None) or user_input
    profile = _profile_row(semantic_profile)
    parts = [goal.strip()]
    level = profile.get("level")
    equipment = profile.get("equipment_list") or []
    if level:
        parts.append(f"体能级别 {level}")
    if equipment:
        parts.append(f"可用器械 {', '.join(equipment)}")
    return "；".join(parts)


def _build_graph_focused_query(
    user_input: str,
    semantic_profile: list[dict[str, Any]] | None,
) -> str:
    injuries = _profile_injuries(semantic_profile)
    if injuries:
        return (
            f"对受损关节 {', '.join(injuries)} 进行 injury_avoidance 安全风险评估："
            f"{user_input}"
        )
    return f"动作安全风险评估：{user_input}"


def _sql_task(
    user_input: str,
    intent_state: IntentState | None,
    semantic_profile: list[dict[str, Any]] | None,
    *,
    task_id: str = "task_sql_base",
) -> ToolCallIntent:
    requested = extract_requested_action_count(user_input)
    return ToolCallIntent(
        task_id=task_id,
        tool_name="sql_tool",
        reason="fast_path: structured action search",
        focused_query=_build_sql_focused_query(user_input, intent_state, semantic_profile),
        limit=requested if requested is not None else 4,
        depends_on=[],
    )


def _graph_task(
    user_input: str,
    semantic_profile: list[dict[str, Any]] | None,
    *,
    depends_on: list[str],
    task_id: str = "task_graph_injury",
) -> ToolCallIntent:
    return ToolCallIntent(
        task_id=task_id,
        tool_name="graph_tool",
        reason="fast_path: injury/safety graph screening",
        focused_query=_build_graph_focused_query(user_input, semantic_profile),
        depends_on=depends_on,
    )


def _rag_task(
    user_input: str,
    intent_state: IntentState | None,
    *,
    task_id: str = "task_rag_query",
) -> ToolCallIntent:
    rag_intent = "mixed"
    if intent_state and intent_state.rag_intent_hint:
        rag_intent = intent_state.rag_intent_hint
    return ToolCallIntent(
        task_id=task_id,
        tool_name="rag_tool",
        rag_intent=rag_intent,
        reason="fast_path: knowledge/recovery retrieval",
        focused_query=(intent_state.user_goal if intent_state else user_input),
        depends_on=[],
    )


def _plan(
    tools: list[ToolCallIntent],
    reason: str,
) -> MacroPlanSchema:
    return MacroPlanSchema(
        routing_mode="standard",
        selected_tools=tools,
        routing_reason=reason,
    )


def try_macro_fast_path(
    user_input: str,
    intent_state: IntentState | None,
    semantic_profile: list[dict[str, Any]] | None,
) -> tuple[MacroPlanSchema, str] | None:
    """
    Return (macro_plan, reason) when macro LLM can be skipped.
    Return None to fall through to LLM planning.
    """
    if intent_state is None:
        return None

    if intent_state.routing_hint == "chat_only_candidate":
        return None

    if "chitchat" in intent_state.slots and len(intent_state.slots) == 1:
        return None

    if "analyzer_feedback" in intent_state.source_refs:
        return None

    if _needs_llm_macro_plan(user_input, intent_state):
        return None

    if _needs_progression_graph(user_input):
        return None

    slots = set(intent_state.slots)
    has_action = "action_search" in slots
    has_knowledge = "knowledge" in slots or "planning" in slots
    needs_graph = _needs_graph_for_action(user_input, intent_state, semantic_profile)

    if _is_recovery_guidance_query(user_input):
        rag = _rag_task(user_input, intent_state, task_id="task_rag_stretch")
        tools: list[ToolCallIntent] = [rag]
        if needs_graph:
            tools.append(
                _graph_task(
                    user_input,
                    semantic_profile,
                    depends_on=[rag.task_id],
                )
            )
        label = "recovery_rag_graph" if len(tools) > 1 else "recovery_rag"
        return (_plan(tools, f"fast_path:{label}"), label)

    if has_knowledge and not has_action:
        return (
            _plan([_rag_task(user_input, intent_state)], "fast_path:knowledge_rag"),
            "knowledge_rag",
        )

    if has_knowledge and has_action and not _is_explicit_action_search(user_input):
        return (
            _plan([_rag_task(user_input, intent_state)], "fast_path:knowledge_rag"),
            "knowledge_rag",
        )

    if has_action and not has_knowledge:
        tools: list[ToolCallIntent] = [
            _sql_task(user_input, intent_state, semantic_profile)
        ]
        if needs_graph:
            tools.append(
                _graph_task(
                    user_input,
                    semantic_profile,
                    depends_on=[tools[0].task_id],
                )
            )
        label = "action_sql_graph" if needs_graph else "action_sql"
        return (_plan(tools, f"fast_path:{label}"), label)

    if has_action and has_knowledge:
        sql = _sql_task(user_input, intent_state, semantic_profile)
        tools = [sql, _rag_task(user_input, intent_state, task_id="task_rag_knowledge")]
        if needs_graph:
            tools.append(
                _graph_task(
                    user_input,
                    semantic_profile,
                    depends_on=[sql.task_id],
                    task_id="task_graph_injury",
                )
            )
        return (_plan(tools, "fast_path:action_sql_rag"), "action_sql_rag")

    if intent_state.rag_intent_hint and not has_action:
        return (
            _plan([_rag_task(user_input, intent_state)], "fast_path:rag_hint"),
            "rag_hint",
        )

    return None
