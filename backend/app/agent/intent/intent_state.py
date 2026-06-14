from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.intent.fitness_lexicon import FitnessLexicon
from app.agent.intent.matching import has_safety_signal, is_noise_input
from app.agent.policy.routing_keywords import (
    ACTION_KEYWORDS,
    EXERCISE_RAG_KEYWORDS,
    GREETING_PREFIXES,
    KNOWLEDGE_RAG_KEYWORDS,
)

IntentSlot = Literal["action_search", "safety", "knowledge", "planning", "chitchat"]
RagIntent = Literal["exercise", "knowledge", "mixed"]
IntentSourceRef = Literal[
    "current_input", "session_summary", "semantic_profile", "analyzer_feedback", "state_patch"
]
RoutingHint = Literal["standard", "chat_only_candidate"]

PLANNER_HISTORY_MAX_TURNS = 2


class IntentState(BaseModel):
    user_goal: str = Field(..., description="用户本轮核心目标（通常等于或提炼自当前输入）")
    current_task: str | None = Field(
        None, description="更细粒度的子任务，如'筛选哑铃练胸动作'"
    )
    slots: list[IntentSlot] = Field(default_factory=list)
    rag_intent_hint: RagIntent | None = Field(
        None, description="若本轮仅需单一 RAG 检索时的意图提示"
    )
    constraints: list[str] = Field(
        default_factory=list, description="来自画像或上下文的硬约束"
    )
    source_refs: list[IntentSourceRef] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    routing_hint: RoutingHint = Field("standard")
    fitness_score: int = Field(0, description="健身相关信号强度；0 且无 safety/planning 可候选 chat_only")
    lexicon_hits: list[str] = Field(default_factory=list, description="FitnessLexicon 命中词")


def _contains_any(text: str, keywords: frozenset[str]) -> bool:
    lowered = text.lower()
    return any(kw in text or kw in lowered for kw in keywords)


def has_fitness_entities(text: str, lexicon: FitnessLexicon | None = None) -> bool:
    lex = lexicon or FitnessLexicon.bootstrap()
    return lex.has_fitness_signal(text) or _contains_any(text, ACTION_KEYWORDS)


def compute_fitness_score(
    text: str,
    lexicon: FitnessLexicon,
    slots: list[IntentSlot],
) -> tuple[int, list[str]]:
    hits = lexicon.find_matches(text)
    score = lexicon.score_hits(text)
    if _contains_any(text, ACTION_KEYWORDS):
        score += 2
    if "action_search" in slots:
        score += 2
    if "knowledge" in slots:
        score += 1
    if "planning" in slots:
        score += 2
    if "safety" in slots:
        score += 2
    return score, hits


def is_greeting_only(text: str, lexicon: FitnessLexicon | None = None) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if has_fitness_entities(stripped, lexicon):
        return False
    normalized = stripped.lower()
    if any(normalized.startswith(prefix) for prefix in GREETING_PREFIXES):
        remainder = stripped
        for prefix in GREETING_PREFIXES:
            if normalized.startswith(prefix):
                remainder = stripped[len(prefix) :].strip("，,。.!！?？ ")
                break
        return not remainder or len(remainder) <= 8
    return False


def should_chat_only_candidate(
    text: str,
    fitness_score: int,
    slots: list[IntentSlot],
    *,
    lexicon: FitnessLexicon | None = None,
) -> bool:
    if fitness_score > 0:
        return False
    if "safety" in slots or "planning" in slots:
        return False
    if is_noise_input(text):
        return True
    return is_greeting_only(text, lexicon)


def detect_intent_slots(
    user_input: str,
    lexicon: FitnessLexicon | None = None,
) -> list[IntentSlot]:
    if is_noise_input(user_input):
        return ["chitchat"]

    lex = lexicon or FitnessLexicon.bootstrap()
    slots: list[IntentSlot] = []
    if _contains_any(user_input, ACTION_KEYWORDS) or lex.has_fitness_signal(user_input):
        slots.append("action_search")
    if has_safety_signal(user_input):
        slots.append("safety")
    if _contains_any(user_input, KNOWLEDGE_RAG_KEYWORDS):
        slots.append("knowledge")
    if any(token in user_input for token in ("计划", "课表", "排课")):
        slots.append("planning")
    if is_greeting_only(user_input, lex):
        slots.append("chitchat")
    if not slots:
        slots.append("action_search")
    return slots


def infer_rag_intent_hint(user_input: str, slots: list[IntentSlot]) -> RagIntent | None:
    exercise_hit = _contains_any(user_input, EXERCISE_RAG_KEYWORDS)
    knowledge_hit = _contains_any(user_input, KNOWLEDGE_RAG_KEYWORDS) or (
        "knowledge" in slots
    )
    if exercise_hit and knowledge_hit:
        return "mixed"
    if exercise_hit:
        return "exercise"
    if knowledge_hit:
        return "knowledge"
    return None


def extract_profile_constraints(
    semantic_profile: list[dict[str, Any]] | None,
) -> list[str]:
    if not semantic_profile:
        return []
    profile = semantic_profile[0]
    constraints: list[str] = []
    level = profile.get("level")
    if level:
        constraints.append(f"体能级别: {level}")
    injuries = profile.get("injuries") or []
    if injuries:
        constraints.append(f"受损关节: {', '.join(injuries)}")
    equipment = profile.get("equipment_list") or []
    if equipment:
        constraints.append(f"可用器械: {', '.join(equipment)}")
    else:
        constraints.append("可用器械: 自重")
    return constraints


def profile_has_spine_injury(semantic_profile: list[dict[str, Any]] | None) -> bool:
    if not semantic_profile:
        return False
    injuries = semantic_profile[0].get("injuries") or []
    return any("脊柱" in str(item) for item in injuries)


def project_intent(
    user_input: str,
    *,
    session_summary: str = "",
    semantic_profile: list[dict[str, Any]] | None = None,
    analyzer_feedback: str = "",
    state_patch_goal: str = "",
    lexicon: FitnessLexicon | None = None,
) -> IntentState:
    text = (user_input or "").strip()
    lex = lexicon or FitnessLexicon.bootstrap()
    source_refs: list[IntentSourceRef] = ["current_input"]
    slots = detect_intent_slots(text, lex)
    constraints = extract_profile_constraints(semantic_profile)
    fitness_score, lexicon_hits = compute_fitness_score(text, lex, slots)

    if session_summary.strip():
        source_refs.append("session_summary")
    if semantic_profile:
        source_refs.append("semantic_profile")
    if analyzer_feedback.strip():
        source_refs.append("analyzer_feedback")
    if state_patch_goal.strip():
        source_refs.append("state_patch")

    routing_hint: RoutingHint = (
        "chat_only_candidate"
        if should_chat_only_candidate(text, fitness_score, slots, lexicon=lex)
        else "standard"
    )

    confidence = 0.85
    if analyzer_feedback.strip():
        confidence = 0.7
    if routing_hint == "chat_only_candidate":
        confidence = 0.9
    if fitness_score >= 4:
        confidence = min(0.95, confidence + 0.05)

    user_goal = text or state_patch_goal.strip()[:200]

    return IntentState(
        user_goal=user_goal,
        current_task=text[:120] if text else None,
        slots=slots,
        rag_intent_hint=infer_rag_intent_hint(text, slots),
        constraints=constraints,
        source_refs=source_refs,
        confidence=confidence,
        routing_hint=routing_hint,
        fitness_score=fitness_score,
        lexicon_hits=lexicon_hits,
    )


def format_intent_block(intent_state: IntentState) -> str:
    lines = [
        "【结构化意图投影 IntentState】",
        f"- user_goal: {intent_state.user_goal}",
        f"- slots: {', '.join(intent_state.slots)}",
        f"- routing_hint: {intent_state.routing_hint}",
        f"- fitness_score: {intent_state.fitness_score}",
        f"- confidence: {intent_state.confidence:.2f}",
    ]
    if intent_state.lexicon_hits:
        lines.append(f"- lexicon_hits: {', '.join(intent_state.lexicon_hits[:8])}")
    if intent_state.rag_intent_hint:
        lines.append(f"- rag_intent_hint: {intent_state.rag_intent_hint}")
    if intent_state.constraints:
        lines.append(f"- constraints: {'; '.join(intent_state.constraints)}")
    if any("脊柱" in c for c in intent_state.constraints):
        lines.append(
            "- policy_note: 用户档案含脊柱受损，若涉及下肢/背部训练必须选装 graph_tool"
        )
    return "\n".join(lines) + "\n\n"


def build_planner_history_messages(
    history_messages: list[dict[str, str]],
    *,
    max_turns: int = PLANNER_HISTORY_MAX_TURNS,
) -> list[dict[str, str]]:
    from app.agent.context.planner_history import build_planner_history_messages as _build

    return _build(history_messages, max_turns=max_turns)
