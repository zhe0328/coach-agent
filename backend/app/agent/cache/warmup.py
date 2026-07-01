from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from app.agent.cache.intent_resources import prefetch_intent_resources
from app.agent.cache.semantic_profile_cache import fetch_semantic_profile_cached
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


async def warmup_user_context(
    user_id: int,
    graph_tool: GraphTool,
    sql_tool: SQLTool | None = None,
) -> None:
    """Preload per-user semantic profile (Redis) and global intent resources."""
    started = time.perf_counter()
    profile_task = fetch_semantic_profile_cached(
        user_id, graph_tool.fetch_user_semantic_memory
    )
    if sql_tool is not None:
        profile, _ = await asyncio.gather(
            profile_task,
            prefetch_intent_resources(sql_tool, graph_tool),
        )
    else:
        profile = await profile_task

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    injuries = profile[0].get("injuries") if profile else []
    equipment = profile[0].get("equipment_list") if profile else []
    logger.info(
        f"[Warmup] user context ready in {elapsed_ms}ms "
        f"user_id={user_id} injuries={injuries} equipment={equipment}"
    )
