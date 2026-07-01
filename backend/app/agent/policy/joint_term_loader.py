"""Merge static joint terms with Neo4j exercise names that LOAD each joint."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.agent.cache.joint_terms_cache import (
    read_joint_terms_cache,
    write_joint_terms_cache,
)
from app.agent.policy.joint_sensitive_terms import JOINT_SENSITIVE_TERMS
from app.agent.utils.logger import logger

if TYPE_CHECKING:
    from app.tools.graph_tool import GraphTool

_runtime_terms: dict[str, frozenset[str]] | None = None
_load_lock = asyncio.Lock()


def get_joint_sensitive_terms() -> dict[str, frozenset[str]]:
    return _runtime_terms or JOINT_SENSITIVE_TERMS


def set_joint_sensitive_terms(terms: dict[str, frozenset[str]]) -> None:
    global _runtime_terms
    _runtime_terms = terms


def clear_joint_sensitive_terms_runtime() -> None:
    """Test helper — drop process-level cache."""
    global _runtime_terms
    _runtime_terms = None


async def _load_joint_terms_from_neo4j(
    graph_tool: GraphTool,
) -> dict[str, frozenset[str]]:
    merged: dict[str, frozenset[str]] = {
        joint: frozenset(terms) for joint, terms in JOINT_SENSITIVE_TERMS.items()
    }
    graph_map = await graph_tool.fetch_joint_exercise_names()
    for joint, static in merged.items():
        extras = graph_map.get(joint, [])
        if extras:
            merged[joint] = frozenset(set(static) | set(extras))
    enriched = sum(
        1
        for joint, terms in merged.items()
        if len(terms) > len(JOINT_SENSITIVE_TERMS.get(joint, frozenset()))
    )
    logger.info(f"[JointTerms] Loaded Neo4j enrichment for {enriched} joints")
    return merged


async def load_joint_sensitive_terms(
    graph_tool: GraphTool | None = None,
) -> dict[str, frozenset[str]]:
    if _runtime_terms is not None:
        return _runtime_terms

    async with _load_lock:
        if _runtime_terms is not None:
            return _runtime_terms

        cached = await read_joint_terms_cache()
        if cached is not None:
            set_joint_sensitive_terms(cached)
            return cached

        merged: dict[str, frozenset[str]] = {
            joint: frozenset(terms) for joint, terms in JOINT_SENSITIVE_TERMS.items()
        }
        if graph_tool is not None:
            try:
                merged = await _load_joint_terms_from_neo4j(graph_tool)
            except Exception as exc:
                logger.warning(f"[JointTerms] Neo4j enrichment skipped: {exc}")

        set_joint_sensitive_terms(merged)
        await write_joint_terms_cache(merged)
        return merged
