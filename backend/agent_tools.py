"""LangGraph node functions for the character agent decision graph."""

import json
import re
from datetime import datetime

from backend.agent_prompts import (
    AGENT_TEMPERATURE,
    build_character_system_prompt,
    build_decision_prompt,
    build_post_validation_prompt,
    build_pre_validation_prompt,
)
from backend.agent_state import AgentState
from backend.config import AGENT_MAX_RETRIES
from backend.extraction import _llm_call, _parse_json_from_text
from backend.memory_manager import MemoryManager
from backend.memory_models import MemoryFragment
from backend.models import GameMessage, MessageType
from backend.spatiotemporal import TimeCoord


async def retrieve_memory_node(state: AgentState, memory_manager: MemoryManager) -> dict:
    """Node: Retrieve memories with temporal filtering and semantic search."""
    role_id = state["role_id"]
    current_coord = state["current_time_coord"]
    player_input = state.get("player_input", "")

    # L1 persona (always loaded)
    l1 = memory_manager.get_persona_fragments(role_id)

    # Retrieve L2+L3 with temporal filtering + semantic search
    result = await memory_manager.retrieve_for_agent(role_id, current_coord, player_input, max_results=15)

    # Separate by layer
    l2 = [f for f in result.fragments if f.valid_time_coord != TimeCoord(state.get("novel_id", ""), 0, 0, 0).to_key()]
    l3 = memory_manager.store.load_l3(TimeCoord.parse(current_coord).to_scene_coord().to_key())

    # Extract cognitive boundary info
    boundary = memory_manager.get_cognitive_boundary(role_id, current_coord)

    return {
        "l1_memories": l1,
        "l2_memories": l2,
        "l3_memories": l3,
        "l4_working": [],
        "knowledge_list": boundary.get("knowledge", []),
        "ability_list": boundary.get("abilities", []),
        "relationship_dict": boundary.get("relationships", {}),
    }


async def pre_validate_node(state: AgentState) -> dict:
    """Node: Check if player input violates character's cognitive boundary."""
    player_input = state.get("player_input", "")
    role_name = state.get("role_name", "")
    knowledge_list = state.get("knowledge_list", [])
    ability_list = state.get("ability_list", [])

    # Quick check: if no knowledge or abilities, everything is valid
    if not knowledge_list and not ability_list:
        return {"pre_validation": {"passed": True, "violations": []}}

    prompt = build_pre_validation_prompt(player_input, role_name, knowledge_list, ability_list)
    try:
        result_text = await _llm_call(prompt, "你是一个精确的一致性校验器。只输出JSON，不要输出其他内容。")
        result_data = _parse_json_from_text(result_text, {"passed": True, "violations": []})
        return {"pre_validation": result_data}
    except Exception as e:
        print(f"Pre-validation failed: {e}")
        return {"pre_validation": {"passed": True, "violations": []}}


async def generate_decision_node(state: AgentState, memory_manager: MemoryManager,
                                  scene_info: dict, npc_names: list[str]) -> dict:
    """Node: Generate NPC response using memory-informed LLM call."""
    role_name = state.get("role_name", "")
    novel_id = state.get("novel_id", "")
    current_coord = state.get("current_time_coord", "")
    player_input = state.get("player_input", "")
    player_name = state.get("player_name", "")
    retry_count = state.get("retry_count", 0)

    # Get memory layers
    l1 = state.get("l1_memories", [])
    l2 = state.get("l2_memories", [])
    l3 = state.get("l3_memories", [])
    knowledge_list = state.get("knowledge_list", [])
    ability_list = state.get("ability_list", [])
    relationship_dict = state.get("relationship_dict", {})

    # Build chapter/scene info
    chapter_title = f"第{TimeCoord.parse(current_coord).chapter}章"
    scene_name = scene_info.get("name", "")

    # Build system prompt
    system_prompt = build_character_system_prompt(
        role_name=role_name,
        novel_name=novel_id,
        chapter_title=chapter_title,
        scene_name=scene_name,
        current_coord=current_coord,
        l1_memories=l1,
        l2_memories=l2,
        l3_memories=l3,
        knowledge_list=knowledge_list,
        ability_list=ability_list,
        relationship_dict=relationship_dict,
    )

    # Add retry context if this is a retry
    if retry_count > 0:
        post_val = state.get("post_validation", {})
        issues = post_val.get("issues", [])
        issue_text = "\n".join(f"- {i.get('explanation', '')}" for i in issues)
        system_prompt += f"\n\n# 重试提醒\n上一次输出存在以下问题，请修正：\n{issue_text}"

    # Build decision prompt
    narrator_output = state.get("narrator_output", "")
    prev_outputs = state.get("previous_npc_outputs", [])
    user_prompt = build_decision_prompt(
        player_input=player_input,
        player_name=player_name,
        npc_names=npc_names,
        scene_info=scene_info,
        narrator_output=narrator_output,
        previous_npc_outputs=prev_outputs,
    )

    try:
        response = await _llm_call(user_prompt, system_prompt)
        parsed = _parse_json_from_text(response, None)
        if parsed and isinstance(parsed, dict):
            return {
                "raw_response": response,
                "parsed_messages": [parsed],
                "retry_count": retry_count,
            }
        else:
            # Fallback: treat as plain text
            return {
                "raw_response": response,
                "parsed_messages": [{"speaker": role_name, "content": response.strip()}],
                "retry_count": retry_count,
            }
    except Exception as e:
        print(f"Decision generation failed: {e}")
        return {
            "raw_response": "",
            "parsed_messages": [{"speaker": role_name, "content": "（沉默不语）"}],
            "retry_count": retry_count,
        }


async def post_validate_node(state: AgentState) -> dict:
    """Node: Check generated output for hallucination and OOC."""
    parsed_messages = state.get("parsed_messages", [])
    role_name = state.get("role_name", "")
    l1 = state.get("l1_memories", [])
    knowledge_list = state.get("knowledge_list", [])
    retry_count = state.get("retry_count", 0)

    if not parsed_messages:
        return {"post_validation": {"passed": True, "issues": []}}

    # Combine all output text
    output_text = "\n".join(m.get("content", "") for m in parsed_messages)
    persona_desc = "\n".join(f.content for f in l1) if l1 else ""

    prompt = build_post_validation_prompt(output_text, role_name, persona_desc, knowledge_list)
    try:
        result_text = await _llm_call(prompt, "你是一个精确的合规校验器。只输出JSON，不要输出其他内容。")
        result_data = _parse_json_from_text(result_text, {"passed": True, "issues": []})

        # If failed and retries left, increment retry count
        if not result_data.get("passed", True) and retry_count < AGENT_MAX_RETRIES:
            return {
                "post_validation": result_data,
                "retry_count": retry_count + 1,
            }
        return {"post_validation": result_data}
    except Exception as e:
        print(f"Post-validation failed: {e}")
        return {"post_validation": {"passed": True, "issues": []}}


def format_output_node(state: AgentState) -> dict:
    """Node: Convert parsed messages to GameMessage list."""
    parsed = state.get("parsed_messages", [])
    pre_val = state.get("pre_validation", {})
    role_name = state.get("role_name", "")
    player_name = state.get("player_name", "")

    messages = []

    # Add GM warning if pre-validation found violations
    if pre_val and not pre_val.get("passed", True):
        violations = pre_val.get("violations", [])
        if violations:
            warnings = [v.get("explanation", "") for v in violations]
            warning_text = "；".join(warnings)
            messages.append(GameMessage(
                type=MessageType.GM,
                speaker="GM",
                content=f"⚠ {warning_text}\n\n你确定要这样做吗？",
            ))

    # Convert parsed messages
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        speaker = entry.get("speaker", "").strip()
        content = entry.get("content", "").strip()
        if not content:
            continue

        if speaker == "旁白" or speaker == "narrator":
            messages.append(GameMessage(
                type=MessageType.NARRATOR,
                speaker="旁白",
                content=content,
            ))
        elif speaker == player_name:
            messages.append(GameMessage(
                type=MessageType.PLAYER,
                speaker=player_name,
                content=content,
            ))
        else:
            messages.append(GameMessage(
                type=MessageType.NPC,
                speaker=speaker or role_name,
                content=content,
            ))

    return {"final_messages": messages}


async def update_memory_node(state: AgentState, memory_manager: MemoryManager) -> dict:
    """Node: Write interaction to L3 memory."""
    role_id = state.get("role_id", "")
    current_coord = state.get("current_time_coord", "")
    player_input = state.get("player_input", "")
    final_messages = state.get("final_messages", [])
    player_name = state.get("player_name", "")

    try:
        coord = TimeCoord.parse(current_coord)

        # Write player action as shared memory
        memory_manager.write_interaction(
            role_id=role_id,
            coord=coord,
            content=f"{player_name}：{player_input}",
            memory_type="event",
            source="player_interaction",
            memory_private=False,
        )

        # Write NPC responses as private memory
        for msg in final_messages:
            if msg.type == MessageType.NPC:
                memory_manager.write_interaction(
                    role_id=role_id,
                    coord=coord,
                    content=msg.content,
                    memory_type="event",
                    source="agent_interaction",
                    memory_private=True,
                )
    except Exception as e:
        print(f"Memory update failed: {e}")

    return {}
