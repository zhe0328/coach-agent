"""DeepEval agent trajectory evaluation entry point."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.eval.paths import (
    AGENT_TEST_FILE,
    DEFAULT_AGENT_DATASET,
    resolve_dataset,
)


@dataclass(frozen=True)
class DeepevalEvalResult:
    exit_code: int
    dataset_path: Path
    limit: int | None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        limit_note = f", limit={self.limit}" if self.limit is not None else ""
        return (
            f"DeepEval agent eval {status}: dataset={self.dataset_path.name}"
            f"{limit_note}, exit_code={self.exit_code}"
        )


def run_deepeval_eval(
    *,
    dataset_path: str | Path | None = None,
    limit: int | None = None,
    pytest_args: list[str] | None = None,
) -> DeepevalEvalResult:
    """
    Run the agent quality pytest module.

    The underlying tests live in tests/agent/test_agent_quality.py and write
    CSV output via the DeepEval hook when the full run completes.
    """
    resolved_dataset = resolve_dataset(dataset_path, DEFAULT_AGENT_DATASET)
    if not resolved_dataset.exists():
        raise FileNotFoundError(f"Agent dataset not found: {resolved_dataset}")

    previous_dataset = os.environ.get("COACH_EVAL_AGENT_DATASET")
    previous_limit = os.environ.get("COACH_EVAL_LIMIT")
    os.environ["COACH_EVAL_AGENT_DATASET"] = str(resolved_dataset)
    if limit is not None:
        os.environ["COACH_EVAL_LIMIT"] = str(limit)
    elif "COACH_EVAL_LIMIT" in os.environ:
        del os.environ["COACH_EVAL_LIMIT"]

    args = [str(AGENT_TEST_FILE), "-q"]
    if pytest_args:
        args.extend(pytest_args)

    try:
        exit_code = pytest.main(args)
    finally:
        if previous_dataset is None:
            os.environ.pop("COACH_EVAL_AGENT_DATASET", None)
        else:
            os.environ["COACH_EVAL_AGENT_DATASET"] = previous_dataset

        if previous_limit is None:
            os.environ.pop("COACH_EVAL_LIMIT", None)
        else:
            os.environ["COACH_EVAL_LIMIT"] = previous_limit

    return DeepevalEvalResult(
        exit_code=exit_code,
        dataset_path=resolved_dataset,
        limit=limit,
    )
