"""Dynamic prompt templates for memory-driven character agents."""

from backend.memory_models import MemoryFragment

# Temperature for all agent LLM calls (per plan2.md section 4.1)
AGENT_TEMPERATURE = 0.1


def build_character_system_prompt(
    role_name: str,
    novel_name: str,
    chapter_title: str,
    scene_name: str,
    current_coord: str,
    l1_memories: list[MemoryFragment],
    l2_memories: list[MemoryFragment],
    l3_memories: list[MemoryFragment],
    knowledge_list: list[str],
    ability_list: list[str],
    relationship_dict: dict[str, str],
) -> str:
    """Build the full system prompt for a character agent (plan2.md section 3.2)."""

    # L1 persona
    persona_text = "\n".join(f"- {m.content}" for m in l1_memories) if l1_memories else "（无）"

    # L2 state
    ability_text = "\n".join(f"- {a}" for a in ability_list) if ability_list else "（无）"
    knowledge_text = "\n".join(f"- {k}" for k in knowledge_list) if knowledge_list else "（无）"
    rel_text = "\n".join(f"- {target}: {desc}" for target, desc in relationship_dict.items()) if relationship_dict else "（无）"

    # L3 scene context
    scene_context = "\n".join(f"- {m.content}" for m in l3_memories) if l3_memories else "（无）"

    return f"""# 角色基础档案（只读，不可修改）
你是小说《{novel_name}》中的{role_name}，以下是你的核心人设，必须100%严格遵守，绝对不能偏离：
{persona_text}

# 当前时空锁定
你当前所处的小说时空坐标为：{current_coord}，对应原著的{chapter_title}，{scene_name}场景。
你绝对不能知晓、提及、使用该时空坐标之后才发生的事件、信息、能力、地点，所有内容必须严格局限在当前时空的有效记忆内。

# 你的当前认知边界（仅能使用以下提供的记忆，绝对不能使用任何外部知识）
## 1. 你当前已解锁的能力与状态：
{ability_text}
## 2. 你当前已知的信息与经历：
{knowledge_text}
## 3. 你与其他角色的关系：
{rel_text}
## 5. 当前场景的上下文记忆：
{scene_context}

# 绝对禁止规则（违反则直接作废输出）
1. 绝对不能提及、使用当前时空坐标之后才解锁的任何信息、事件、能力、地点，包括小说后续剧情的内容；
2. 绝对不能脱离你的核心人设，你的对话语气、行为逻辑、决策方式，必须100%符合你的人设；
3. 绝对不能使用你当前未解锁的能力、功法、物品，必须严格符合当前时空的修为与状态；
4. 你只能知晓你自己的私有记忆和场景内的公开共享记忆，绝对不能知晓其他角色的私有记忆、内心想法；
5. 所有信息必须来自于上面提供的记忆，绝对不能调用你自身的预训练知识，不能编造记忆中没有的内容。

# 工具使用规则
你必须通过调用提供的工具，获取所有需要的信息，不能自行编造。所有工具调用必须携带当前锁定的时空坐标{current_coord}。"""


def build_decision_prompt(
    player_input: str,
    player_name: str,
    npc_names: list[str],
    scene_info: dict,
    narrator_output: str = "",
    previous_npc_outputs: list[dict] = None,
) -> str:
    """Build the per-turn decision prompt for an NPC agent."""

    npc_list_str = "、".join(npc_names) if npc_names else "无"
    scene_desc = scene_info.get("description", "无特定场景")
    scene_location = scene_info.get("location", "未知")

    context_parts = [f"## 当前场景\n{scene_desc}\n地点：{scene_location}"]
    if narrator_output:
        context_parts.append(f"## 旁白叙述\n{narrator_output}")
    if previous_npc_outputs:
        prev_lines = []
        for out in previous_npc_outputs:
            prev_lines.append(f"- {out.get('speaker', '未知')}：{out.get('content', '')}")
        context_parts.append(f"## 其他角色已发言\n" + "\n".join(prev_lines))

    context = "\n\n".join(context_parts)

    return f"""{context}

## 玩家「{player_name}」的行动
{player_input}

## 任务
请以你所扮演角色的身份，对玩家的行动做出回应。
回复要符合你的性格、当前认知和时空状态。
回复控制在 50-150 字，包含对话和行为描述。

## 输出格式（严格JSON）
{{"speaker": "{npc_names[0] if npc_names else 'NPC'}", "content": "你的回应内容..."}}

只输出一个JSON对象，不要输出其他内容。"""


def build_narrator_prompt(
    player_input: str,
    player_name: str,
    scene_info: dict,
) -> str:
    """Build the prompt for the narrator agent."""

    scene_desc = scene_info.get("description", "无特定场景")
    scene_location = scene_info.get("location", "未知")
    participants = "、".join(scene_info.get("participants", [])) or "无"

    return f"""## 当前场景
{scene_desc}
地点：{scene_location}
在场人物：{participants}

## 玩家「{player_name}」的行动
{player_input}

## 任务
请以旁白叙述的方式，描述环境变化和事件发展。
描写要生动，符合小说风格，控制在 100-200 字。

## 输出格式（严格JSON）
{{"speaker": "旁白", "content": "环境描述和事件叙述..."}}

只输出一个JSON对象，不要输出其他内容。"""


def build_pre_validation_prompt(
    player_input: str,
    character_name: str,
    knowledge_list: list[str],
    ability_list: list[str],
) -> str:
    """Build prompt for cognitive boundary check."""

    knowledge_desc = "\n".join(f"- {k}" for k in knowledge_list) if knowledge_list else "（无已知信息）"
    ability_desc = "\n".join(f"- {a}" for a in ability_list) if ability_list else "（无能力）"

    return f"""你是一个小说世界的一致性校验器。请检查玩家的发言是否符合角色「{character_name}」的认知边界。

## 角色当前已知信息
{knowledge_desc}

## 角色当前能力
{ability_desc}

## 玩家的发言
{player_input}

## 校验规则
1. 知识边界：角色是否知道玩家提到的概念/地点/人物？
2. 能力边界：角色是否有能力做到玩家声称的行为？
3. 时态边界：提到的事件是否发生在当前时空坐标之前？

请以 JSON 格式输出校验结果：
{{"passed": true/false, "violations": [{{"type": "knowledge/temporal/ability", "explanation": "具体说明"}}]}}

注意：如果玩家只是在做角色当前状态下合理的行动（比如走路、说话、观察环境），应该判定为 passed=true。只有当玩家明显引用了角色不可能知道的信息或做出超出能力范围的行为时才判定为违规。"""


def build_post_validation_prompt(
    generated_output: str,
    character_name: str,
    persona_desc: str,
    knowledge_list: list[str],
) -> str:
    """Build prompt for hallucination/OOC check."""

    knowledge_desc = "\n".join(f"- {k}" for k in knowledge_list) if knowledge_list else "（无）"

    return f"""你是一个小说世界的合规校验器。请检查角色「{character_name}」的输出是否合规。

## 角色人设
{persona_desc}

## 角色当前已知信息
{knowledge_desc}

## 角色的输出
{generated_output}

## 校验规则
1. 人设一致性：输出的语气、行为是否符合角色人设？
2. 信息溯源：输出中的所有信息，是否都能在已知信息中找到来源？
3. 幻觉检测：是否有使用了角色不可能知道的外部知识？

请以 JSON 格式输出校验结果：
{{"passed": true/false, "issues": [{{"type": "ooc/hallucination/temporal", "explanation": "具体说明"}}]}}

注意：如果输出基本符合人设和认知，应该判定为 passed=true。轻微的语气偏差可以忽略。"""
