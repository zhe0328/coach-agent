from __future__ import annotations

import json

import pytest

from app.agent.cache import joint_terms_cache as cache_mod
from app.agent.cache.joint_terms_cache import (
    invalidate_joint_terms_cache,
    read_joint_terms_cache,
    write_joint_terms_cache,
)
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
    monkeypatch.setattr("app.config.settings.JOINT_TERMS_CACHE_TTL_SECONDS", 3600)
    return redis


@pytest.fixture(autouse=True)
def reset_caches():
    joint_mod.clear_joint_sensitive_terms_runtime()
    cache_mod._get_async_redis.cache_clear()
    yield
    joint_mod.clear_joint_sensitive_terms_runtime()
    cache_mod._get_async_redis.cache_clear()


@pytest.mark.asyncio
async def test_joint_terms_cache_round_trip(fake_redis):
    terms = {"腕关节": frozenset(["卧推", "俯卧撑"]), "膝关节": frozenset(["深蹲"])}

    await write_joint_terms_cache(terms)
    loaded = await read_joint_terms_cache()

    assert loaded == terms
    assert "global:joint_sensitive_terms" in fake_redis.store


@pytest.mark.asyncio
async def test_load_joint_terms_uses_redis_without_neo4j(fake_redis):
    payload = {"腕关节": ["划船"]}
    fake_redis.store["global:joint_sensitive_terms"] = json.dumps(payload)
    calls = 0

    class FakeGraph:
        async def fetch_joint_exercise_names(self):
            nonlocal calls
            calls += 1
            return {}

    result = await joint_mod.load_joint_sensitive_terms(FakeGraph())

    assert calls == 0
    assert "划船" in result["腕关节"]


@pytest.mark.asyncio
async def test_load_joint_terms_writes_redis_after_neo4j(fake_redis):
    class FakeGraph:
        async def fetch_joint_exercise_names(self):
            return {"腕关节": ["哑铃弯举"]}

    result = await joint_mod.load_joint_sensitive_terms(FakeGraph())

    assert "哑铃弯举" in result["腕关节"]
    cached = await read_joint_terms_cache()
    assert cached is not None
    assert "哑铃弯举" in cached["腕关节"]


@pytest.mark.asyncio
async def test_invalidate_joint_terms_cache(fake_redis):
    await write_joint_terms_cache({"腕关节": frozenset(["a"])})

    await invalidate_joint_terms_cache()

    assert await read_joint_terms_cache() is None
