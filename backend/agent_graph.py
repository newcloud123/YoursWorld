"""LangGraph decision DAG for character agents."""

from typing import Callable

from backend.agent_state import AgentState
from backend.agent_tools import (
    format_output_node,
    generate_decision_node,
    post_validate_node,
    pre_validate_node,
    retrieve_memory_node,
    update_memory_node,
)
from backend.config import AGENT_MAX_RETRIES
from backend.memory_manager import MemoryManager
from backend.models import GameMessage


def build_character_agent_graph(
    memory_manager: MemoryManager,
    scene_info: dict,
    npc_names: list[str],
):
    """Build a LangGraph decision graph for a single NPC agent.

    Flow: retrieve_memory -> pre_validate -> generate_decision -> post_validate
                                                              |
                                              passed? -------+-------
                                              /                      \
                                        format_output          generate_decision (retry)
                                              |
                                        update_memory -> END
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError("langgraph is required. Install with: pip install langgraph")

    graph = StateGraph(AgentState)

    # === Nodes ===

    async def _retrieve(state: AgentState):
        return await retrieve_memory_node(state, memory_manager)

    async def _pre_validate(state: AgentState):
        return await pre_validate_node(state)

    async def _generate(state: AgentState):
        return await generate_decision_node(state, memory_manager, scene_info, npc_names)

    async def _post_validate(state: AgentState):
        return await post_validate_node(state)

    def _format(state: AgentState):
        return format_output_node(state)

    async def _update_memory(state: AgentState):
        return await update_memory_node(state, memory_manager)

    graph.add_node("retrieve_memory", _retrieve)
    graph.add_node("pre_validate", _pre_validate)
    graph.add_node("generate_decision", _generate)
    graph.add_node("post_validate", _post_validate)
    graph.add_node("format_output", _format)
    graph.add_node("update_memory", _update_memory)

    # === Edges ===

    graph.set_entry_point("retrieve_memory")
    graph.add_edge("retrieve_memory", "pre_validate")
    graph.add_edge("pre_validate", "generate_decision")

    # Conditional edge after post_validate
    def _should_retry(state: AgentState) -> str:
        post_val = state.get("post_validation", {})
        retry_count = state.get("retry_count", 0)
        if not post_val.get("passed", True) and retry_count < AGENT_MAX_RETRIES:
            return "generate_decision"
        return "format_output"

    graph.add_conditional_edges(
        "post_validate",
        _should_retry,
        {
            "generate_decision": "generate_decision",
            "format_output": "format_output",
        },
    )
    graph.add_edge("generate_decision", "post_validate")
    graph.add_edge("format_output", "update_memory")
    graph.add_edge("update_memory", END)

    return graph.compile()


async def run_character_agent(
    memory_manager: MemoryManager,
    role_id: str,
    role_name: str,
    current_coord: str,
    scene_info: dict,
    player_input: str,
    player_name: str,
    npc_names: list[str],
    narrator_output: str = "",
    previous_npc_outputs: list[dict] = None,
) -> list[GameMessage]:
    """Run a single character agent and return its messages."""
    from backend.extraction import load_novel_characters

    novel_id = memory_manager.novel_id

    # Initialize state
    initial_state: AgentState = {
        "role_id": role_id,
        "role_name": role_name,
        "current_time_coord": current_coord,
        "scene_info": scene_info,
        "player_input": player_input,
        "player_name": player_name,
        "retry_count": 0,
        "narrator_output": narrator_output,
        "previous_npc_outputs": previous_npc_outputs or [],
        "novel_id": novel_id,
    }

    # Build and run graph
    graph = build_character_agent_graph(memory_manager, scene_info, npc_names)
    final_state = await graph.ainvoke(initial_state)

    return final_state.get("final_messages", [])
