"""RQ worker entrypoints — must be importable sync callables."""

from __future__ import annotations

import asyncio
from typing import Any

from openai import OpenAI

from app.agent.memory.memory_consolidator import MemoryConsolidator
from app.agent.memory.session_summarizer import merge_session_summary, summarize_pruned_turns
from app.agent.utils.logger import logger
from app.config import settings
from app.models.fitness import AgentPlansLog, ChatRecord, TrainingLog
from app.models.memory import ChatMessage, InjurySnifferSchema, WorkingMemory
from app.tools.graph_tool import GraphTool
from app.tools.sql_tool import SQLTool

_services: dict[str, Any] | None = None


def _get_services() -> dict[str, Any]:
    global _services
    if _services is None:
        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        sql_tool = SQLTool()
        graph_tool = GraphTool()
        _services = {
            "client": client,
            "sql_tool": sql_tool,
            "graph_tool": graph_tool,
            "consolidator": MemoryConsolidator(graph_tool, sql_tool, client),
        }
    return _services


def _parse_model(model_cls, payload: dict[str, Any]):
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


def log_chat_transaction(
    user_record: dict[str, Any],
    coach_record: dict[str, Any],
) -> None:
    sql_tool = _get_services()["sql_tool"]
    sql_tool._sync_log_chat_transaction(
        _parse_model(ChatRecord, user_record),
        _parse_model(ChatRecord, coach_record),
    )


def save_training_log(training_log: dict[str, Any]) -> None:
    sql_tool = _get_services()["sql_tool"]
    sql_tool._sync_save_training_log(_parse_model(TrainingLog, training_log))


def agent_plans_log(agent_plans_log_payload: dict[str, Any]) -> None:
    sql_tool = _get_services()["sql_tool"]
    sql_tool._sync_log_agent_plan_decision(
        _parse_model(AgentPlansLog, agent_plans_log_payload)
    )


def consolidate_to_graph(
    user_id: int,
    user_query: str,
    semantic_profile: list[dict[str, Any]] | None,
    sniff: dict[str, Any] | None,
) -> None:
    consolidator = _get_services()["consolidator"]
    parsed_sniff = _parse_model(InjurySnifferSchema, sniff) if sniff else None
    asyncio.run(
        consolidator.consolidate_session_to_graph(
            user_id=user_id,
            user_query=user_query,
            semantic_profile=semantic_profile,
            sniff=parsed_sniff,
        )
    )


def memory_summarize(
    session_id: str,
    pruned_messages: list[dict[str, Any]],
    turn_range: str,
) -> None:
    if not pruned_messages:
        return

    from redis import Redis

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    redis_key = f"working_memory:{session_id}"
    raw_json = redis.get(redis_key)
    if not raw_json:
        logger.warning(
            f"[Queue] memory_summarize skipped — no Redis key for session {session_id}"
        )
        return

    if hasattr(WorkingMemory, "model_validate_json"):
        memory = WorkingMemory.model_validate_json(raw_json)
    else:
        memory = WorkingMemory.parse_raw(raw_json)

    messages = [_parse_model(ChatMessage, msg) for msg in pruned_messages]
    client = _get_services()["client"]
    chunk = asyncio.run(summarize_pruned_turns(messages, client=client))
    if not chunk:
        return

    memory.session_summary = merge_session_summary(memory.session_summary, chunk)
    payload = (
        memory.model_dump_json()
        if hasattr(memory, "model_dump_json")
        else memory.json()
    )
    ttl = redis.ttl(redis_key)
    if ttl and ttl > 0:
        redis.set(redis_key, payload, ex=ttl)
    else:
        redis.set(redis_key, payload)

    logger.info(
        f"[Queue] memory_summarize merged warm summary for {session_id} "
        f"(turn_range={turn_range}, chunk={len(chunk)} chars)"
    )
