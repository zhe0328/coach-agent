"""Merge static joint terms with Neo4j exercise names that LOAD each joint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.policy.joint_sensitive_terms import JOINT_SENSITIVE_TERMS
from app.agent.utils.logger import logger

if TYPE_CHECKING:
    from app.tools.graph_tool import GraphTool

_runtime_terms: dict[str, frozenset[str]] | None = None


def get_joint_sensitive_terms() -> dict[str, frozenset[str]]:
    return _runtime_terms or JOINT_SENSITIVE_TERMS


def set_joint_sensitive_terms(terms: dict[str, frozenset[str]]) -> None:
    global _runtime_terms
    _runtime_terms = terms


async def load_joint_sensitive_terms(
    graph_tool: GraphTool | None = None,
) -> dict[str, frozenset[str]]:
    merged: dict[str, frozenset[str]] = {
        joint: frozenset(terms) for joint, terms in JOINT_SENSITIVE_TERMS.items()
    }
    if graph_tool is None:
        return merged

    try:
        graph_map = await graph_tool.fetch_joint_exercise_names()
        for joint, static in merged.items():
            extras = graph_map.get(joint, [])
            if extras:
                merged[joint] = frozenset(set(static) | set(extras))
        enriched = sum(
            1
            for j, t in merged.items()
            if len(t) > len(JOINT_SENSITIVE_TERMS.get(j, frozenset()))
        )
        logger.info(f"[JointTerms] Loaded Neo4j enrichment for {enriched} joints")
    except Exception as exc:
        logger.warning(f"[JointTerms] Neo4j enrichment skipped: {exc}")

    set_joint_sensitive_terms(merged)
    return merged
