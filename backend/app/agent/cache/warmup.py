from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.agent.cache.intent_resources import prefetch_intent_resources
from app.agent.utils.logger import logger

if TYPE_CHECKING:
    from app.tools.graph_tool import GraphTool
    from app.tools.sql_tool import SQLTool


async def warmup_intent_resources(
    sql_tool: SQLTool | None,
    graph_tool: GraphTool | None,
) -> None:
    """Preload lexicon + joint terms so the first chat skips cold Neo4j/SQL."""
    started = time.perf_counter()
    lexicon, terms = await prefetch_intent_resources(sql_tool, graph_tool)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        f"[Warmup] intent resources ready in {elapsed_ms}ms "
        f"(lexicon_terms={lexicon.term_count}, joints={len(terms)})"
    )
