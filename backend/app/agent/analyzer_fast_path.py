"""Deterministic analyzer fast-path — skip LLM when tool data is clearly sufficient."""

from __future__ import annotations

import re
from typing import Any

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_ACTION_LIMIT_RE = re.compile(
    r"(?:推荐\s*)?(?:([一二两三四五六七八九十\d]+))\s*个"
)


def _parse_count_token(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


def extract_requested_action_count(user_input: str) -> int | None:
    text = (user_input or "").strip()
    if not text:
        return None

    digit_match = re.search(r"(\d+)\s*个", text)
    if digit_match:
        return int(digit_match.group(1))

    for cn, val in _CN_NUM.items():
        if re.search(rf"{cn}\s*个", text):
            return val

    recommend_match = re.search(r"推荐\s*([一二两三四五六七八九十\d]+)\s*个?", text)
    if recommend_match:
        return _parse_count_token(recommend_match.group(1))

    return None


def extract_clause_action_counts(user_input: str) -> list[int]:
    """Per-clause「N个」counts in order, e.g. 3个练背+3个练臀 → [3, 3]."""
    tokens = _ACTION_LIMIT_RE.findall((user_input or "").strip())
    counts: list[int] = []
    for token in tokens:
        parsed = _parse_count_token(token)
        if parsed is None:
            return []
        counts.append(parsed)
    return counts


def sum_requested_action_counts(user_input: str) -> int | None:
    """Sum all「N个」clauses, e.g. 3个练背 + 3个练臀 → 6."""
    clause_counts = extract_clause_action_counts(user_input)
    if clause_counts:
        return sum(clause_counts)
    return extract_requested_action_count(user_input)


def _get_type(result: dict[str, Any]) -> str:
    return result.get("tool_name") or result.get("type", "")


def sql_result_lengths(tool_results: list[dict[str, Any]]) -> list[int]:
    lengths: list[int] = []
    for result in tool_results:
        if _get_type(result) != "sql":
            continue
        data = result.get("data")
        lengths.append(len(data) if isinstance(data, list) else 0)
    return lengths


def count_sql_results(tool_results: list[dict[str, Any]]) -> int:
    return sum(sql_result_lengths(tool_results))


def sql_tasks_meet_counts(
    user_input: str,
    tool_results: list[dict[str, Any]],
) -> bool | None:
    """
    Per SQL task vs per-clause counts.
    True / False when check applies; None → ambiguous, defer to LLM or total sum.
    """
    clause_counts = extract_clause_action_counts(user_input)
    if not clause_counts:
        return None

    sql_lens = sql_result_lengths(tool_results)
    if not sql_lens:
        return False

    if len(sql_lens) == len(clause_counts):
        return all(actual >= need for actual, need in zip(sql_lens, clause_counts))

    if len(sql_lens) == 1:
        return sql_lens[0] >= sum(clause_counts)

    if len(sql_lens) > len(clause_counts):
        return all(
            sql_lens[i] >= clause_counts[i] for i in range(len(clause_counts))
        )

    # More clauses than SQL tasks — cannot verify per task.
    return None


def _row_is_injury_shape(row: dict[str, Any]) -> bool:
    return bool(
        row.get("unsafe_exercise_id")
        or row.get("unsafe_name")
        or "safe_replacements" in row
    )


def _row_is_exercise_shape(row: dict[str, Any]) -> bool:
    return bool(row.get("id") or row.get("name_zh"))


def graph_result_is_valid(result: dict[str, Any]) -> bool:
    """Validate graph payload shape matches the declared scenario."""
    scenario = result.get("scenario") or ""
    data = result.get("data")
    if not isinstance(data, list):
        return False

    if scenario == "injury_avoidance":
        if not data:
            return True
        return any(isinstance(row, dict) and _row_is_injury_shape(row) for row in data)

    if scenario in ("regression", "progression", "synergy", "strengthen_joint"):
        if not data:
            return False
        for row in data:
            if not isinstance(row, dict):
                continue
            if _row_is_injury_shape(row) and not _row_is_exercise_shape(row):
                return False
        return any(isinstance(row, dict) and _row_is_exercise_shape(row) for row in data)

    return len(data) > 0


def graph_results_valid(tool_results: list[dict[str, Any]]) -> bool:
    graph_results = [r for r in tool_results if _get_type(r) == "graph"]
    if not graph_results:
        return True
    return all(graph_result_is_valid(r) for r in graph_results)


def rag_has_data(tool_results: list[dict[str, Any]]) -> bool:
    for result in tool_results:
        if _get_type(result) != "rag":
            continue
        data = result.get("data")
        if isinstance(data, list) and len(data) > 0:
            return True
    return False


def try_analyzer_fast_path(
    user_input: str,
    tool_results: list[dict[str, Any]],
    *,
    flags: dict[str, bool],
    is_action_query: bool,
    has_safety_concern: bool,
) -> tuple[bool, str] | None:
    """
    Return (True, reason) when LLM analyzer can be skipped.
    Return None to fall through to LLM review.
    """
    if flags.get("rag") and not flags.get("sql"):
        if rag_has_data(tool_results):
            return True, "fast_path:rag_only_with_data"
        return None

    if not flags.get("sql_data"):
        return None

    sql_count = count_sql_results(tool_results)
    if sql_count <= 0:
        return None

    per_task = sql_tasks_meet_counts(user_input, tool_results)
    if per_task is False:
        return None

    requested = sum_requested_action_counts(user_input)
    if per_task is None:
        if requested is not None and sql_count < requested:
            return None

    if is_action_query and requested is None and sql_count < 1:
        return None

    if flags.get("graph"):
        if not graph_results_valid(tool_results):
            return None

    if has_safety_concern and not flags.get("graph"):
        return None

    if flags.get("rag") and not rag_has_data(tool_results):
        return None

    clause_counts = extract_clause_action_counts(user_input)
    if per_task is True and clause_counts:
        sql_lens = sql_result_lengths(tool_results)
        return True, f"fast_path:per_task sql={sql_lens}>={clause_counts}"

    if requested is not None:
        return True, f"fast_path:sql_count={sql_count}>=requested={requested}"
    return True, f"fast_path:sql_count={sql_count}"
