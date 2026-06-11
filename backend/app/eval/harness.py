"""Unified eval harness CLI for coach-agent."""

from __future__ import annotations

import argparse
import sys

from app.eval.deepeval_eval import run_deepeval_eval
from app.eval.ragas_eval import run_ragas_eval
from app.eval.reporters.baseline import (
    compare_agent_baseline,
    compare_rag_baseline,
    load_baseline,
    write_baseline,
)


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
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Fail if mean metrics drop more than baseline max_drop_pct (default 5%%).",
    )
    parser.add_argument(
        "--baseline-path",
        default=None,
        help="Baseline JSON path (default: tests/results/baseline.json).",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write current run metrics to baseline JSON (developer utility).",
    )
    return parser


def run_harness(
    *,
    suite: str,
    dataset: str | None = None,
    limit: int | None = None,
    output_dir: str | None = None,
    compare_baseline: bool = False,
    baseline_path: str | None = None,
    write_baseline_flag: bool = False,
) -> int:
    exit_code = 0
    baseline = load_baseline(baseline_path)
    rag_metrics: dict[str, float] | None = None
    agent_metrics: dict[str, float] | None = None

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

        rag_metrics = {
            "context_recall": rag_result.mean_context_recall,
            "context_precision": rag_result.mean_context_precision,
        }

        if compare_baseline:
            comparison = compare_rag_baseline(
                mean_context_recall=rag_result.mean_context_recall,
                mean_context_precision=rag_result.mean_context_precision,
                baseline=baseline,
            )
            print(comparison.summary())
            if not comparison.passed:
                exit_code = 1

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

        agent_metrics = {
            "trajectory": agent_result.mean_trajectory,
            "faithfulness": agent_result.mean_faithfulness,
            "safety": agent_result.mean_safety,
            "relevancy": agent_result.mean_relevancy,
            "tool_trace_accuracy": agent_result.mean_tool_trace_accuracy,
        }

        if compare_baseline:
            comparison = compare_agent_baseline(
                mean_trajectory=agent_result.mean_trajectory,
                mean_faithfulness=agent_result.mean_faithfulness,
                mean_safety=agent_result.mean_safety,
                mean_relevancy=agent_result.mean_relevancy,
                mean_tool_trace_accuracy=agent_result.mean_tool_trace_accuracy,
                baseline=baseline,
            )
            print(comparison.summary())
            if not comparison.passed:
                exit_code = 1

    if write_baseline_flag:
        path = write_baseline(
            rag=rag_metrics,
            agent=agent_metrics,
            path=baseline_path,
        )
        print(f"Baseline written: {path}")

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
        compare_baseline=args.compare_baseline,
        baseline_path=args.baseline_path,
        write_baseline_flag=args.write_baseline,
    )


if __name__ == "__main__":
    sys.exit(main())
