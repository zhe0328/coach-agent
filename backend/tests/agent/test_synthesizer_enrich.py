"""Unit tests for two-phase synthesizer enrich (no live LLM)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent.roles.synthesizer import CoachSynthesizer
from app.models.schema import ExerciseBase, MacroPlanSchema, ToolCallIntent


def _synth() -> CoachSynthesizer:
    return CoachSynthesizer(MagicMock(), skill_guide="")


def _macro_with_sql(limit: int = 3) -> MacroPlanSchema:
    return MacroPlanSchema(
        routing_mode="standard",
        routing_reason="test",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql",
                tool_name="sql_tool",
                reason="filter",
                focused_query="练胸",
                limit=limit,
            )
        ],
    )


def _exercise(ex_id: str, name: str) -> ExerciseBase:
    return ExerciseBase(
        id=ex_id,
        name_zh=name,
        body_part_zh="胸部",
        target_zh="胸大肌",
        equipment_zh="哑铃",
        difficulty="intermediate",
        category_zh="力量训练",
    )


def _macro_with_two_sql() -> MacroPlanSchema:
    return MacroPlanSchema(
        routing_mode="standard",
        routing_reason="test",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql_back",
                tool_name="sql_tool",
                reason="练背",
                focused_query="练背",
                limit=3,
            ),
            ToolCallIntent(
                task_id="task_sql_glute",
                tool_name="sql_tool",
                reason="练臀",
                focused_query="练臀",
                limit=3,
            ),
        ],
    )


def test_resolve_exercises_per_task_limit_not_global_slice():
    synth = _synth()
    tasks = [
        {
            "task_id": "task_sql_back",
            "tool_name": "sql_tool",
            "data": [_exercise(f"b{i}", f"背{i}") for i in range(5)],
        },
        {
            "task_id": "task_sql_glute",
            "tool_name": "sql_tool",
            "data": [_exercise(f"g{i}", f"臀{i}") for i in range(5)],
        },
    ]
    exercises = synth._resolve_exercises(tasks, _macro_with_two_sql())
    assert len(exercises) == 6
    assert [e.id for e in exercises] == ["b0", "b1", "b2", "g0", "g1", "g2"]


def test_resolve_exercises_filters_unsafe_ids():
    synth = _synth()
    tasks = [
        {
            "task_id": "task_sql",
            "tool_name": "sql_tool",
            "data": [
                _exercise("e1", "卧推"),
                _exercise("e2", "飞鸟"),
            ],
        },
        {
            "task_id": "task_graph",
            "tool_name": "graph_tool",
            "data": [
                {"unsafe_exercise_id": "e1", "unsafe_name": "卧推", "safe_replacements": []},
            ],
        },
    ]
    exercises = synth._resolve_exercises(tasks, _macro_with_sql(limit=5))
    assert [e.id for e in exercises] == ["e2"]


def test_build_references_includes_graph_and_sql():
    synth = _synth()
    tasks = [
        {
            "task_id": "task_sql",
            "tool_name": "sql_tool",
            "data": [_exercise("e2", "飞鸟")],
        },
        {
            "task_id": "task_graph",
            "tool_name": "graph_tool",
            "data": [
                {
                    "unsafe_name": "卧推",
                    "safe_replacements": [{"id": "e3", "name_zh": "跪姿俯卧撑"}],
                }
            ],
        },
    ]
    refs = synth._build_references(tasks)
    assert any("飞鸟" in r for r in refs)
    assert any("卧推" in r for r in refs)
    assert any("跪姿俯卧撑" in r for r in refs)


def test_build_response_from_guidance_has_structured_fields():
    synth = _synth()
    tasks = [
        {
            "task_id": "task_sql",
            "tool_name": "sql_tool",
            "data": [_exercise("e2", "飞鸟")],
        },
    ]
    macro = _macro_with_sql()
    resp = synth.build_response_from_guidance(
        "这是教练正文。请保持动作标准。",
        macro,
        tasks,
    )
    assert resp.response_type == "recommendation"
    assert resp.exercises and resp.exercises[0].name_zh == "飞鸟"
    assert resp.greeting
    assert resp.summary
    assert resp.selected_tools == ["sql_tool"]


@pytest.mark.asyncio
async def test_enrich_metadata_uses_llm_when_available():
    synth = _synth()
    from app.agent.roles.synthesizer import CoachEnrichMetadata

    mock_parsed = CoachEnrichMetadata(
        greeting="加油！",
        summary="今天练胸，注意肩胛稳定。",
        safety_alerts=["如有不适请停止"],
    )
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(parsed=mock_parsed))]
    synth.client.beta.chat.completions.parse = MagicMock(return_value=mock_response)

    tasks = [
        {
            "task_id": "task_sql",
            "tool_name": "sql_tool",
            "data": [_exercise("e2", "飞鸟")],
        },
    ]
    resp = await synth.enrich_metadata(
        "教练正文…",
        "推荐练胸动作",
        _macro_with_sql(),
        tasks,
    )
    assert resp.greeting == "加油！"
    assert resp.summary == "今天练胸，注意肩胛稳定。"
    assert resp.safety_alerts == ["如有不适请停止"]
    assert resp.detailed_guidance == "教练正文…"
