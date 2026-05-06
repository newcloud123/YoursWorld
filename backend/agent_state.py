"""LangGraph state schema for character agent decision graph."""

from typing import TypedDict

from backend.memory_models import MemoryFragment
from backend.models import GameMessage


class AgentState(TypedDict, total=False):
    """State for a single character agent's decision cycle."""

    # === Input ===
    role_id: str
    role_name: str
    current_time_coord: str
    scene_info: dict
    player_input: str
    player_name: str

    # === Memory retrieval results ===
    l1_memories: list[MemoryFragment]  # Persona (read-only)
    l2_memories: list[MemoryFragment]  # Chapter state
    l3_memories: list[MemoryFragment]  # Scene context
    l4_working: list[MemoryFragment]   # Current turn context

    # === Decision ===
    decision_goal: str
    raw_response: str
    parsed_messages: list[dict]

    # === Validation ===
    pre_validation: dict   # {"passed": bool, "violations": [...]}
    post_validation: dict  # {"passed": bool, "issues": [...]}
    validation_passed: bool
    retry_count: int

    # === Output ===
    final_messages: list[GameMessage]

    # === Context from other agents ===
    narrator_output: str          # Narrator's description for this turn
    previous_npc_outputs: list[dict]  # {"speaker": str, "content": str}


class SceneAgentState(TypedDict, total=False):
    """State for the multi-agent coordinator graph."""

    scene_coord: str
    scene_info: dict
    player_input: str
    player_name: str
    npc_names: list[str]

    # Narrator output
    narrator_messages: list[GameMessage]

    # Per-NPC outputs (accumulated sequentially)
    npc_outputs: list[dict]  # {"speaker": str, "content": str, "messages": list[GameMessage]}

    # Final merged output
    all_messages: list[GameMessage]
