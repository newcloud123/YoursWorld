"""Multi-agent coordinator: memory-informed single-pass generation.

Performance-optimized design: keeps the memory system's spatiotemporal filtering
and persona injection, but uses a single LLM call for narrator + all NPC dialogue
(matching the legacy GameMaster's 2-call total: 1 validation + 1 generation).
"""

import json
import re
import time

from backend.agent_prompts import AGENT_TEMPERATURE, build_character_system_prompt
from backend.extraction import _llm_call, _parse_json_from_text
from backend.memory_manager import MemoryManager
from backend.models import (
    GameMessage, MessageType, PlayerIdentity, IdentityMode,
    ValidationResult, Violation, CharacterState,
)
from backend.spatiotemporal import TimeCoord
from backend.world_engine import WorldState, CognitiveValidator


class MultiAgentCoordinator:
    """Memory-informed coordinator: retrieves memories, validates, generates in 2 LLM calls."""

    def __init__(self, memory_manager: MemoryManager, world: WorldState,
                 player_identity: PlayerIdentity):
        self.memory_manager = memory_manager
        self.world = world
        self.player_identity = player_identity

    def _get_player_name(self) -> str:
        if self.player_identity.mode == IdentityMode.POSSESS:
            for c in self.world._characters:
                if c.get("id") == self.player_identity.character_id:
                    return c["name"]
            return self.player_identity.character_id or "玩家"
        return self.player_identity.custom_name or "玩家"

    def _get_npc_info(self, scene: dict) -> list[dict]:
        """Get NPC list with their role_ids and names."""
        player_name = self._get_player_name()
        participants = scene.get("participants", [])
        npcs = []
        for name in participants:
            if name == player_name or name == "众人":
                continue
            role_id = name
            for c in self.world._characters:
                if c.get("name") == name:
                    role_id = c.get("id", name)
                    break
            npcs.append({"role_id": role_id, "name": name})
        return npcs

    async def process_scene_turn(
        self,
        player_input: str,
        current_coord: str,
        scene: dict,
    ) -> list[GameMessage]:
        """Process a scene turn in 2 LLM calls: 1 validation + 1 generation.

        Memory retrieval and update happen around these calls (no LLM).
        """
        player_name = self._get_player_name()
        npc_info = self._get_npc_info(scene)
        npc_names = [n["name"] for n in npc_info]

        # === Step 1: Memory retrieval for all NPCs (no LLM call) ===
        t0 = time.time()
        npc_memory_contexts = {}
        for npc in npc_info:
            boundary = self.memory_manager.get_cognitive_boundary(npc["role_id"], current_coord)
            persona = self.memory_manager.get_persona_prompt(npc["role_id"])
            l1 = self.memory_manager.get_persona_fragments(npc["role_id"])
            l3 = self.memory_manager.store.load_l3(
                TimeCoord.parse(current_coord).to_scene_coord().to_key()
            )
            npc_memory_contexts[npc["name"]] = {
                "persona": persona,
                "l1": l1,
                "knowledge": boundary.get("knowledge", []),
                "abilities": boundary.get("abilities", []),
                "relationships": boundary.get("relationships", {}),
                "l3": l3,
            }
        print(f"[multi_agent] Step 1 记忆召回 ({len(npc_info)} NPCs): {(time.time()-t0)*1000:.0f}ms")

        # === Step 2: Global pre-validation (1 LLM call) ===
        t0 = time.time()
        validation = await self._global_validate(
            player_input, player_name, npc_memory_contexts
        )
        print(f"[multi_agent] Step 2 全局校验 (LLM): {(time.time()-t0)*1000:.0f}ms")

        # === Step 3: Single generation call for narrator + all NPCs (1 LLM call) ===
        t0 = time.time()
        messages = await self._generate_all(
            player_input, player_name, scene, npc_info,
            npc_memory_contexts, validation, current_coord
        )
        print(f"[multi_agent] Step 3 决策生成 (LLM): {(time.time()-t0)*1000:.0f}ms")

        # === Step 4: Memory update (no LLM call) ===
        t0 = time.time()
        self._update_memories(messages, player_name, player_input, current_coord, npc_info)
        print(f"[multi_agent] Step 4 记忆更新: {(time.time()-t0)*1000:.0f}ms")

        if not messages:
            messages.append(GameMessage(
                type=MessageType.GM, speaker="GM",
                content="（世界的运转似乎出现了短暂的停滞...）",
            ))

        return messages

    async def _global_validate(
        self, player_input: str, player_name: str,
        npc_memory_contexts: dict,
    ) -> ValidationResult:
        """Single global validation using the player's character state (1 LLM call)."""
        # Use player's own state for validation (same as legacy path)
        if self.player_identity.mode == IdentityMode.POSSESS:
            char_state = self.world.get_character_state(player_name)
        else:
            char_state = CharacterState(
                location="未知",
                abilities=self.player_identity.custom_abilities,
                knowledge=[],
                relationships=self.player_identity.custom_relationships,
                status="外来者",
            )
        chapter_info = self.world.get_chapter_info()
        validator = CognitiveValidator()
        return await validator.validate(player_input, char_state, chapter_info, player_name)

    async def _generate_all(
        self, player_input: str, player_name: str, scene: dict,
        npc_info: list[dict], npc_memory_contexts: dict,
        validation: ValidationResult, current_coord: str,
    ) -> list[GameMessage]:
        """Single LLM call generating narrator + all NPC dialogue with memory context."""
        messages = []

        # Add validation warning if needed
        if validation and not validation.valid:
            warnings = [v.explanation for v in validation.violations]
            warning_text = "；".join(warnings)
            messages.append(GameMessage(
                type=MessageType.GM, speaker="GM",
                content=f"⚠ {warning_text}\n\n你确定要这样做吗？",
            ))

        # Build memory-informed NPC state descriptions
        npc_states = self._build_memory_npc_states(npc_info, npc_memory_contexts, player_name)

        # Build player info
        player_info = self._build_player_info()

        # Build system prompt with memory context
        chapter = self.world.get_chapter_info()
        system_prompt = self._build_memory_system_prompt(
            chapter, scene, player_info, npc_states, current_coord
        )

        # Build user prompt (same structure as legacy GameMaster)
        npc_names = [n["name"] for n in npc_info]
        npc_list_str = "、".join(npc_names) if npc_names else "无"

        user_prompt = (
            f"## 当前场景\n{scene.get('description', '无特定场景')}\n"
            f"地点：{scene.get('location', '未知')}\n\n"
            f"## 玩家「{player_name}」的行动\n{player_input}\n\n"
            f"## 在场 NPC\n{npc_list_str}\n\n"
            f"## 任务\n"
            f"请以 JSON 数组格式回复，每个元素代表一段叙述或一个角色的对话。\n\n"
            f"格式要求：\n"
            f"1. 第一个元素必须是旁白（narrator），描述环境变化和事件发展\n"
            f"2. 之后每个在场 NPC 各一个元素，包含该角色的对话和行为\n"
            f"3. 每个 NPC 的发言要严格符合其性格和认知边界（见系统提示中的记忆信息）\n"
            f"4. 如果场景没有 NPC，只需旁白即可\n"
            f"5. 旁白控制在 100-200 字，每个 NPC 对话控制在 50-100 字\n\n"
            f"输出格式（严格JSON数组）：\n"
            f'[\n'
            f'  {{"speaker": "旁白", "content": "环境描述和事件叙述..."}},\n'
            f'  {{"speaker": "NPC名", "content": "NPC的对话和行为..."}},\n'
            f'  ...\n'
            f']\n\n'
            f"只输出JSON数组，不要输出其他内容。"
        )

        try:
            response = await _llm_call(user_prompt, system_prompt)
            entries = _parse_json_from_text(response, None)
            if entries and isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    speaker = entry.get("speaker", "").strip()
                    content = entry.get("content", "").strip()
                    if not content:
                        continue
                    if speaker in ("旁白", "narrator"):
                        messages.append(GameMessage(
                            type=MessageType.NARRATOR, speaker="旁白", content=content,
                        ))
                    elif speaker in npc_names:
                        messages.append(GameMessage(
                            type=MessageType.NPC, speaker=speaker, content=content,
                        ))
                    elif speaker == player_name:
                        messages.append(GameMessage(
                            type=MessageType.PLAYER, speaker=player_name, content=content,
                        ))
                    else:
                        messages.append(GameMessage(
                            type=MessageType.GM, speaker=speaker or "GM", content=content,
                        ))
            else:
                # Fallback: treat as GM narration
                messages.append(GameMessage(
                    type=MessageType.GM, speaker="GM", content=response.strip(),
                ))
        except Exception as e:
            print(f"Generation failed: {e}")
            messages.append(GameMessage(
                type=MessageType.GM, speaker="GM",
                content="（世界的运转似乎出现了短暂的停滞...）",
            ))

        return messages

    def _build_memory_npc_states(self, npc_info: list[dict],
                                  npc_memory_contexts: dict, player_name: str) -> str:
        """Build NPC state descriptions from memory (replaces legacy _build_npc_states)."""
        lines = []
        for npc in npc_info:
            name = npc["name"]
            ctx = npc_memory_contexts.get(name, {})
            persona = ctx.get("persona", "未知")[:80]
            knowledge = ctx.get("knowledge", [])
            abilities = ctx.get("abilities", [])
            rels = ctx.get("relationships", {})
            rel_with_player = rels.get(player_name, "不认识")

            knowledge_preview = "、".join(knowledge[:5]) if knowledge else "无"
            ability_desc = "、".join(abilities[:3]) if abilities else "无特殊能力"

            lines.append(
                f"- {name}：性格{persona}，"
                f"能力：{ability_desc}，"
                f"已知信息：{knowledge_preview}{'...' if len(knowledge) > 5 else ''}，"
                f"与玩家关系：{rel_with_player}"
            )
        return "\n".join(lines) if lines else "无其他 NPC"

    def _build_player_info(self) -> str:
        """Build player identity info (same as legacy GameMaster._build_player_info)."""
        pi = self.player_identity
        if pi.mode == IdentityMode.POSSESS:
            char = {}
            for c in self.world._characters:
                if c.get("id") == pi.character_id:
                    char = c
                    break
            state = self.world.get_character_state(char.get("name", ""))
            return (
                f"模式：夺舍\n"
                f"角色名：{char.get('name', '未知')}\n"
                f"性格：{char.get('personality', '未知')}\n"
                f"背景：{char.get('background', '未知')}\n"
                f"当前状态：{state.status or '未知'}，位置：{state.location}\n"
                f"能力：{'、'.join(state.abilities) or '凡人'}\n"
                f"注意：玩家是穿越者，拥有自己的意识，但使用该角色的身体和记忆。"
            )
        else:
            rels_desc = "、".join(f"{k}({v})" for k, v in (pi.custom_relationships or {}).items())
            return (
                f"模式：杜撰身份\n"
                f"名字：{pi.custom_name}\n"
                f"背景：{pi.custom_background or '未知'}\n"
                f"能力：{'、'.join(pi.custom_abilities) or '普通人'}\n"
                f"与原著角色关系：{rels_desc or '无'}\n"
                f"注意：这是一个外来角色，原著角色不认识此人。"
            )

    def _build_memory_system_prompt(self, chapter: dict, scene: dict,
                                     player_info: str, npc_states: str,
                                     current_coord: str) -> str:
        """Build system prompt with spatiotemporal memory context."""
        return f"""你是一个小说世界的地下城主（Game Master）。你的职责是：

1. 维护小说世界的一致性和真实感
2. 根据角色的性格、记忆、能力来生成合理的 NPC 反应
3. 推进剧情发展，描述环境和事件

## 当前时空锁定
时空坐标：{current_coord}
你绝对不能让任何角色提及、使用该时空坐标之后才发生的事件、信息、能力。

## 当前世界状态
小说：{self.world.novel_id}
当前章节：{chapter.get('title', '未知')}
当前场景：{scene.get('description', '无特定场景')}
场景地点：{scene.get('location', '未知')}
在场人物：{'、'.join(scene.get('participants', [])) or '无'}

## 玩家身份
{player_info}

## 场景中的 NPC 状态（基于记忆系统）
{npc_states}

## 叙事规则
- 用中文写作
- 描写要生动，符合小说风格
- NPC 对话要严格符合各自的性格和当前认知边界
- NPC 绝对不能说出超出当前时空坐标之后才知道的信息
- 如果玩家行为超出认知边界，用 GM 身份温和提示
- 每次回复控制在 200-400 字"""

    def _update_memories(self, messages: list[GameMessage], player_name: str,
                          player_input: str, current_coord: str,
                          npc_info: list[dict]):
        """Write interaction to L3 memory (no LLM call)."""
        try:
            coord = TimeCoord.parse(current_coord)
            # Write player action as shared memory for all NPCs
            for npc in npc_info:
                self.memory_manager.write_interaction(
                    role_id=npc["role_id"], coord=coord,
                    content=f"{player_name}：{player_input}",
                    memory_type="event", source="player_interaction",
                    memory_private=False,
                )
            # Write NPC responses as private memory
            for msg in messages:
                if msg.type == MessageType.NPC:
                    # Find role_id for this NPC
                    role_id = msg.speaker
                    for npc in npc_info:
                        if npc["name"] == msg.speaker:
                            role_id = npc["role_id"]
                            break
                    self.memory_manager.write_interaction(
                        role_id=role_id, coord=coord,
                        content=msg.content,
                        memory_type="event", source="agent_interaction",
                        memory_private=True,
                    )
        except Exception as e:
            print(f"Memory update failed: {e}")


async def process_with_multi_agent(
    novel_id: str,
    chapter_id: str,
    scene: dict,
    player_identity: PlayerIdentity,
    player_input: str,
    scene_coord: str = None,
) -> list[GameMessage]:
    """High-level entry point: memory-informed generation in 2 LLM calls."""
    world = WorldState(novel_id, chapter_id)
    memory_manager = MemoryManager(novel_id)
    memory_manager.initialize()

    # Determine scene coordinate
    if not scene_coord:
        scene_id = scene.get("id", "")
        coord = TimeCoord.from_scene_id(novel_id, chapter_id, scene_id)
        scene_coord = coord.to_scene_coord().to_key()

    memory_manager.start_scene(scene_coord)

    coordinator = MultiAgentCoordinator(memory_manager, world, player_identity)
    messages = await coordinator.process_scene_turn(player_input, scene_coord, scene)

    return messages
