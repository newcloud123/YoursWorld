from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# === Enums ===

class IdentityMode(str, Enum):
    POSSESS = "possess"   # 夺舍已有角色
    CUSTOM = "custom"     # 杜撰身份插入


class MessageType(str, Enum):
    PLAYER = "player"     # 玩家发言
    NPC = "npc"           # NPC 角色对话
    GM = "gm"             # GM 叙事
    NARRATOR = "narrator" # 旁白叙述
    SYSTEM = "system"     # 系统提示（校验结果等）


# === Chapter & Timeline ===

class ChapterInfo(BaseModel):
    id: str
    index: int
    title: str
    summary: str = ""
    content_preview: str = ""  # 前200字预览


class CharacterState(BaseModel):
    """角色在某章节的状态快照"""
    location: str = "未知"
    abilities: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)  # 角色名 -> 关系描述
    status: str = ""  # 身份状态，如"外门弟子"
    events: list[str] = Field(default_factory=list)  # 本章经历的事件


class CharacterTimeline(BaseModel):
    """角色完整时间线"""
    id: str
    name: str
    personality: str = ""
    background: str = ""
    states: dict[str, CharacterState] = Field(default_factory=dict)  # chapter_id -> state


class ChapterData(BaseModel):
    """一章的完整数据"""
    chapter_id: str
    character_states: dict[str, CharacterState] = Field(default_factory=dict)
    scenes: list["SceneInfo"] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


# === Scenes ===

class SceneInfo(BaseModel):
    id: str
    name: str
    location: str = ""
    participants: list[str] = Field(default_factory=list)
    description: str = ""
    source_text: str = ""
    chapter_id: str = ""


# === Player Identity ===

class PlayerIdentity(BaseModel):
    mode: IdentityMode
    character_id: Optional[str] = None         # 夺舍模式
    custom_name: Optional[str] = None          # 杜撰模式
    custom_background: Optional[str] = None
    custom_abilities: list[str] = Field(default_factory=list)
    custom_relationships: dict[str, str] = Field(default_factory=dict)  # 与原著角色的关系


# === Game Session ===

class GameMessage(BaseModel):
    type: MessageType
    speaker: str = ""        # 发言者名称
    content: str = ""
    validation: Optional["ValidationResult"] = None


class ValidationResult(BaseModel):
    valid: bool = True
    violations: list["Violation"] = Field(default_factory=list)


class Violation(BaseModel):
    type: str  # knowledge / temporal / ability / relationship
    explanation: str


class GameSession(BaseModel):
    session_id: str
    novel_id: str
    chapter_id: str
    player_identity: PlayerIdentity
    messages: list[GameMessage] = Field(default_factory=list)


# === API Request/Response ===

class NovelUploadResponse(BaseModel):
    novel_id: str
    chapters_count: int
    characters_count: int
    scenes_count: int


class GameStartRequest(BaseModel):
    novel_id: str
    chapter_id: str
    player_identity: PlayerIdentity
    scene_id: Optional[str] = None


class GameStartResponse(BaseModel):
    session_id: str
    chapter_id: str
    player_name: str
    scene: Optional[SceneInfo] = None
    opening_narrative: str = ""


class GameChatRequest(BaseModel):
    message: str


class GameChatResponse(BaseModel):
    messages: list[GameMessage]


class GameSessionState(BaseModel):
    session_id: str
    novel_id: str
    chapter_id: str
    player_name: str
    player_state: Optional[CharacterState] = None
    messages_count: int = 0
