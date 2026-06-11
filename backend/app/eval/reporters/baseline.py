"""Baseline loading and regression comparison for eval harness runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASELINE_PATH = Path(__file__).resolve().parent.parent / "baseline.json"
DEFAULT_MAX_DROP_PCT = 0.05

DEFAULT_BASELINE: dict[str, Any] = {
    "rag": {
        "context_recall": 0.70,
        "context_precision": 0.83,
    },
    "agent": {
        "trajectory": 0.99,
        "faithfulness": 0.92,
        "safety": 0.81,
        "relevancy": 0.85,
        "tool_trace_accuracy": 1.0,
    },
    "regression": {
        "max_drop_pct": DEFAULT_MAX_DROP_PCT,
    },
}


@dataclass(frozen=True)
class MetricRegression:
    suite: str
    metric: str
    baseline: float
    current: float
    min_allowed: float

    def message(self) -> str:
        drop_pct = 0.0 if self.baseline == 0 else (self.baseline - self.current) / self.baseline
        return (
            f"{self.suite}.{self.metric} regressed: "
            f"current={self.current:.3f}, baseline={self.baseline:.3f}, "
            f"drop={drop_pct:.1%}, min_allowed={self.min_allowed:.3f}"
        )


@dataclass
class BaselineComparison:
    passed: bool
    regressions: list[MetricRegression] = field(default_factory=list)

    def summary(self) -> str:
        if self.passed:
            return "Baseline comparison PASSED"
        lines = ["Baseline comparison FAILED:"]
        lines.extend(f"  - {item.message()}" for item in self.regressions)
        return "\n".join(lines)


def load_baseline(path: str | Path | None = None) -> dict[str, Any]:
    baseline_path = Path(path) if path else DEFAULT_BASELINE_PATH
    if baseline_path.exists():
        with open(baseline_path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return _merge_baseline(DEFAULT_BASELINE, loaded)
    return DEFAULT_BASELINE.copy()


def _merge_baseline(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(defaults))
    for section, values in overrides.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _max_drop_pct(baseline: dict[str, Any]) -> float:
    return float(baseline.get("regression", {}).get("max_drop_pct", DEFAULT_MAX_DROP_PCT))


def _min_allowed(baseline_value: float, max_drop_pct: float) -> float:
    return baseline_value * (1.0 - max_drop_pct)


def _check_metric(
    *,
    suite: str,
    metric: str,
    current: float,
    baseline_value: float,
    max_drop_pct: float,
    regressions: list[MetricRegression],
) -> None:
    min_allowed = _min_allowed(baseline_value, max_drop_pct)
    if current + 1e-9 < min_allowed:
        regressions.append(
            MetricRegression(
                suite=suite,
                metric=metric,
                baseline=baseline_value,
                current=current,
                min_allowed=min_allowed,
            )
        )


def compare_rag_baseline(
    *,
    mean_context_recall: float,
    mean_context_precision: float,
    baseline: dict[str, Any] | None = None,
) -> BaselineComparison:
    baseline_data = baseline or load_baseline()
    max_drop_pct = _max_drop_pct(baseline_data)
    rag_base = baseline_data["rag"]
    regressions: list[MetricRegression] = []

    _check_metric(
        suite="rag",
        metric="context_recall",
        current=mean_context_recall,
        baseline_value=float(rag_base["context_recall"]),
        max_drop_pct=max_drop_pct,
        regressions=regressions,
    )
    _check_metric(
        suite="rag",
        metric="context_precision",
        current=mean_context_precision,
        baseline_value=float(rag_base["context_precision"]),
        max_drop_pct=max_drop_pct,
        regressions=regressions,
    )

    return BaselineComparison(passed=not regressions, regressions=regressions)


def compare_agent_baseline(
    *,
    mean_trajectory: float,
    mean_faithfulness: float,
    mean_safety: float,
    mean_relevancy: float,
    mean_tool_trace_accuracy: float,
    baseline: dict[str, Any] | None = None,
) -> BaselineComparison:
    baseline_data = baseline or load_baseline()
    max_drop_pct = _max_drop_pct(baseline_data)
    agent_base = baseline_data["agent"]
    regressions: list[MetricRegression] = []

    for metric, current in (
        ("trajectory", mean_trajectory),
        ("faithfulness", mean_faithfulness),
        ("safety", mean_safety),
        ("relevancy", mean_relevancy),
        ("tool_trace_accuracy", mean_tool_trace_accuracy),
    ):
        _check_metric(
            suite="agent",
            metric=metric,
            current=current,
            baseline_value=float(agent_base[metric]),
            max_drop_pct=max_drop_pct,
            regressions=regressions,
        )

    return BaselineComparison(passed=not regressions, regressions=regressions)


def write_baseline(
    *,
    rag: dict[str, float] | None = None,
    agent: dict[str, float] | None = None,
    path: str | Path | None = None,
    max_drop_pct: float | None = None,
) -> Path:
    baseline_path = Path(path) if path else DEFAULT_BASELINE_PATH
    baseline_path.parent.mkdir(parents=True, exist_ok=True)

    payload = load_baseline(baseline_path)
    if rag:
        payload["rag"].update(rag)
    if agent:
        payload["agent"].update(agent)
    if max_drop_pct is not None:
        payload.setdefault("regression", {})["max_drop_pct"] = max_drop_pct

    with open(baseline_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return baseline_path
