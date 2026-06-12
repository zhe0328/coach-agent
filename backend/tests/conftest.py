"""Pytest bootstrap — allow eval unit tests to import app modules without a local .env."""

from __future__ import annotations

import os

_CI_DEFAULTS = {
    "DB_PASSWORD": "ci-test",
    "OPENAI_API_KEY": "ci-test",
    "DEEPSEEK_API_KEY": "ci-test",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "ci-test",
    "LLM_MODEL_NAME": "gpt-4o-mini",
    "DASHSCOPE_API_KEY": "ci-test",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "AUTH_SECRET_KEY": "ci-test-secret",
}

for key, value in _CI_DEFAULTS.items():
    os.environ.setdefault(key, value)
