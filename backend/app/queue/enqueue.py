from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from rq import Retry

from app.agent.utils.logger import logger
from app.config import settings
from app.models.fitness import AgentPlansLog, ChatRecord, TrainingLog
from app.models.memory import ChatMessage, InjurySnifferSchema
from app.queue import jobs
from app.queue.queues import QUEUE_HIGH, QUEUE_LOW, QUEUE_MEDIUM, get_queue


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _enqueue(
    queue_name: str,
    func,
    *,
    job_id: str,
    args: tuple = (),
    kwargs: dict | None = None,
    retry: Retry | None = None,
) -> str | None:
    if not settings.QUEUE_ENABLED:
        logger.warning(f"[Queue] disabled — skipping job {job_id}")
        return None

    queue = get_queue(queue_name)
    try:
        job = queue.enqueue(
            func,
            args=args,
            kwargs=kwargs or {},
            job_id=job_id,
            retry=retry,
            failure_ttl=86400,
            result_ttl=300,
        )
        return job.id
    except Exception as exc:
        if "DuplicateJobId" in type(exc).__name__ or "already exists" in str(exc).lower():
            logger.info(f"[Queue] idempotent skip — job already queued: {job_id}")
            return job_id
        logger.error(f"[Queue] failed to enqueue {job_id}: {exc}")
        raise


def _semantic_profile_job_id(
    user_id: int,
    name: str,
    level: str,
    injuries: list[str],
    equipments: list[str],
) -> str:
    fingerprint = json.dumps(
        {
            "name": name,
            "level": level,
            "injuries": sorted(injuries),
            "equipments": sorted(equipments),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    return f"{user_id}__semantic_init__{digest}"


@dataclass(frozen=True)
class AfterTurnPayload:
    session_id: str
    turn_id: int
    user_id: int
    user_record: ChatRecord
    coach_record: ChatRecord
    training_log: TrainingLog
    run_consolidation: bool
    user_query: str
    semantic_profile: list[dict[str, Any]] | None
    sniff: InjurySnifferSchema | None
    agent_plans_log: AgentPlansLog | None
    pruned_messages: list[ChatMessage] | None = None
    turn_range: str | None = None


def enqueue_after_turn(payload: AfterTurnPayload) -> list[str]:
    """Enqueue all post-persist background jobs. Returns enqueued job ids."""
    sid = payload.session_id
    turn = payload.turn_id
    enqueued: list[str] = []

    job_id = _enqueue(
        QUEUE_HIGH,
        jobs.log_chat_transaction,
        job_id=f"{sid}__{turn}__log_chat",
        args=(_model_dump(payload.user_record), _model_dump(payload.coach_record)),
        retry=Retry(max=3, interval=[10, 30, 60]),
    )
    if job_id:
        enqueued.append(job_id)

    job_id = _enqueue(
        QUEUE_MEDIUM,
        jobs.save_training_log,
        job_id=f"{sid}__{turn}__training_log",
        args=(_model_dump(payload.training_log),),
        retry=Retry(max=3, interval=[15, 45, 90]),
    )
    if job_id:
        enqueued.append(job_id)

    if payload.run_consolidation:
        sniff_payload = _model_dump(payload.sniff) if payload.sniff else None
        job_id = _enqueue(
            QUEUE_LOW,
            jobs.consolidate_to_graph,
            job_id=f"{payload.user_id}__{sid}__{turn}__consolidate",
            kwargs={
                "user_id": payload.user_id,
                "user_query": payload.user_query,
                "semantic_profile": payload.semantic_profile,
                "sniff": sniff_payload,
            },
            retry=Retry(max=2, interval=[30, 120]),
        )
        if job_id:
            enqueued.append(job_id)

    if payload.pruned_messages:
        turn_range = payload.turn_range or f"turn_{turn}"
        pruned_payload = [_model_dump(msg) for msg in payload.pruned_messages]
        job_id = _enqueue(
            QUEUE_LOW,
            jobs.memory_summarize,
            job_id=f"{sid}__{turn_range}__memory_summarize",
            kwargs={
                "session_id": sid,
                "pruned_messages": pruned_payload,
                "turn_range": turn_range,
            },
            retry=Retry(max=2, interval=[20, 60]),
        )
        if job_id:
            enqueued.append(job_id)

    if payload.agent_plans_log:
        retry_count = payload.agent_plans_log.loop_retry_count
        job_id = _enqueue(
            QUEUE_LOW,
            jobs.agent_plans_log,
            job_id=f"{sid}__{turn}__retry_{retry_count}__plan_log",
            args=(_model_dump(payload.agent_plans_log),),
            retry=Retry(max=2, interval=[15, 45]),
        )
        if job_id:
            enqueued.append(job_id)

    logger.info(
        f"[Queue] enqueue_after_turn session={sid} turn={turn} "
        f"jobs={len(enqueued)} consolidate={payload.run_consolidation}"
    )
    return enqueued


def enqueue_sniff_after_turn(
    *,
    user_id: int,
    session_id: str,
    turn_id: int,
    user_query: str,
    semantic_profile: list[dict[str, Any]] | None,
) -> str | None:
    """Run sniff_delta off the request hot path; may trigger consolidation."""
    return _enqueue(
        QUEUE_MEDIUM,
        jobs.sniff_profile_and_maybe_consolidate,
        job_id=f"{user_id}__{session_id}__{turn_id}__sniff_profile",
        kwargs={
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_query": user_query,
            "semantic_profile": semantic_profile,
        },
        retry=Retry(max=2, interval=[20, 60]),
    )


def enqueue_agent_plans_log(
    agent_plans_log: AgentPlansLog,
    *,
    turn_id: int,
) -> str | None:
    sid = agent_plans_log.session_id
    retry_count = agent_plans_log.loop_retry_count
    return _enqueue(
        QUEUE_LOW,
        jobs.agent_plans_log,
        job_id=f"{sid}__{turn_id}__retry_{retry_count}__plan_log",
        args=(_model_dump(agent_plans_log),),
        retry=Retry(max=2, interval=[15, 45]),
    )


def enqueue_consolidation(
    *,
    user_id: int,
    session_id: str,
    user_query: str,
    semantic_profile: list[dict[str, Any]] | None,
    sniff: InjurySnifferSchema | None,
    turn_id: int | None = None,
) -> str | None:
    turn_key = turn_id if turn_id is not None else "close"
    sniff_payload = _model_dump(sniff) if sniff else None
    return _enqueue(
        QUEUE_LOW,
        jobs.consolidate_to_graph,
        job_id=f"{user_id}__{session_id}__{turn_key}__consolidate",
        kwargs={
            "user_id": user_id,
            "user_query": user_query,
            "semantic_profile": semantic_profile,
            "sniff": sniff_payload,
        },
        retry=Retry(max=2, interval=[30, 120]),
    )


def enqueue_user_semantic_init(
    *,
    user_id: int,
    name: str,
    level: str,
    injuries: list[str],
    equipments: list[str],
) -> str | None:
    """Enqueue Neo4j semantic profile initialization after signup or profile update."""
    job_id = _semantic_profile_job_id(user_id, name, level, injuries, equipments)
    return _enqueue(
        QUEUE_MEDIUM,
        jobs.init_user_semantic_memory,
        job_id=job_id,
        kwargs={
            "user_id": user_id,
            "name": name,
            "level": level,
            "injuries": injuries,
            "equipments": equipments,
        },
        retry=Retry(max=3, interval=[15, 45, 90]),
    )


def enqueue_user_context_warmup(user_id: int) -> str | None:
    """Enqueue per-user semantic profile cache warmup (login / explicit refresh)."""
    if not settings.LOGIN_WARMUP_ENABLED:
        return None
    return _enqueue(
        QUEUE_MEDIUM,
        jobs.warmup_user_context_cache,
        job_id=f"{user_id}__warmup_context",
        kwargs={"user_id": user_id},
        retry=Retry(max=2, interval=[5, 15]),
    )
