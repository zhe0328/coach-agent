"""Unit tests for the eval harness (no API keys required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.harness import build_parser, run_harness
from app.eval.paths import (
    BACKEND_ROOT,
    DATASET_DIR,
    DEFAULT_AGENT_DATASET,
    DEFAULT_RAG_DATASET,
    dataset,
    resolve_dataset,
    resolve_output_dir,
)
from app.eval.ragas_eval import load_rag_dataset


class TestEvalPaths:
    def test_backend_root_points_at_backend(self):
        assert BACKEND_ROOT.name == "backend"
        assert (BACKEND_ROOT / "app" / "eval").is_dir()

    def test_default_datasets_exist(self):
        assert DEFAULT_RAG_DATASET.exists()
        assert DEFAULT_AGENT_DATASET.exists()

    def test_dataset_helper(self):
        assert dataset("fitness_ground_truth.json") == DATASET_DIR / "fitness_ground_truth.json"

    def test_resolve_dataset_relative_to_backend(self):
        resolved = resolve_dataset("tests/dataset/fitness_ground_truth.json", DEFAULT_RAG_DATASET)
        assert resolved == DEFAULT_RAG_DATASET

    def test_load_rag_dataset_returns_rows(self):
        rows = load_rag_dataset()
        assert len(rows) > 0
        assert "user_input" in rows[0]
        assert "reference_contexts" in rows[0]


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
