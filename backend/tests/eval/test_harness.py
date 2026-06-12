"""Unit tests for the eval harness (no API keys required)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.eval.harness import build_parser, run_harness
from app.eval.paths import (
    BACKEND_ROOT,
    DATASET_DIR,
    DEFAULT_RAG_DATASET,
    SMOKE_AGENT_DATASET,
    SMOKE_RAG_DATASET,
    dataset,
    resolve_dataset,
)


class TestEvalPaths:
    def test_backend_root_points_at_backend(self):
        assert BACKEND_ROOT.name == "backend"
        assert (BACKEND_ROOT / "app" / "eval").is_dir()

    def test_smoke_datasets_exist(self):
        assert SMOKE_RAG_DATASET.is_file()
        assert SMOKE_AGENT_DATASET.is_file()

    def test_dataset_helper(self):
        assert dataset("fitness_ground_truth.json") == DATASET_DIR / "fitness_ground_truth.json"

    def test_resolve_dataset_relative_to_backend(self):
        resolved = resolve_dataset(
            "app/eval/datasets/smoke/rag_smoke.json",
            DEFAULT_RAG_DATASET,
        )
        assert resolved == SMOKE_RAG_DATASET


class TestHarnessCLI:
    def test_parser_requires_suite(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_accepts_limit(self):
        parser = build_parser()
        args = parser.parse_args(["--suite", "rag", "--limit", "3"])
        assert args.suite == "rag"
        assert args.limit == 3

    def test_parser_accepts_compare_baseline(self):
        parser = build_parser()
        args = parser.parse_args(["--suite", "rag", "--compare-baseline"])
        assert args.compare_baseline is True


class TestEvalNoPersist:
    def test_enable_eval_no_persist_sets_flag(self, monkeypatch):
        from app.config import settings
        from app.eval.deepeval_eval import enable_eval_no_persist

        monkeypatch.setattr(settings, "EVAL_NO_PERSIST", False)
        enable_eval_no_persist()
        assert settings.EVAL_NO_PERSIST is True
        assert os.environ.get("COACH_EVAL_NO_PERSIST") == "1"


class TestHarnessDryRun:
    def test_rag_suite_with_limit_calls_runner(self, monkeypatch, tmp_path: Path):
        calls: dict = {}

        class FakeResult:
            case_count = 2
            mean_context_recall = 0.9
            mean_context_precision = 0.9
            output_path = tmp_path / "rag_eval_latest.csv"
            passed = True

            def summary(self):
                return "ok"

        def fake_run_ragas_eval(**kwargs):
            calls.update(kwargs)
            return FakeResult()

        monkeypatch.setattr("app.eval.harness.run_ragas_eval", fake_run_ragas_eval)
        exit_code = run_harness(
            suite="rag",
            limit=2,
            output_dir=str(tmp_path),
        )
        assert exit_code == 0
        assert calls["limit"] == 2
        assert calls["output_dir"] == str(tmp_path)

    def test_agent_suite_with_limit_calls_runner(self, monkeypatch, tmp_path: Path):
        calls: dict = {}

        class FakeAgentResult:
            case_count = 2
            passed_count = 2
            mean_trajectory = 0.9
            mean_faithfulness = 0.9
            mean_safety = 0.9
            mean_relevancy = 0.9
            mean_tool_trace_accuracy = 1.0
            tool_trace_pass_count = 2
            dataset_path = tmp_path / "agent.json"
            output_path = tmp_path / "coach_agent_report_new.csv"
            limit = 2
            passed = True

            def summary(self):
                return "agent ok"

        def fake_run_deepeval_eval(**kwargs):
            calls.update(kwargs)
            return FakeAgentResult()

        monkeypatch.setattr("app.eval.harness.run_deepeval_eval", fake_run_deepeval_eval)
        exit_code = run_harness(
            suite="agent",
            limit=2,
            output_dir=str(tmp_path),
        )
        assert exit_code == 0
        assert calls["limit"] == 2
        assert calls["output_dir"] == str(tmp_path)
