"""Golden routing eval — deterministic intent/routing invariants (IC-P2 #13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.paths import SMOKE_ROUTING_DATASET
from app.eval.routing_eval import evaluate_routing_case, load_routing_dataset, run_routing_eval


@pytest.fixture
def routing_cases() -> list[dict]:
    return load_routing_dataset(SMOKE_ROUTING_DATASET)


@pytest.mark.parametrize(
    "case_id",
    [
        "greeting_chat_only",
        "greeting_with_fitness_intent",
        "safety_requires_graph",
        "knee_profile_squat",
        "shoulder_profile_bench",
        "spine_profile_legs",
        "rag_knowledge_hint",
        "rag_exercise_hint",
        "noise_punctuation",
        "lexicon_longest_match",
    ],
)
def test_routing_smoke_case(routing_cases: list[dict], case_id: str):
    case = next(c for c in routing_cases if c["id"] == case_id)
    failures = evaluate_routing_case(case)
    assert failures == [], f"{case_id}: " + "; ".join(failures)


def test_routing_smoke_dataset_loads():
    cases = load_routing_dataset(SMOKE_ROUTING_DATASET)
    assert len(cases) >= 10
    assert all("id" in c and "input" in c for c in cases)


def test_routing_eval_runner_reports_all_pass():
    passed, total, reports = run_routing_eval(SMOKE_ROUTING_DATASET)
    assert passed == total, f"failures: {reports}"
    assert total >= 10
