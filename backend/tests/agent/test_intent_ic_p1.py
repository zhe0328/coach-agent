from app.agent.intent.fitness_lexicon import FitnessLexicon
from app.agent.intent.intent_state import project_intent, should_chat_only_candidate
from app.agent.intent.matching import has_safety_signal
from app.agent.memory.state_patch import (
    format_state_patch_block,
    merge_state_patch_from_intent,
    merge_state_patch_from_pruned,
)
from app.agent.policy.intent_validators import (
    apply_chat_only_gate,
    injured_joints_triggered,
    validate_and_patch_macro_plan,
)
from app.models.memory import ChatMessage, SessionStatePatch
from app.models.schema import MacroPlanSchema, ToolCallIntent


def test_fitness_lexicon_longest_match_prefers_longer_term():
    lexicon = FitnessLexicon(["罗马尼亚硬拉", "硬拉", "深蹲"])
    matches = lexicon.find_matches("我想练罗马尼亚硬拉")

    assert "罗马尼亚硬拉" in matches
    assert "硬拉" not in matches


def test_fitness_score_zero_for_pure_greeting():
    intent = project_intent("你好")

    assert intent.fitness_score == 0
    assert intent.routing_hint == "chat_only_candidate"


def test_fitness_score_positive_for_equipment_query():
    lexicon = FitnessLexicon(["哑铃", "胸"])
    intent = project_intent("用哑铃练胸", lexicon=lexicon)

    assert intent.fitness_score > 0
    assert intent.routing_hint == "standard"
    assert "哑铃" in intent.lexicon_hits


def test_shoulder_injury_triggers_joint_policy():
    profile = [{"injuries": ["肩关节"], "equipment_list": ["哑铃"], "level": "beginner"}]
    triggered = injured_joints_triggered("我想练卧推", profile)

    assert "肩关节" in triggered


def test_chat_only_gate_overrides_standard_macro_plan():
    intent = project_intent("你好")
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="llm mistake",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql",
                tool_name="sql_tool",
                reason="test",
                focused_query="test",
            )
        ],
    )

    patched, actions = apply_chat_only_gate(plan, intent)

    assert patched.routing_mode == "chat_only"
    assert patched.selected_tools == []
    assert "forced_chat_only:fitness_score" in actions


def test_state_patch_merge_from_pruned_and_intent():
    patch = SessionStatePatch()
    patch = merge_state_patch_from_pruned(
        patch,
        [ChatMessage(role="user", content="我肩膀Previously问的问题？")],
    )
    patch = merge_state_patch_from_intent(
        patch,
        user_goal="用弹力带练背",
        constraints=["受损关节: 肩"],
        slots=["action_search"],
    )

    block = format_state_patch_block(patch)
    assert "user_goal" in block
    assert "open_questions" in block
    assert "hard_constraints" in block


def test_phrase_safety_without_bare_difficulty_char():
    assert has_safety_signal("这个动作太难了") is True
    assert has_safety_signal("难度适中") is False


def test_validate_multi_joint_injection():
    plan = MacroPlanSchema(
        routing_mode="standard",
        routing_reason="sql",
        selected_tools=[
            ToolCallIntent(
                task_id="task_sql",
                tool_name="sql_tool",
                reason="test",
                focused_query="练腿",
            )
        ],
    )
    profile = [{"injuries": ["膝关节"], "equipment_list": [], "level": "beginner"}]

    patched, actions = validate_and_patch_macro_plan(
        "我想练深蹲",
        plan,
        profile,
    )

    assert any("graph_tool" == t.tool_name for t in patched.selected_tools)
    assert any("joints:膝关节" in a for a in actions)


def test_should_chat_only_candidate_rejects_fitness_followup():
    assert should_chat_only_candidate("你好，我想练胸", 0, ["chitchat"]) is False
