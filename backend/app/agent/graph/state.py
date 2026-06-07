from typing import Any, Literal, TypedDict

from app.models.memory import WorkingMemory
from app.models.schema import CoachResponse, FullPlan, MacroPlanSchema


class CoachAgentState(TypedDict, total=False):
    """LangGraph state for the coach agent workflow."""

    # Request context
    user_id: int
    session_id: str
    user_input: str

    # Loaded context
    memory: WorkingMemory
    history_messages: list[dict[str, str]]
    semantic_profile: list[dict[str, Any]]

    # Planner / execution
    macro_plan: MacroPlanSchema | None
    full_plan: FullPlan | None
    tool_results: list[dict[str, Any]]
    executed_tasks_snapshot: list[dict[str, Any]]

    # Analyzer loop
    loop_count: int
    max_loops: int
    is_complete: bool
    analyzer_feedback: str

    # Routing flags
    planner_offline: bool
    skip_analyzer: bool
    routing_mode: Literal["standard", "chat_only", "fallback"]

    # Output
    coach_response: CoachResponse | str | None
