from langgraph.graph import END, StateGraph

from app.agent.graph.state import CoachAgentState
from app.agent.utils.logger import LogColor, logger


def route_after_macro(state: CoachAgentState) -> str:
    if state.get("planner_offline"):
        return "tool_execute"

    macro_plan = state.get("macro_plan")
    if macro_plan and (
        macro_plan.routing_mode == "chat_only" or not macro_plan.selected_tools
    ):
        logger.info(
            f"{LogColor.TOOL}[Graph] chat_only → synthesizer{LogColor.RESET}"
        )
        return "synthesizer"

    return "small_planner"


def route_after_tool_execute(state: CoachAgentState) -> str:
    if state.get("planner_offline") or state.get("skip_analyzer"):
        logger.info(
            f"{LogColor.ROUTER}[Graph] offline/fallback → synthesizer (skip analyzer){LogColor.RESET}"
        )
        return "synthesizer"
    return "analyzer"


def route_after_analyzer(state: CoachAgentState) -> str:
    prefix = f"{LogColor.ROUTER}[Graph]"
    suffix = f"{LogColor.RESET}"

    if state.get("is_complete"):
        logger.info(f"{prefix} analyzer pass → synthesizer{suffix}")
        return "synthesizer"

    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)

    if loop_count >= max_loops - 1:
        logger.warning(
            f"{prefix} max retries ({max_loops}) → synthesizer (force stop){suffix}"
        )
        return "synthesizer"

    logger.info(f"{prefix} analyzer fail → context_builder (retry){suffix}")
    return "context_builder"


def build_coach_graph(orchestrator, *, interrupt_before: list[str] | None = None):
    graph = StateGraph(CoachAgentState)

    graph.add_node("load_context", orchestrator._node_load_context)
    graph.add_node("intent_projector", orchestrator._node_intent_projector)
    graph.add_node("context_builder", orchestrator._node_context_builder)
    graph.add_node("macro_planner", orchestrator._node_macro_planner)
    graph.add_node("small_planner", orchestrator._node_small_planner)
    graph.add_node("tool_execute", orchestrator._node_tool_execute)
    graph.add_node("analyzer", orchestrator._node_analyzer)
    graph.add_node("synthesizer", orchestrator._node_synthesizer)
    graph.add_node("persist", orchestrator._node_persist)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "intent_projector")
    graph.add_edge("intent_projector", "context_builder")
    graph.add_edge("context_builder", "macro_planner")

    graph.add_conditional_edges(
        "macro_planner",
        route_after_macro,
        {
            "small_planner": "small_planner",
            "tool_execute": "tool_execute",
            "synthesizer": "synthesizer",
        },
    )

    graph.add_edge("small_planner", "tool_execute")

    graph.add_conditional_edges(
        "tool_execute",
        route_after_tool_execute,
        {
            "analyzer": "analyzer",
            "synthesizer": "synthesizer",
        },
    )

    graph.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {
            "context_builder": "context_builder",
            "synthesizer": "synthesizer",
        },
    )

    graph.add_edge("synthesizer", "persist")
    graph.add_edge("persist", END)

    compile_kwargs = {}
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
    return graph.compile(**compile_kwargs)
