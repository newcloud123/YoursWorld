import json
import re
from backend.config import GM_SYSTEM_PROMPT, VALIDATION_PROMPT
from backend.models import (
    CharacterState, PlayerIdentity, IdentityMode,
    ValidationResult, Violation, GameMessage, MessageType,
    SceneInfo,
)
from backend.extraction import (
    load_novel_characters, load_novel_scenes, load_novel_timeline,
    _llm_call, _parse_json_from_text,
)
from backend.chapter_manager import load_chapters


class WorldState:
    """Manages the current game world state for a session."""

    def __init__(self, novel_id: str, chapter_id: str):
        self.novel_id = novel_id
        self.chapter_id = chapter_id
        self._timeline = load_novel_timeline(novel_id)
        self._characters = load_novel_characters(novel_id)
        self._scenes = load_novel_scenes(novel_id)
        self._chapters = load_chapters(novel_id)

    def get_chapter_info(self) -> dict:
        for ch in self._chapters:
            if ch.get("id") == self.chapter_id:
                return ch
        return {}

    def get_character_state(self, character_name: str) -> CharacterState:
        ch_states = self._timeline.get(self.chapter_id, {})
        if character_name in ch_states:
            data = ch_states[character_name]
            return CharacterState(**data) if isinstance(data, dict) else data
        return CharacterState()

    def get_character_full(self, character_name: str) -> dict:
        for c in self._characters:
            if c["name"] == character_name:
                return c
        return {}

    def get_available_scenes(self) -> list[dict]:
        return [s for s in self._scenes if s.get("chapter_id") == self.chapter_id]

    def get_scene(self, scene_id: str) -> dict:
        for s in self._scenes:
            if s.get("id") == scene_id:
                return s
        return {}

    def get_npc_list(self, scene: dict = None) -> list[str]:
        if scene:
            return [p for p in scene.get("participants", []) if p != "众人"]
        ch_states = self._timeline.get(self.chapter_id, {})
        return list(ch_states.keys())

    def get_all_characters(self) -> list[dict]:
        result = []
        ch_states = self._timeline.get(self.chapter_id, {})
        for char in self._characters:
            name = char["name"]
            state_data = ch_states.get(name)
            state = CharacterState(**state_data) if isinstance(state_data, dict) else (state_data or CharacterState())
            result.append({
                "id": char["id"],
                "name": name,
                "personality": char.get("personality", ""),
                "background": char.get("background", ""),
                "relationships": char.get("relationships", []),
                "current_state": state.model_dump(),
            })
        return result


class CognitiveValidator:
    """Validates player input against character's cognitive boundaries."""

    async def validate(self, player_input: str, character_state: CharacterState,
                       chapter_info: dict, character_name: str) -> ValidationResult:
        state_desc = (
            f"角色名：{character_name}\n"
            f"当前位置：{character_state.location}\n"
            f"能力/修为：{'、'.join(character_state.abilities) or '未知'}\n"
            f"已知信息：{'、'.join(character_state.knowledge) or '无'}\n"
            f"身份状态：{character_state.status or '未知'}\n"
            f"人际关系：{'、 '.join(f'{k}({v})' for k, v in character_state.relationships.items()) or '无'}"
        )
        chapter_desc = f"第{chapter_info.get('index', '?')}章：{chapter_info.get('title', '未知')}"
        prompt = VALIDATION_PROMPT.format(
            character_state=state_desc,
            chapter_info=chapter_desc,
            player_input=player_input,
        )
        try:
            result_text = await _llm_call(prompt, "你是一个精确的一致性校验器。只输出JSON，不要输出其他内容。")
            result_data = _parse_json_from_text(result_text, {"valid": True, "violations": []})
            violations = [
                Violation(type=v.get("type", "unknown"), explanation=v.get("explanation", ""))
                for v in result_data.get("violations", [])
            ]
            return ValidationResult(valid=result_data.get("valid", True), violations=violations)
        except Exception as e:
            print(f"Validation failed: {e}")
            return ValidationResult(valid=True)


class GameMaster:
    """Narrative arbitrator - generates world responses to player actions.

    Uses a multi-agent approach: one call produces structured output with
    narrator prose and per-NPC dialogue as separate entries.
    """

    def __init__(self, world: WorldState, player_identity: PlayerIdentity):
        self.world = world
        self.player_identity = player_identity
        self._scene = None

    def set_scene(self, scene: dict):
        self._scene = scene

    def _build_player_info(self) -> str:
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
                f"玩家可能做出不符合原著角色性格的行为，这是正常的穿越设定。"
            )
        else:
            rels_desc = "、".join(f"{k}({v})" for k, v in (pi.custom_relationships or {}).items())
            return (
                f"模式：杜撰身份\n"
                f"名字：{pi.custom_name}\n"
                f"背景：{pi.custom_background or '未知'}\n"
                f"能力：{'、'.join(pi.custom_abilities) or '普通人'}\n"
                f"与原著角色关系：{rels_desc or '无'}\n"
                f"注意：这是一个外来角色，原著角色不认识此人。NPC 应根据自己的性格决定如何对待这个陌生人。"
            )

    def _build_npc_states(self) -> str:
        scene = self._scene
        npcs = self.world.get_npc_list(scene)
        player_name = self._get_player_name()
        lines = []
        for npc_name in npcs:
            if npc_name == player_name:
                continue
            state = self.world.get_character_state(npc_name)
            char = self.world.get_character_full(npc_name)
            rel_with_player = state.relationships.get(player_name, "不认识")
            lines.append(
                f"- {npc_name}：性格{char.get('personality', '未知')[:30]}，"
                f"当前位置{state.location}，状态{state.status}，"
                f"与玩家关系：{rel_with_player}"
            )
        return "\n".join(lines) if lines else "无其他 NPC"

    def _get_player_name(self) -> str:
        if self.player_identity.mode == IdentityMode.POSSESS:
            for c in self.world._characters:
                if c.get("id") == self.player_identity.character_id:
                    return c["name"]
            return self.player_identity.character_id or "玩家"
        return self.player_identity.custom_name or "玩家"

    def _get_npc_names(self) -> list[str]:
        """Get list of NPC names in the current scene (excluding the player)."""
        scene = self._scene
        npcs = self.world.get_npc_list(scene)
        player_name = self._get_player_name()
        return [n for n in npcs if n != player_name]

    def build_gm_prompt(self) -> str:
        chapter = self.world.get_chapter_info()
        scene = self._scene or {}
        return GM_SYSTEM_PROMPT.format(
            novel_name=self.world.novel_id,
            chapter_title=chapter.get("title", "未知"),
            scene_description=scene.get("description", "无特定场景"),
            scene_location=scene.get("location", "未知"),
            scene_participants="、".join(scene.get("participants", [])) or "无",
            player_identity_info=self._build_player_info(),
            npc_states=self._build_npc_states(),
        )

    async def generate_opening(self) -> str:
        chapter = self.world.get_chapter_info()
        scene = self._scene or {}
        player_name = self._get_player_name()

        prompt = (
            f"游戏开始。玩家以「{player_name}」的身份进入小说世界。\n"
            f"当前章节：{chapter.get('title', '未知')}\n"
        )
        if scene:
            prompt += (
                f"当前场景：{scene.get('name', '')}\n"
                f"地点：{scene.get('location', '')}\n"
                f"场景描述：{scene.get('description', '')}\n"
            )
        prompt += (
            "\n请用2-3句话描述开场场景，让玩家感受到自己身处小说世界中。"
            "描述要生动，符合小说风格，最后给出一个自然的互动切入点。"
        )
        try:
            return await _llm_call(prompt, self.build_gm_prompt())
        except Exception as e:
            print(f"Opening generation failed: {e}")
            return f"你以「{player_name}」的身份，来到了{scene.get('location', '这个世界')}。周围的一切既陌生又熟悉。"

    async def process_player_action(self, player_input: str,
                                     validation: ValidationResult = None) -> list[GameMessage]:
        """Process a player's action and generate multi-agent dialogue.

        Returns a list of messages: narrator prose + per-NPC dialogue,
        each as a separate GameMessage with clear speaker labels.
        """
        messages = []
        player_name = self._get_player_name()

        # If validation failed, prepend a GM warning
        if validation and not validation.valid:
            warnings = [v.explanation for v in validation.violations]
            warning_text = "；".join(warnings)
            messages.append(GameMessage(
                type=MessageType.GM,
                speaker="GM",
                content=f"⚠ {warning_text}\n\n你确定要这样做吗？",
            ))

        # Get NPC names for structured output
        npc_names = self._get_npc_names()
        npc_list_str = "、".join(npc_names) if npc_names else "无"

        scene = self._scene or {}
        prompt = (
            f"## 当前场景\n{scene.get('description', '无特定场景')}\n"
            f"地点：{scene.get('location', '未知')}\n\n"
            f"## 玩家「{player_name}」的行动\n{player_input}\n\n"
            f"## 在场 NPC\n{npc_list_str}\n\n"
            f"## 任务\n"
            f"请以 JSON 数组格式回复，每个元素代表一段叙述或一个角色的对话。\n\n"
            f"格式要求：\n"
            f"1. 第一个元素必须是旁白（narrator），描述环境变化和事件发展\n"
            f"2. 之后每个在场 NPC 各一个元素，包含该角色的对话和行为\n"
            f"3. 每个 NPC 的发言要符合其性格和与玩家的关系\n"
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
            response = await _llm_call(prompt, self.build_gm_prompt())
            # Parse structured dialogue
            dialogue_entries = self._parse_dialogue(response, player_name, npc_names)

            if dialogue_entries:
                messages.extend(dialogue_entries)
            else:
                # Fallback: treat entire response as GM narration
                messages.append(GameMessage(
                    type=MessageType.GM,
                    speaker="GM",
                    content=response.strip(),
                ))
        except Exception as e:
            print(f"GM response failed: {e}")
            messages.append(GameMessage(
                type=MessageType.GM,
                speaker="GM",
                content="（世界的运转似乎出现了短暂的停滞...）",
            ))

        return messages

    def _parse_dialogue(self, response: str, player_name: str,
                        npc_names: list[str]) -> list[GameMessage]:
        """Parse LLM response into structured dialogue messages."""
        # Try to extract JSON array from response
        entries = _parse_json_from_text(response, None)

        if not entries or not isinstance(entries, list):
            # Try line-based parsing as fallback
            return self._parse_dialogue_lines(response, player_name, npc_names)

        messages = []
        for entry in entries:
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
            elif speaker in npc_names:
                messages.append(GameMessage(
                    type=MessageType.NPC,
                    speaker=speaker,
                    content=content,
                ))
            elif speaker == player_name:
                messages.append(GameMessage(
                    type=MessageType.PLAYER,
                    speaker=player_name,
                    content=content,
                ))
            else:
                # Unknown speaker, treat as GM narration
                messages.append(GameMessage(
                    type=MessageType.GM,
                    speaker=speaker or "GM",
                    content=content,
                ))

        return messages

    def _parse_dialogue_lines(self, response: str, player_name: str,
                               npc_names: list[str]) -> list[GameMessage]:
        """Fallback: parse dialogue from line-based format like '叶凡：...' or [旁白] ..."""
        messages = []
        lines = response.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Match patterns like "叶凡：...", "【旁白】...", "[旁白]..."
            npc_match = None
            for npc in npc_names:
                if line.startswith(f"{npc}：") or line.startswith(f"{npc}:") or \
                   line.startswith(f"【{npc}】") or line.startswith(f"[{npc}]"):
                    npc_match = npc
                    break

            if npc_match:
                content = re.sub(r'^.*?[:：]', '', line).strip()
                content = re.sub(r'^【.*?】\s*', '', content).strip()
                content = re.sub(r'^\[.*?\]\s*', '', content).strip()
                if content:
                    messages.append(GameMessage(
                        type=MessageType.NPC,
                        speaker=npc_match,
                        content=content,
                    ))
            elif line.startswith("旁白") or line.startswith("【旁白】") or line.startswith("[旁白]"):
                content = re.sub(r'^.*?[:：]', '', line).strip()
                content = re.sub(r'^【.*?】\s*', '', content).strip()
                content = re.sub(r'^\[.*?\]\s*', '', content).strip()
                if content:
                    messages.append(GameMessage(
                        type=MessageType.NARRATOR,
                        speaker="旁白",
                        content=content,
                    ))
            else:
                # Plain text - treat as narrator if no speaker detected
                if messages and messages[-1].type == MessageType.NARRATOR:
                    messages[-1].content += "\n" + line
                else:
                    messages.append(GameMessage(
                        type=MessageType.NARRATOR,
                        speaker="旁白",
                        content=line,
                    ))

        return messages
