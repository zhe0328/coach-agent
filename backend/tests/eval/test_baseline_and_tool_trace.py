"""Tests for baseline regression and tool trace metrics."""

from __future__ import annotations

import json

import pytest

from app.eval.metrics.tool_trace import check_tool_trace
from app.eval.reporters.baseline import (
    compare_agent_baseline,
    compare_rag_baseline,
    load_baseline,
    write_baseline,
)


class TestToolTrace:
    def test_passes_on_exact_match(self):
        result = check_tool_trace(
            ["rag_tool", "sql_tool"],
            ["sql_tool", "rag_tool"],
        )
        assert result.passed is True
        assert result.missing_tools == []
        assert result.extra_tools == []

    def test_fails_when_tool_missing(self):
        result = check_tool_trace(
            ["rag_tool", "graph_tool"],
            ["rag_tool"],
        )
        assert result.passed is False
        assert result.missing_tools == ["graph_tool"]

    def test_passes_when_no_expected_tools(self):
        result = check_tool_trace([], ["rag_tool"])
        assert result.passed is True
        assert result.accuracy == 1.0


class TestBaselineComparison:
    def test_rag_regression_detects_recall_drop(self):
        baseline = load_baseline()
        comparison = compare_rag_baseline(
            mean_context_recall=0.60,
            mean_context_precision=0.90,
            baseline=baseline,
        )
        assert comparison.passed is False
        assert any(item.metric == "context_recall" for item in comparison.regressions)

    def test_agent_regression_detects_safety_drop(self):
        baseline = load_baseline()
        comparison = compare_agent_baseline(
            mean_trajectory=0.99,
            mean_faithfulness=0.92,
            mean_safety=0.70,
            mean_relevancy=0.85,
            mean_tool_trace_accuracy=1.0,
            baseline=baseline,
        )
        assert comparison.passed is False
        assert any(item.metric == "safety" for item in comparison.regressions)

    def test_agent_passes_at_baseline(self):
        baseline = load_baseline()
        comparison = compare_agent_baseline(
            mean_trajectory=0.99,
            mean_faithfulness=0.92,
            mean_safety=0.81,
            mean_relevancy=0.85,
            mean_tool_trace_accuracy=1.0,
            baseline=baseline,
        )
        assert comparison.passed is True


class TestWriteBaseline:
    def test_write_baseline_merges_sections(self, tmp_path):
        path = tmp_path / "baseline.json"
        write_baseline(
            rag={"context_recall": 0.75, "context_precision": 0.84},
            path=path,
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["rag"]["context_recall"] == 0.75
        assert payload["agent"]["safety"] == 0.81
