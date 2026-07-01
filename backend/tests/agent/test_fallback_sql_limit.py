"""Tests for offline fallback SQL limit derived from user input."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agent.orchestrator import CoachOrchestrator


def _orch() -> CoachOrchestrator:
    return CoachOrchestrator(MagicMock())


def test_fallback_sql_limit_from_multi_clause_query():
    orch = _orch()
    macro, full = orch._build_fallback_plans("3个练背+3个练臀动作")

    assert macro.selected_tools[0].limit == 6
    assert full.tasks[0].sql_params.limit == 6


def test_fallback_sql_limit_defaults_to_four():
    orch = _orch()
    macro, full = orch._build_fallback_plans("推荐练腿动作")

    assert macro.selected_tools[0].limit == 4
    assert full.tasks[0].sql_params.limit == 4
