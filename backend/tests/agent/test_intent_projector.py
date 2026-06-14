from app.agent.intent.intent_state import (
    build_planner_history_messages,
    is_greeting_only,
    project_intent,
)
from app.models.schema import RAGQueryExtractSchema, RAGSearchSchema


def test_project_intent_detects_safety_and_knowledge_slots():
    intent = project_intent("深蹲时膝盖痛，先做高翻还是深蹲？")

    assert "safety" in intent.slots
    assert "knowledge" in intent.slots
    assert intent.rag_intent_hint == "knowledge"
    assert intent.routing_hint == "standard"
    assert "current_input" in intent.source_refs


def test_project_intent_chat_only_candidate_for_greeting():
    intent = project_intent("你好")

    assert intent.routing_hint == "chat_only_candidate"
    assert "chitchat" in intent.slots


def test_project_intent_not_chat_only_when_fitness_follows_greeting():
    intent = project_intent("你好，我想练胸")

    assert intent.routing_hint == "standard"
    assert "action_search" in intent.slots


def test_project_intent_includes_profile_constraints():
    intent = project_intent(
        "推荐哑铃动作",
        semantic_profile=[
            {
                "level": "beginner",
                "injuries": ["脊柱"],
                "equipment_list": ["哑铃"],
            }
        ],
    )

    assert any("脊柱" in c for c in intent.constraints)
    assert "semantic_profile" in intent.source_refs


def test_build_planner_history_messages_keeps_last_two_turns():
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
    ]

    trimmed = build_planner_history_messages(history, max_turns=2)

    assert len(trimmed) == 4
    assert trimmed[0]["content"] == "u2"


def test_is_greeting_only_rejects_fitness_small_talk():
    assert is_greeting_only("谢谢") is True
    assert is_greeting_only("谢谢，再推荐几个练背动作") is False


def test_macro_rag_intent_is_applied_without_reclassification():
    extracted = RAGQueryExtractSchema(query_text="波比跳 步骤", top_k=5)
    merged = RAGSearchSchema(
        query_text=extracted.query_text,
        top_k=extracted.top_k,
        intent="exercise",
    )

    assert merged.intent == "exercise"
    assert merged.query_text == "波比跳 步骤"
