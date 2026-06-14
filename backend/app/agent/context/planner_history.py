"""Compact chat history for macro planner — avoid full CoachResponse JSON in context."""

from __future__ import annotations

from pydantic import ValidationError

from app.models.schema import CoachResponse

_SUMMARY_MAX_CHARS = 180
_SAFETY_MAX_CHARS = 150
_PLAIN_ASSISTANT_MAX_CHARS = 320
_PLAIN_USER_MAX_CHARS = 400


def _truncate(text: str, max_chars: int) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "…"


def compact_coach_response_for_planner(response: CoachResponse) -> str:
    """Structured coach reply → short planner-facing summary."""
    lines = [f"【上轮教练回复·{response.response_type}】"]

    if response.exercises:
        names = [ex.name_zh for ex in response.exercises if ex.name_zh][:8]
        if names:
            lines.append(f"已推荐动作: {', '.join(names)}")

    if response.greeting.strip() and not response.exercises:
        lines.append(f"开场: {_truncate(response.greeting, 80)}")

    if response.summary.strip():
        lines.append(f"总结: {_truncate(response.summary, _SUMMARY_MAX_CHARS)}")

    if response.safety_alerts:
        alerts = "; ".join(response.safety_alerts[:2])
        lines.append(f"安全提示: {_truncate(alerts, _SAFETY_MAX_CHARS)}")

    if response.selected_tools:
        lines.append(f"使用工具: {', '.join(response.selected_tools)}")

    if response.detailed_guidance and not response.exercises:
        lines.append("(详细指导正文已省略，仅保留摘要供续聊路由)")

    return "\n".join(lines)


def compact_message_for_planner(role: str, content: str) -> str:
    stripped = (content or "").strip()
    if not stripped:
        return stripped

    if role == "assistant" and stripped.startswith("{"):
        try:
            response = CoachResponse.model_validate_json(stripped)
            return compact_coach_response_for_planner(response)
        except (ValidationError, ValueError):
            pass
        return _truncate(stripped, _PLAIN_ASSISTANT_MAX_CHARS)

    if role == "assistant":
        return _truncate(stripped, _PLAIN_ASSISTANT_MAX_CHARS)

    if role == "user":
        return _truncate(stripped, _PLAIN_USER_MAX_CHARS)

    return stripped


def build_planner_history_messages(
    history_messages: list[dict[str, str]],
    *,
    max_turns: int = 2,
) -> list[dict[str, str]]:
    """Last N turns with assistant replies compacted for macro planner context."""
    if not history_messages:
        return []

    max_messages = max(1, max_turns) * 2
    trimmed = history_messages[-max_messages:]
    return [
        {
            "role": msg.get("role", "user"),
            "content": compact_message_for_planner(
                msg.get("role", "user"),
                msg.get("content", ""),
            ),
        }
        for msg in trimmed
    ]
