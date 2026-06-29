from __future__ import annotations

import json

import pytest

from app.agent.cache import semantic_profile_cache as cache_mod
from app.agent.cache.semantic_profile_cache import (
    fetch_semantic_profile_cached,
    invalidate_semantic_profile,
)
from app.agent.cache.intent_resources import prefetch_intent_resources
from app.agent.intent import fitness_lexicon as lexicon_mod
from app.agent.policy import joint_term_loader as joint_mod


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttl[key] = ttl

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttl.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(cache_mod, "_get_async_redis", lambda: redis)
    monkeypatch.setattr(
        "app.config.settings.SEMANTIC_PROFILE_CACHE_TTL_SECONDS", 600
    )
    return redis


@pytest.fixture(autouse=True)
def reset_process_caches():
    lexicon_mod._cached_lexicon = None
    joint_mod._runtime_terms = None
    joint_mod.clear_joint_sensitive_terms_runtime()
    cache_mod._get_async_redis.cache_clear()
    yield
    lexicon_mod._cached_lexicon = None
    joint_mod.clear_joint_sensitive_terms_runtime()
    cache_mod._get_async_redis.cache_clear()


@pytest.mark.asyncio
async def test_semantic_profile_cache_miss_then_hit(fake_redis):
    calls: list[int] = []

    async def fetch_fn(user_id: int):
        calls.append(user_id)
        return [{"injuries": ["膝关节"], "equipment_list": ["哑铃"]}]

    first = await fetch_semantic_profile_cached(42, fetch_fn)
    second = await fetch_semantic_profile_cached(42, fetch_fn)

    assert first == second
    assert calls == [42]
    assert "user:42:semantic_profile" in fake_redis.store


@pytest.mark.asyncio
async def test_semantic_profile_cache_neo4j_failure_returns_empty(fake_redis):
    async def fetch_fn(_user_id: int):
        raise RuntimeError("neo4j down")

    profile = await fetch_semantic_profile_cached(7, fetch_fn)

    assert profile == []
    assert json.loads(fake_redis.store["user:7:semantic_profile"]) == []


@pytest.mark.asyncio
async def test_invalidate_semantic_profile(fake_redis):
    fake_redis.store["user:9:semantic_profile"] = "[]"

    await invalidate_semantic_profile(9)

    assert "user:9:semantic_profile" not in fake_redis.store


@pytest.mark.asyncio
async def test_prefetch_intent_resources_returns_lexicon_and_terms(monkeypatch):
    async def fake_lexicon(_sql_tool):
        return lexicon_mod.FitnessLexicon.bootstrap()

    async def fake_joint(_graph_tool):
        return {"knee": frozenset(["squat"])}

    monkeypatch.setattr(
        "app.agent.cache.intent_resources.get_fitness_lexicon", fake_lexicon
    )
    monkeypatch.setattr(
        "app.agent.cache.intent_resources.load_joint_sensitive_terms", fake_joint
    )

    lexicon, terms = await prefetch_intent_resources(None, None)

    assert lexicon.term_count > 0
    assert "knee" in terms


@pytest.mark.asyncio
async def test_get_fitness_lexicon_singleton():
    first = await lexicon_mod.get_fitness_lexicon(None)
    second = await lexicon_mod.get_fitness_lexicon(None)

    assert first is second
