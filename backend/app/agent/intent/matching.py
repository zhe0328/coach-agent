"""Deterministic text matching helpers for intent routing."""

from __future__ import annotations

import re
import string

from app.agent.policy.routing_keywords import ACTION_KEYWORDS, SAFETY_PHRASES

# Single-character body-part tokens allowed when surrounded by fitness context.
_SINGLE_CHAR_BODY_TERMS = frozenset({"胸", "背", "肩", "腿", "臀", "腹", "腰", "膝", "髋", "腕", "肘"})

_NOISE_PATTERN = re.compile(r"^[\s\d" + re.escape(string.punctuation) + "，。！？、；：""''（）【】]+$")


def contains_phrase(text: str, phrases: frozenset[str]) -> bool:
    lowered = text.lower()
    return any(p in text or p in lowered for p in phrases)


def has_safety_signal(text: str) -> bool:
    if contains_phrase(text, SAFETY_PHRASES):
        return True
    return "痛" in text or "伤" in text


def is_noise_input(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    if len(stripped) <= 1:
        return True
    if _NOISE_PATTERN.match(stripped):
        return True
    return False


def term_allowed_for_match(term: str) -> bool:
    if len(term) >= 2:
        return True
    if term in ACTION_KEYWORDS:
        return True
    return term in _SINGLE_CHAR_BODY_TERMS


def find_lexicon_matches(text: str, terms_longest_first: list[str]) -> list[str]:
    """Longest-match-first; skip overlapping shorter hits on same span."""
    if not text:
        return []

    matches: list[str] = []
    occupied: list[tuple[int, int]] = []

    for term in terms_longest_first:
        if not term or not term_allowed_for_match(term):
            continue
        start = 0
        while True:
            idx = text.find(term, start)
            if idx == -1:
                break
            end = idx + len(term)
            if not any(not (end <= lo or idx >= hi) for lo, hi in occupied):
                matches.append(term)
                occupied.append((idx, end))
            start = idx + 1

    return matches
