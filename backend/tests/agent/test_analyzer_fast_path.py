"""Tests for deterministic analyzer fast-path."""

from __future__ import annotations

from app.agent.analyzer_fast_path import (
    extract_clause_action_counts,
    extract_requested_action_count,
    graph_result_is_valid,
    sum_requested_action_counts,
    try_analyzer_fast_path,
)


def test_extract_requested_action_count_chinese():
    assert extract_requested_action_count("推荐三个练腿动作") == 3
    assert extract_requested_action_count("来 5 个计划") == 5


def test_sum_requested_action_counts_multi_clause():
    assert sum_requested_action_counts("3个高阶练背动作+3个练屁股动作") == 6
    assert sum_requested_action_counts("推荐两个练上肢，三个练腹肌") == 5
    assert extract_clause_action_counts("3个练背+3个练臀") == [3, 3]


def test_fast_path_multi_clause_sql_per_task():
    tool_results = [
        {"type": "sql", "data": [{"id": str(i)} for i in range(21)]},
        {"type": "sql", "data": [{"id": str(i)} for i in range(30)]},
        {
            "type": "graph",
            "scenario": "injury_avoidance",
            "data": [
                {
                    "unsafe_exercise_id": "e1",
                    "unsafe_name": "卧推",
                    "safe_replacements": [{"id": "e2", "name_zh": "跪姿俯卧撑"}],
                }
            ],
        },
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": True}
    result = try_analyzer_fast_path(
        "3个高阶练背动作+3个练屁股动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result is not None
    assert result[0] is True
    assert "per_task" in result[1]


def test_fast_path_rejects_uneven_sql_per_task():
    tool_results = [
        {"type": "sql", "data": [{"id": "1"} for _ in range(21)]},
        {"type": "sql", "data": []},
        {
            "type": "graph",
            "scenario": "injury_avoidance",
            "data": [{"unsafe_exercise_id": "e1", "safe_replacements": []}],
        },
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": True}
    result = try_analyzer_fast_path(
        "3个高阶练背动作+3个练屁股动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result is None


def test_graph_result_rejects_injury_shape_for_regression():
    injury_row = {
        "unsafe_exercise_id": "e1",
        "unsafe_name": "俯卧撑",
        "safe_replacements": [{"id": "e2", "name_zh": "跪姿俯卧撑"}],
    }
    assert graph_result_is_valid(
        {"scenario": "regression", "data": [injury_row]}
    ) is False
    assert graph_result_is_valid(
        {"scenario": "progression", "data": [{"id": "e3", "name_zh": "钻石俯卧撑"}]}
    ) is True


def test_fast_path_rejects_wrong_graph_shape_for_progression():
    tool_results = [
        {"type": "sql", "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        {
            "type": "graph",
            "scenario": "progression",
            "data": [
                {
                    "unsafe_exercise_id": "e1",
                    "unsafe_name": "俯卧撑",
                    "safe_replacements": [],
                }
            ],
        },
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": True}
    result = try_analyzer_fast_path(
        "俯卧撑太难了，推荐更简单的",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=True,
    )
    assert result is None


def test_fast_path_sql_with_requested_count():
    tool_results = [
        {
            "type": "sql",
            "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
        }
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": False}
    result = try_analyzer_fast_path(
        "推荐三个练腿动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result == (True, "fast_path:per_task sql=[3]>=[3]")


def test_fast_path_rejects_insufficient_sql_for_request():
    tool_results = [{"type": "sql", "data": [{"id": "1"}]}]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": False}
    result = try_analyzer_fast_path(
        "推荐三个练腿动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result is None


def test_fast_path_rejects_empty_progression_graph():
    tool_results = [
        {"type": "sql", "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        {"type": "graph", "scenario": "progression", "data": []},
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": True}
    result = try_analyzer_fast_path(
        "俯卧撑太简单了，推荐进阶动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result is None


def test_fast_path_allows_empty_injury_avoidance_graph():
    tool_results = [
        {"type": "sql", "data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        {"type": "graph", "scenario": "injury_avoidance", "data": []},
    ]
    flags = {"sql": True, "sql_data": True, "rag": False, "graph": True}
    result = try_analyzer_fast_path(
        "推荐练腿动作",
        tool_results,
        flags=flags,
        is_action_query=True,
        has_safety_concern=False,
    )
    assert result is not None
    assert result[0] is True
