"""Tests for signup/profile Neo4j semantic init enqueueing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.queue import jobs
from app.queue.enqueue import enqueue_user_semantic_init


@dataclass
class CapturedEnqueue:
    queue_name: str
    func: Any
    job_id: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@pytest.fixture
def captured_enqueues(monkeypatch):
    captured: list[CapturedEnqueue] = []

    def fake_enqueue(
        queue_name,
        func,
        *,
        job_id,
        args=(),
        kwargs=None,
        retry=None,
    ):
        captured.append(
            CapturedEnqueue(
                queue_name=queue_name,
                func=func,
                job_id=job_id,
                args=args,
                kwargs=kwargs or {},
            )
        )
        return job_id

    monkeypatch.setattr("app.queue.enqueue._enqueue", fake_enqueue)
    monkeypatch.setattr("app.config.settings.QUEUE_ENABLED", True)
    return captured


class TestEnqueueUserSemanticInit:
    def test_enqueues_neo4j_init_on_medium_queue(self, captured_enqueues):
        enqueue_user_semantic_init(
            user_id=42,
            name="alice",
            level="beginner",
            injuries=["膝关节"],
            equipments=["哑铃"],
        )

        assert len(captured_enqueues) == 1
        job = captured_enqueues[0]
        assert job.func == jobs.init_user_semantic_memory
        assert job.queue_name == "coach_medium"
        assert job.kwargs["user_id"] == 42
        assert job.kwargs["injuries"] == ["膝关节"]
        assert job.job_id.startswith("42__semantic_init__")

    def test_same_profile_is_idempotent(self, captured_enqueues):
        kwargs = dict(
            user_id=7,
            name="bob",
            level="intermediate",
            injuries=[],
            equipments=["自重"],
        )
        enqueue_user_semantic_init(**kwargs)
        enqueue_user_semantic_init(**kwargs)

        assert len(captured_enqueues) == 2
        assert captured_enqueues[0].job_id == captured_enqueues[1].job_id

    def test_different_profile_gets_distinct_job_id(self, captured_enqueues):
        enqueue_user_semantic_init(
            user_id=7,
            name="bob",
            level="intermediate",
            injuries=[],
            equipments=["自重"],
        )
        enqueue_user_semantic_init(
            user_id=7,
            name="bob",
            level="advanced",
            injuries=[],
            equipments=["自重"],
        )

        assert captured_enqueues[0].job_id != captured_enqueues[1].job_id
