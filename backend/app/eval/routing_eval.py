"""Deterministic routing eval — no live LLM required."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent.intent.fitness_lexicon import FitnessLexicon
from app.agent.intent.intent_state import project_intent
from app.agent.policy.intent_validators import (
    apply_chat_only_gate,
    injured_joints_triggered,
    validate_and_patch_macro_plan,
)
from app.models.schema import MacroPlanSchema, ToolCallIntent


def _sql_only_plan(focused: str = "练胸") -> MacroPlanSchema:
    return MacroPlanSchema(
        routing_mode="standard",
        routing_reason="eval stub",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_eval",
                tool_name="sql_tool",
                reason="eval",
                focused_query=focused,
            )
        ],
    )


def evaluate_routing_case(case: dict[str, Any]) -> list[str]:
    """Return list of failure messages; empty means pass."""
    failures: list[str] = []
    user_input = case["input"]
    profile = case.get("profile")
    expect = case.get("expect") or {}

    lexicon_terms = case.get("lexicon_terms")
    lexicon = FitnessLexicon(lexicon_terms) if lexicon_terms else FitnessLexicon.bootstrap()

    intent = project_intent(user_input, semantic_profile=profile, lexicon=lexicon)

    if "routing_hint" in expect and intent.routing_hint != expect["routing_hint"]:
        failures.append(
            f"routing_hint expected {expect['routing_hint']!r}, got {intent.routing_hint!r}"
        )

    if "fitness_score_max" in expect and intent.fitness_score > expect["fitness_score_max"]:
        failures.append(
            f"fitness_score {intent.fitness_score} > max {expect['fitness_score_max']}"
        )

    if "fitness_score_min" in expect and intent.fitness_score < expect["fitness_score_min"]:
        failures.append(
            f"fitness_score {intent.fitness_score} < min {expect['fitness_score_min']}"
        )

    if expect.get("force_chat_only"):
        plan, actions = apply_chat_only_gate(_sql_only_plan(), intent)
        if plan.routing_mode != "chat_only":
            failures.append("expected chat_only gate to force chat_only")

    if "rag_intent_hint" in expect and intent.rag_intent_hint != expect["rag_intent_hint"]:
        failures.append(
            f"rag_intent_hint expected {expect['rag_intent_hint']!r}, "
            f"got {intent.rag_intent_hint!r}"
        )

    if "slot_contains" in expect and expect["slot_contains"] not in intent.slots:
        failures.append(f"expected slot {expect['slot_contains']!r} in {intent.slots}")

    if "lexicon_hits_contain" in expect:
        if expect["lexicon_hits_contain"] not in intent.lexicon_hits:
            failures.append(
                f"expected lexicon hit {expect['lexicon_hits_contain']!r} in {intent.lexicon_hits}"
            )

    if "lexicon_hits_exclude" in expect:
        if expect["lexicon_hits_exclude"] in intent.lexicon_hits:
            failures.append(
                f"did not expect lexicon hit {expect['lexicon_hits_exclude']!r}"
            )

    if expect.get("requires_graph"):
        triggered = injured_joints_triggered(user_input, profile)
        if "triggered_joints" in expect:
            for joint in expect["triggered_joints"]:
                if joint not in triggered:
                    failures.append(f"expected triggered joint {joint!r}, got {triggered}")

        patched, actions = validate_and_patch_macro_plan(
            user_input, _sql_only_plan(user_input[:20]), profile, intent
        )
        if not any(t.tool_name == "graph_tool" for t in patched.selected_tools):
            failures.append("expected graph_tool injection")

        if "policy_action_contains" in expect:
            needle = expect["policy_action_contains"]
            if not any(needle in a for a in actions):
                failures.append(f"expected policy action containing {needle!r}")

    return failures


def load_routing_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("routing dataset must be a JSON array")
    return data


def run_routing_eval(dataset_path: Path) -> tuple[int, int, list[str]]:
    cases = load_routing_dataset(dataset_path)
    passed = 0
    reports: list[str] = []
    for case in cases:
        case_id = case.get("id", "?")
        failures = evaluate_routing_case(case)
        if failures:
            reports.append(f"{case_id}: " + "; ".join(failures))
        else:
            passed += 1
    return passed, len(cases), reports
