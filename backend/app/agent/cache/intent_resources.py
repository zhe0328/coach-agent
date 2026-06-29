from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.agent.intent.fitness_lexicon import FitnessLexicon, get_fitness_lexicon
from app.agent.policy.joint_term_loader import load_joint_sensitive_terms

if TYPE_CHECKING:
    from app.tools.graph_tool import GraphTool
    from app.tools.sql_tool import SQLTool


async def prefetch_intent_resources(
    sql_tool: SQLTool | None,
    graph_tool: GraphTool | None,
) -> tuple[FitnessLexicon, dict[str, frozenset[str]]]:
    """Load lexicon and joint-sensitive terms in parallel (process-level cache)."""
    lexicon, terms = await asyncio.gather(
        get_fitness_lexicon(sql_tool),
        load_joint_sensitive_terms(graph_tool),
    )
    return lexicon, terms
