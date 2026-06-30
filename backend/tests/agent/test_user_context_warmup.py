"""Tests for per-user login warmup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.cache.warmup import warmup_user_context


@pytest.mark.asyncio
async def test_warmup_user_context_fetches_profile_and_intent(monkeypatch):
    graph_tool = MagicMock()
    graph_tool.fetch_user_semantic_memory = AsyncMock(
        return_value=[{"injuries": ["腕关节"], "equipment_list": ["哑铃"], "level": "intermediate"}]
    )
    sql_tool = MagicMock()

    fetch_mock = AsyncMock(
        return_value=[{"injuries": ["腕关节"], "equipment_list": ["哑铃"], "level": "intermediate"}]
    )
    prefetch_mock = AsyncMock(return_value=(MagicMock(term_count=10), {"腕关节": frozenset()}))

    monkeypatch.setattr(
        "app.agent.cache.warmup.fetch_semantic_profile_cached",
        fetch_mock,
    )
    monkeypatch.setattr(
        "app.agent.cache.warmup.prefetch_intent_resources",
        prefetch_mock,
    )

    await warmup_user_context(42, graph_tool, sql_tool)

    fetch_mock.assert_awaited_once_with(42, graph_tool.fetch_user_semantic_memory)
    prefetch_mock.assert_awaited_once_with(sql_tool, graph_tool)
