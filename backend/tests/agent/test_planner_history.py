"""Tests for macro planner history compaction."""

from app.agent.context.planner_history import (
    build_planner_history_messages,
    compact_coach_response_for_planner,
    compact_message_for_planner,
)
from app.models.schema import CoachResponse, ExerciseBase


def _sample_recommendation_json() -> str:
    response = CoachResponse(
        response_type="recommendation",
        greeting="很高兴为您推荐高阶核心训练动作！",
        exercises=[
            ExerciseBase(
                id="core_001",
                name_zh="反向卷腹",
                body_part_zh="腰腹",
                equipment_zh="垫子",
                target_zh="腹直肌",
                difficulty="advanced",
                category_zh="力量训练",
            ),
            ExerciseBase(
                id="core_002",
                name_zh="悬垂举腿",
                body_part_zh="腰腹",
                equipment_zh="单杠",
                target_zh="腹直肌、髋屈肌",
                difficulty="advanced",
                category_zh="力量训练",
            ),
        ],
        detailed_guidance="非常长的详细指导 " * 200,
        safety_alerts=["避免交替侧下拉", "保持肩胛骨下沉"],
        summary="本次为您科学筛选了2个高阶核心训练动作，既确保训练强度，又规避肩胛带风险。",
        selected_tools=["sql_tool", "graph_tool"],
    )
    return response.model_dump_json()


def test_compact_coach_response_drops_detailed_guidance():
    raw = _sample_recommendation_json()
    response = CoachResponse.model_validate_json(raw)

    compact = compact_coach_response_for_planner(response)

    assert "非常长的详细指导" not in compact
    assert "反向卷腹" in compact
    assert "悬垂举腿" in compact
    assert "sql_tool" in compact
    assert len(compact) < len(raw) // 10


def test_compact_message_for_planner_parses_json_assistant():
    raw = _sample_recommendation_json()
    compact = compact_message_for_planner("assistant", raw)

    assert compact.startswith("【上轮教练回复·recommendation】")
    assert "detailed_guidance" not in compact


def test_build_planner_history_compacts_assistant_only():
    history = [
        {"role": "user", "content": "再推荐几个练核心动作"},
        {"role": "assistant", "content": _sample_recommendation_json()},
        {"role": "user", "content": "有没有不用单杠的"},
        {"role": "assistant", "content": _sample_recommendation_json()},
    ]

    trimmed = build_planner_history_messages(history, max_turns=2)

    assert len(trimmed) == 4
    assert trimmed[0]["content"] == "再推荐几个练核心动作"
    assert trimmed[1]["content"].startswith("【上轮教练回复")
    assert "detailed_guidance" not in trimmed[1]["content"]
    assert len(trimmed[1]["content"]) < len(history[1]["content"]) // 10


def test_compact_message_falls_back_for_plain_text():
    long_text = "plain coach reply " * 50
    compact = compact_message_for_planner("assistant", long_text)

    assert compact.endswith("…")
    assert len(compact) <= 320
