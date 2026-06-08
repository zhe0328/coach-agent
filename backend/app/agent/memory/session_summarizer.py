from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.models.memory import ChatMessage

SummarizeFn = Callable[[list[ChatMessage]], Awaitable[str] | str]


def merge_session_summary(existing: str, new_chunk: str, *, max_chars: int = 4000) -> str:
    chunk = (new_chunk or "").strip()
    if not chunk:
        return existing or ""
    if not existing:
        merged = chunk
    else:
        merged = f"{existing.strip()}\n{chunk}"
    if len(merged) <= max_chars:
        return merged
    return merged[-max_chars:]


def _deterministic_summary(messages: list[ChatMessage]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = "用户" if msg.role == "user" else "教练"
        content = " ".join(msg.content.split())
        if len(content) > 160:
            content = content[:160] + "…"
        lines.append(f"- {role}: {content}")
    return "\n".join(lines)


async def summarize_pruned_turns(
    messages: list[ChatMessage],
    *,
    client: Any = None,
    summarize_fn: SummarizeFn | None = None,
) -> str:
    if not messages:
        return ""

    if summarize_fn is not None:
        result = summarize_fn(messages)
        if asyncio.iscoroutine(result):
            return (await result).strip()
        return str(result).strip()

    if client is None:
        return _deterministic_summary(messages)

    transcript = "\n".join(
        f"{msg.role}: {msg.content[:500]}" for msg in messages
    )
    system_prompt = (
        "你是健身教练对话摘要器。将以下被移出短期记忆窗口的历史对话"
        "压缩为简洁中文要点，保留：训练目标、伤病/器械变更、已推荐动作、用户偏好。"
        "不要编造，控制在 200 字以内。"
    )

    def _call_llm():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
            max_tokens=300,
        )

    response = await asyncio.to_thread(_call_llm)
    return (response.choices[0].message.content or "").strip()
