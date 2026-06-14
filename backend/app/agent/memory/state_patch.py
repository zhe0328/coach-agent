from __future__ import annotations

from app.models.memory import ChatMessage, SessionStatePatch

_QUESTION_MARKERS = ("?", "？", "吗", "怎么", "为什么", "能否", "可不可以", "行不行")


def merge_state_patch_from_pruned(
    patch: SessionStatePatch,
    pruned: list[ChatMessage],
) -> SessionStatePatch:
    updated = patch.model_copy(deep=True)

    for msg in pruned:
        if msg.role != "user":
            continue
        content = msg.content.strip()
        if not content:
            continue
        updated.user_goal = content[:200]
        if any(marker in content for marker in _QUESTION_MARKERS):
            snippet = content[:120]
            if snippet not in updated.open_questions:
                updated.open_questions.append(snippet)
        if len(updated.open_questions) > 5:
            updated.open_questions = updated.open_questions[-5:]

    return updated


def merge_state_patch_from_intent(
    patch: SessionStatePatch,
    *,
    user_goal: str,
    constraints: list[str],
    slots: list[str],
) -> SessionStatePatch:
    updated = patch.model_copy(deep=True)
    if user_goal.strip():
        updated.user_goal = user_goal.strip()[:200]
    for c in constraints:
        if c and c not in updated.hard_constraints:
            updated.hard_constraints.append(c)
    if len(updated.hard_constraints) > 8:
        updated.hard_constraints = updated.hard_constraints[-8:]
    if slots:
        updated.active_intent_slots = slots
    return updated


def format_state_patch_block(patch: SessionStatePatch) -> str:
    if not any(
        [
            patch.user_goal,
            patch.open_questions,
            patch.hard_constraints,
            patch.active_intent_slots,
        ]
    ):
        return ""

    lines = ["【结构化会话状态 StatePatch】"]
    if patch.user_goal:
        lines.append(f"- user_goal: {patch.user_goal}")
    if patch.active_intent_slots:
        lines.append(f"- active_slots: {', '.join(patch.active_intent_slots)}")
    if patch.hard_constraints:
        lines.append(f"- hard_constraints: {'; '.join(patch.hard_constraints)}")
    if patch.open_questions:
        lines.append(f"- open_questions: {' | '.join(patch.open_questions)}")
    return "\n".join(lines) + "\n\n"
