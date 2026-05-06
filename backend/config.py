import os

# LLM API Configuration
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-cp-Rh2lGpsni6rcb6tCi5LK9oIuiedZtZk7np1Vi6q35EbMpnZTFr1KA3dC5Msvu-Pah1XEMnnSE0xWil551K0bGYTEEGLueR3Ja2X1fItKdQx1eg65StRGZ8s")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.minimaxi.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "MiniMax-M2.7")

# Embedding API Configuration (SiliconFlow BGE-M3)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "sk-ezhgxvmfpfbnioktmaxcxednnknschztqjnufhhzrjfbqggk")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_DIM = 1024

# Base data directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Novel data directory (per-novel subdirectories)
NOVELS_DIR = os.path.join(DATA_DIR, "novels")

# Legacy paths (for backward compatibility during migration)
RAG_WORKING_DIR = os.path.join(DATA_DIR, "rag_storage")
CHARACTERS_FILE = os.path.join(DATA_DIR, "characters.json")
SCENES_FILE = os.path.join(DATA_DIR, "scenes.json")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Chapter splitting patterns (Chinese novel chapter formats)
CHAPTER_PATTERNS = [
    r"^第[零一二三四五六七八九十百千万\d]+[章回节卷]",
    r"^Chapter\s+\d+",
    r"^\d+\.\s+",
]

# Max characters per LLM call for chapter summarization
MAX_CHAPTER_CONTENT_LENGTH = 6000

# Agent configuration
AGENT_TEMPERATURE = 0.1
AGENT_MAX_RETRIES = 2
MEMORY_EMBEDDING_BATCH_SIZE = 32
MEMORY_TOP_K = 10
MEMORY_DIR_NAME = "memory"

# Game Master system prompt template
GM_SYSTEM_PROMPT = """你是一个小说世界的地下城主（Game Master）。你的职责是：

1. 维护小说世界的一致性和真实感
2. 根据角色的性格、背景、能力来生成合理的 NPC 反应
3. 当玩家行为超出角色认知边界时，给出合理的提示
4. 推进剧情发展，描述环境和事件
5. 在玩家偏离原著时，维持世界的自洽性

## 当前世界状态
小说：{novel_name}
当前章节：{chapter_title}
当前场景：{scene_description}
场景地点：{scene_location}
在场人物：{scene_participants}

## 玩家身份
{player_identity_info}

## 场景中的 NPC 状态
{npc_states}

## 叙事规则
- 用中文写作
- 描写要生动，符合小说风格
- NPC 对话要符合各自的性格设定
- 如果玩家行为不合理，用 GM 身份温和地提示，而不是直接拒绝
- 每次回复控制在 200-400 字
- 在回复末尾可以给出 1-2 个合理的后续行动建议"""

# Cognitive validation prompt
VALIDATION_PROMPT = """你是一个小说世界的一致性校验器。请检查玩家的发言是否符合角色当前的认知边界。

## 角色当前状态
{character_state}

## 当前章节
{chapter_info}

## 玩家的发言
{player_input}

## 校验规则
1. 知识边界：角色是否知道玩家提到的概念/地点/人物？
2. 时态边界：提到的事件是否发生在当前章节之前？
3. 能力边界：角色是否有能力做到玩家声称的行为？
4. 关系边界：玩家声称的互动是否符合当前关系状态？

请以 JSON 格式输出校验结果：
{{"valid": true/false, "violations": [{{"type": "knowledge/temporal/ability/relationship", "explanation": "具体说明"}}]}}

注意：如果玩家只是在做角色当前状态下合理的行动（比如走路、说话、观察环境），应该判定为 valid。只有当玩家明显引用了角色不可能知道的信息或做出超出能力范围的行为时才判定为违规。"""
