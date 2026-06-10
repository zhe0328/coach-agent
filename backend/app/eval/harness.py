"""Unified eval harness CLI for coach-agent."""

from __future__ import annotations

import argparse
import sys

from app.eval.deepeval_eval import run_deepeval_eval
from app.eval.ragas_eval import run_ragas_eval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run coach-agent offline evaluation suites (RAG + agent)."
    )
    parser.add_argument(
        "--suite",
        choices=["rag", "agent", "all"],
        required=True,
        help="Which eval suite to run.",
    )
    parser.add_argument(
        "--dataset",
        help="Override dataset path (relative to backend/ or absolute).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N golden cases (useful during development).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for CSV reports (default: tests/results).",
    )
    return parser


def run_harness(
    *,
    suite: str,
    dataset: str | None = None,
    limit: int | None = None,
    output_dir: str | None = None,
) -> int:
    summaries: list[str] = []
    exit_code = 0

    if suite in {"rag", "all"}:
        rag_result = run_ragas_eval(
            dataset_path=dataset if suite == "rag" else None,
            limit=limit,
            output_dir=output_dir,
        )
        print(rag_result.summary())
        if rag_result.output_path:
            print(f"RAG report: {rag_result.output_path}")
        if not rag_result.passed:
            exit_code = 1
        summaries.append(rag_result.summary())

    if suite in {"agent", "all"}:
        agent_result = run_deepeval_eval(
            dataset_path=dataset if suite == "agent" else None,
            limit=limit,
            output_dir=output_dir,
        )
        print(agent_result.summary())
        if agent_result.output_path:
            print(f"Agent report: {agent_result.output_path}")
        if not agent_result.passed:
            exit_code = 1
        summaries.append(agent_result.summary())

    if suite == "all" and exit_code == 0:
        print("All eval suites passed.")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_harness(
        suite=args.suite,
        dataset=args.dataset,
        limit=args.limit,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
