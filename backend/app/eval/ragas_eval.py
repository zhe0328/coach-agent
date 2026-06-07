"""
Ragas retrieval evaluation entry point.

Full metric wiring lives in tests/tools/test_rag_quality.py; this module provides
a stable import path for CI and the Phase 5 eval harness.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2] / "tests/dataset/fitness_ground_truth.json"
)


def load_dataset(dataset_path: str | Path | None = None) -> list[dict]:
    path = Path(dataset_path) if dataset_path else DEFAULT_DATASET
    if not path.exists():
        raise FileNotFoundError(f"Ragas dataset not found: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def run_ragas_eval(dataset_path: str | Path | None = None) -> str:
    """
    Run the Ragas retrieval suite via pytest.

    Returns a short status message for CLI / CI callers.
    """
    import pytest

    dataset = load_dataset(dataset_path)
    exit_code = pytest.main(
        [
            str(Path(__file__).resolve().parents[2] / "tests/tools/test_rag_quality.py"),
            "-q",
        ]
    )
    if exit_code != 0:
        raise RuntimeError(f"Ragas eval failed (exit {exit_code})")
    return f"Ragas eval passed ({len(dataset)} golden cases in dataset)"
