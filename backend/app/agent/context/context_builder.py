"""Compile macro-planner context by P0–P3 priority with auditable segments."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.intent.intent_state import IntentState, format_intent_block
from app.agent.memory.state_patch import format_state_patch_block
from app.models.memory import WorkingMemory

Priority = Literal["P0", "P1", "P2", "P3"]
DEFAULT_BUDGET_TOKENS = 6000


class ContextSegment(BaseModel):
    segment_id: str
    priority: Priority
    source: str
    reason: str
    content: str
    estimated_tokens: int = 0
    droppable: bool = False
    included: bool = True


class PlannerContextBundle(BaseModel):
    current_request: str
    segments: list[ContextSegment] = Field(default_factory=list)
    history_messages: list[dict[str, str]] = Field(default_factory=list)
    budget_max_tokens: int = DEFAULT_BUDGET_TOKENS
    used_tokens: int = 0

    def explain(self) -> list[dict[str, Any]]:
        return [
            {
                "segment_id": s.segment_id,
                "priority": s.priority,
                "source": s.source,
                "reason": s.reason,
                "included": s.included,
                "estimated_tokens": s.estimated_tokens,
            }
            for s in self.segments
        ]


def estimate_tokens(text: str) -> int:
    stripped = (text or "").strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 2)


def _semantic_constraints_block(semantic_profile: list[dict[str, Any]]) -> str:
    if not semantic_profile:
        return ""
    profile = semantic_profile[0]
    injuries = profile.get("injuries") or []
    equipment = profile.get("equipment_list") or []
    return (
        f"【来自图数据库（Neo4j）的当前用户长效硬性指标与物理红线】:\n"
        f"- 用户当前体能级别硬钢印: {profile.get('level', 'beginner')}\n"
        f"- 用户当前【主诉受损/严禁过度负载】的身体关节: "
        f"{', '.join(injuries) if injuries else '全身健康无受损'}\n"
        f"- 用户家里目前【仅拥有且仅能调遣】的常备训练器械库: "
        f"{', '.join(equipment) if equipment else '自重'}\n\n"
        f"【最高硬核调度约束】：\n"
        f"1. 安全红线：如果受损关节与本轮训练相关，"
        f"你【必须且强制】选装图任务实例（task_graph_injury）去从医学图谱层面严格拉黑并剔除高风险重载动作！\n"
        f"2. 器械边界：在为工具拆分多任务实例（selected_tools）时，你配置的专属 `focused_query` 和 `reason` "
        f"中【必须严格限定器械范围】！\n"
        f"你【必须且强制】将当前用户的体能级别字面量「{profile.get('level', 'beginner')}」"
        f"作为核心约束词，直接写入 `focused_query` 文本中！\n\n"
    )


def build_planner_context(
    *,
    user_input: str,
    memory: WorkingMemory,
    semantic_profile: list[dict[str, Any]] | None,
    intent_state: IntentState | None,
    planner_history_messages: list[dict[str, str]] | None,
    budget_max_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> PlannerContextBundle:
    segments: list[ContextSegment] = []
    profile = semantic_profile or []
    history = list(planner_history_messages or [])

    semantic_block = _semantic_constraints_block(profile)
    if semantic_block:
        segments.append(
            ContextSegment(
                segment_id="semantic_profile",
                priority="P0",
                source="semantic_profile",
                reason="Neo4j user injuries/equipment/level hard constraints",
                content=semantic_block,
                estimated_tokens=estimate_tokens(semantic_block),
                droppable=False,
            )
        )

    current_block = f"【当前用户的最新发问】：\n\"{user_input}\"\n"
    segments.append(
        ContextSegment(
            segment_id="current_request",
            priority="P0",
            source="current_input",
            reason="Current turn user request — must never drop",
            content=current_block,
            estimated_tokens=estimate_tokens(current_block),
            droppable=False,
        )
    )

    if memory.latest_analyzer_feedback.strip():
        feedback_block = (
            "【自愈复盘报告 —— 你在上一轮由于调度不当被质检官打回了！】\n"
            f"- 质检官的反思修正指令: \"{memory.latest_analyzer_feedback}\"\n\n"
        )
        segments.append(
            ContextSegment(
                segment_id="analyzer_feedback",
                priority="P0",
                source="analyzer_feedback",
                reason="Analyzer retry instruction for macro replan",
                content=feedback_block,
                estimated_tokens=estimate_tokens(feedback_block),
                droppable=False,
            )
        )

    state_patch_block = format_state_patch_block(memory.state_patch)
    if state_patch_block:
        segments.append(
            ContextSegment(
                segment_id="state_patch",
                priority="P1",
                source="state_patch",
                reason="Structured warm memory: goal, constraints, open questions",
                content=state_patch_block,
                estimated_tokens=estimate_tokens(state_patch_block),
                droppable=False,
            )
        )

    if intent_state:
        intent_block = format_intent_block(intent_state)
        segments.append(
            ContextSegment(
                segment_id="intent_state",
                priority="P1",
                source="intent_projector",
                reason="Projected slots, fitness_score, routing_hint",
                content=intent_block,
                estimated_tokens=estimate_tokens(intent_block),
                droppable=False,
            )
        )

    if history:
        history_chars = sum(len(m.get("content", "")) for m in history)
        segments.append(
            ContextSegment(
                segment_id="recent_history",
                priority="P2",
                source="chat_history",
                reason=f"Last {len(history)//2} turns for dialogue continuity",
                content="",
                estimated_tokens=max(1, history_chars // 2),
                droppable=True,
            )
        )

    summary = memory.session_summary.strip()
    if summary:
        summary_block = f"【本对话较早轮次摘要（warm memory）】:\n{summary}\n\n"
        segments.append(
            ContextSegment(
                segment_id="session_summary",
                priority="P3",
                source="session_summary",
                reason="Compressed older turns — drop first under budget pressure",
                content=summary_block,
                estimated_tokens=estimate_tokens(summary_block),
                droppable=True,
            )
        )

    bundle = PlannerContextBundle(
        current_request=user_input,
        segments=segments,
        history_messages=history,
        budget_max_tokens=budget_max_tokens,
    )
    return fit_context_to_budget(bundle)


def fit_context_to_budget(bundle: PlannerContextBundle) -> PlannerContextBundle:
    """Drop or trim P3 → P2 segments until within token budget. P0/P1 never dropped."""
    used = sum(s.estimated_tokens for s in bundle.segments if s.included)
    used += sum(
        estimate_tokens(m.get("content", "")) for m in bundle.history_messages
    )
    bundle.used_tokens = used

    if used <= bundle.budget_max_tokens:
        return bundle

    for segment in bundle.segments:
        if used <= bundle.budget_max_tokens:
            break
        if not segment.droppable or not segment.included:
            continue
        used -= segment.estimated_tokens
        segment.included = False

    while used > bundle.budget_max_tokens and len(bundle.history_messages) > 2:
        removed = bundle.history_messages.pop(0)
        used -= estimate_tokens(removed.get("content", ""))
        hist_seg = next(
            (s for s in bundle.segments if s.segment_id == "recent_history"), None
        )
        if hist_seg:
            hist_seg.estimated_tokens = sum(
                estimate_tokens(m.get("content", ""))
                for m in bundle.history_messages
            )

    bundle.used_tokens = used
    return bundle


def compile_macro_user_content(bundle: PlannerContextBundle) -> str:
    """Assemble included text segments in priority order (excluding history)."""
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    parts: list[str] = []
    for segment in sorted(
        bundle.segments,
        key=lambda s: (order[s.priority], s.segment_id),
    ):
        if segment.included and segment.content.strip():
            parts.append(segment.content)
    return "".join(parts)


def compile_macro_messages(
    bundle: PlannerContextBundle,
    system_prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    hist_seg = next(
        (s for s in bundle.segments if s.segment_id == "recent_history"), None
    )
    if hist_seg and hist_seg.included and bundle.history_messages:
        messages.extend(bundle.history_messages)

    user_content = compile_macro_user_content(bundle)
    messages.append({"role": "user", "content": user_content})
    return messages
