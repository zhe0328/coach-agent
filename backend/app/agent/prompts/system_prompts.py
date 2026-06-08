"""
Centralized prompt registry for the coach agent.

Roles still import from skill_guide during the P4 migration; this module is the
single source of truth entry point for versioned prompts and eval reproducibility.
"""

from app.agent.prompts.skill_guide import (
    ASSESSMENT_LOGIC,
    COACH_PERSONA,
    PROGRAMMING_LOGIC,
    SAFETY_GUARDRAILS,
    SYNTHESIZER_SKILL,
    get_skill_by_node,
)

PROMPT_VERSION = "1.0.0"

__all__ = [
    "PROMPT_VERSION",
    "COACH_PERSONA",
    "ASSESSMENT_LOGIC",
    "PROGRAMMING_LOGIC",
    "SAFETY_GUARDRAILS",
    "SYNTHESIZER_SKILL",
    "get_skill_by_node",
]
