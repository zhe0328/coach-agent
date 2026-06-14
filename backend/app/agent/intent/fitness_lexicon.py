from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from app.agent.intent.matching import find_lexicon_matches
from app.agent.policy.routing_keywords import ACTION_KEYWORDS, FITNESS_ENTITY_KEYWORDS

if TYPE_CHECKING:
    from app.tools.sql_tool import SQLTool


class FitnessLexicon:
    """DB-backed fitness entity dictionary with bootstrap fallback."""

    def __init__(self, terms: list[str]):
        cleaned = {t.strip() for t in terms if t and t.strip()}
        self._terms = sorted(cleaned, key=len, reverse=True)

    @classmethod
    def bootstrap(cls) -> FitnessLexicon:
        terms = list(FITNESS_ENTITY_KEYWORDS) + list(ACTION_KEYWORDS)
        return cls(terms)

    @classmethod
    async def load(cls, sql_tool: Optional["SQLTool"] = None) -> FitnessLexicon:
        if sql_tool is None:
            return cls.bootstrap()
        try:
            terms = await sql_tool.fetch_fitness_lexicon_terms()
            if terms:
                merged = list(set(terms) | set(FITNESS_ENTITY_KEYWORDS) | set(ACTION_KEYWORDS))
                return cls(merged)
        except Exception:
            pass
        return cls.bootstrap()

    def find_matches(self, text: str) -> list[str]:
        return find_lexicon_matches(text, self._terms)

    def has_fitness_signal(self, text: str) -> bool:
        return bool(self.find_matches(text))

    def score_hits(self, text: str) -> int:
        matches = self.find_matches(text)
        score = 0
        for term in matches:
            score += 2 if len(term) >= 3 else 1
        return score

    @property
    def term_count(self) -> int:
        return len(self._terms)
