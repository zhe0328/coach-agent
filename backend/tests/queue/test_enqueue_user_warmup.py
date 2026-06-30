"""Tests for login warmup enqueueing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.queue import jobs
from app.queue.enqueue import enqueue_user_context_warmup


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
    monkeypatch.setattr("app.queue.enqueue.settings.QUEUE_ENABLED", True)
    monkeypatch.setattr("app.queue.enqueue.settings.LOGIN_WARMUP_ENABLED", True)
    return captured


def test_enqueue_user_context_warmup(captured_enqueues):
    job_id = enqueue_user_context_warmup(42)

    assert job_id == "42__warmup_context"
    assert len(captured_enqueues) == 1
    entry = captured_enqueues[0]
    assert entry.func is jobs.warmup_user_context_cache
    assert entry.kwargs == {"user_id": 42}


def test_enqueue_user_context_warmup_respects_disabled_flag(monkeypatch, captured_enqueues):
    monkeypatch.setattr("app.queue.enqueue.settings.LOGIN_WARMUP_ENABLED", False)

    assert enqueue_user_context_warmup(42) is None
    assert captured_enqueues == []
