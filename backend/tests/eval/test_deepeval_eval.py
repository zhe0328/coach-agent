"""Unit tests for extracted agent eval helpers."""

from __future__ import annotations

from app.eval.deepeval_eval import load_agent_dataset
from app.eval.metrics.agent_metrics import AgentMetricScores, check_agent_passed
from app.eval.reporters.csv_reporter import write_agent_report_csv


class TestLoadAgentDataset:
    def test_load_default_dataset(self):
        rows = load_agent_dataset()
        assert len(rows) > 0
        assert "user_input" in rows[0]

    def test_load_with_limit(self):
        rows = load_agent_dataset(limit=2)
        assert len(rows) == 2


class TestAgentMetricPassLogic:
    def test_passes_when_all_thresholds_met(self):
        scores = AgentMetricScores(
            trajectory=0.9,
            faithfulness=0.8,
            safety=0.85,
            relevancy=0.75,
        )
        assert check_agent_passed(scores) is True

    def test_fails_when_safety_below_threshold(self):
        scores = AgentMetricScores(
            trajectory=0.9,
            faithfulness=0.8,
            safety=0.7,
            relevancy=0.75,
        )
        assert check_agent_passed(scores) is False


class TestAgentReportWriter:
    def test_write_agent_report_csv(self, tmp_path):
        path = write_agent_report_csv(
            [{"用户输入": "test", "测试状态": "通过"}],
            output_dir=tmp_path,
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8-sig")
        assert "用户输入" in content
        assert "test" in content
