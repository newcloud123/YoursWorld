import os
import json
import uuid
from backend.models import (
    PlayerIdentity, IdentityMode, GameMessage, MessageType,
    ValidationResult, GameSession, CharacterState,
)
from backend.world_engine import WorldState, CognitiveValidator, GameMaster
from backend.extraction import load_novel_characters, load_novel_scenes
from backend.chapter_manager import get_novel_dir

# In-memory session store: session_id -> GameSession
_sessions: dict[str, GameSession] = {}

# Session persistence directory
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sessions")


def _ensure_sessions_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _save_session(session: GameSession):
    """Persist session to disk."""
    _ensure_sessions_dir()
    path = os.path.join(SESSIONS_DIR, f"{session.session_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)


def _load_session(session_id: str) -> GameSession | None:
    """Load session from disk if not in memory."""
    if session_id in _sessions:
        return _sessions[session_id]
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            session = GameSession(**data)
            _sessions[session_id] = session
            return session
    return None


async def start_game(novel_id: str, chapter_id: str, player_identity: PlayerIdentity,
                     scene_id: str = None) -> dict:
    """Start a new game session.

    Returns: { session_id, chapter_id, player_name, scene, opening_narrative }
    """
    session_id = f"game_{uuid.uuid4().hex[:12]}"

    # Initialize world state
    world = WorldState(novel_id, chapter_id)

    # Resolve player name
    if player_identity.mode == IdentityMode.POSSESS:
        chars = load_novel_characters(novel_id)
        char = next((c for c in chars if c["id"] == player_identity.character_id), None)
        player_name = char["name"] if char else player_identity.character_id
    else:
        player_name = player_identity.custom_name or "无名者"

    # Get scene
    scene_data = None
    if scene_id:
        scene_data = world.get_scene(scene_id)
    else:
        available = world.get_available_scenes()
        if available:
            scene_data = available[0]

    # Initialize Game Master
    gm = GameMaster(world, player_identity)
    if scene_data:
        gm.set_scene(scene_data)

    # Generate opening narrative
    opening = await gm.generate_opening()

    # Create session
    session = GameSession(
        session_id=session_id,
        novel_id=novel_id,
        chapter_id=chapter_id,
        player_identity=player_identity,
        messages=[
            GameMessage(type=MessageType.GM, speaker="GM", content=opening),
        ],
    )

    _sessions[session_id] = session
    _save_session(session)

    return {
        "session_id": session_id,
        "chapter_id": chapter_id,
        "player_name": player_name,
        "scene": scene_data,
        "opening_narrative": opening,
    }


async def game_chat(session_id: str, message: str) -> list[GameMessage]:
    """Process a player message in an active game session.

    Returns list of response messages (system warnings, GM narration, NPC dialogue).
    """
    session = _load_session(session_id)
    if not session:
        return [GameMessage(type=MessageType.SYSTEM, speaker="系统", content="会话不存在或已过期。")]

    # Initialize world and GM
    world = WorldState(session.novel_id, session.chapter_id)
    gm = GameMaster(world, session.player_identity)

    # Get scene from session context
    # Try to find scene from opening messages or available scenes
    scenes = world.get_available_scenes()
    if scenes:
        gm.set_scene(scenes[0])

    # Cognitive validation
    validator = CognitiveValidator()
    player_name = _get_player_name(session.player_identity, world)

    # Get character state for validation
    if session.player_identity.mode == IdentityMode.POSSESS:
        char_name = player_name
        char_state = world.get_character_state(char_name)
    else:
        # Custom characters have no pre-existing state constraints
        char_state = _build_custom_state(session.player_identity)

    chapter_info = world.get_chapter_info()
    validation = await validator.validate(message, char_state, chapter_info, player_name)

    # Record player message
    player_msg = GameMessage(type=MessageType.PLAYER, speaker=player_name, content=message)
    session.messages.append(player_msg)

    # Generate GM/NPC response
    response_messages = await gm.process_player_action(message, validation)

    # Add response messages to session
    session.messages.extend(response_messages)

    # Save session
    _save_session(session)

    return [player_msg] + response_messages


def _get_player_name(player_identity: PlayerIdentity, world: WorldState) -> str:
    if player_identity.mode == IdentityMode.POSSESS:
        # character_id is like "char_0", need to find by id first
        for c in world._characters:
            if c.get("id") == player_identity.character_id:
                return c["name"]
        return player_identity.character_id or "玩家"
    return player_identity.custom_name or "玩家"


def _build_custom_state(pi: PlayerIdentity) -> CharacterState:
    """Build a CharacterState for a custom (non-possess) player."""
    return CharacterState(
        location="未知",
        abilities=pi.custom_abilities,
        knowledge=[],
        relationships=pi.custom_relationships,
        status="外来者",
    )


def get_session_state(session_id: str) -> dict | None:
    """Get current session state."""
    session = _load_session(session_id)
    if not session:
        return None

    world = WorldState(session.novel_id, session.chapter_id)
    player_name = _get_player_name(session.player_identity, world)

    if session.player_identity.mode == IdentityMode.POSSESS:
        player_state = world.get_character_state(player_name)
    else:
        player_state = _build_custom_state(session.player_identity)

    return {
        "session_id": session.session_id,
        "novel_id": session.novel_id,
        "chapter_id": session.chapter_id,
        "player_name": player_name,
        "player_state": player_state.model_dump(),
        "messages_count": len(session.messages),
        "messages": [m.model_dump() for m in session.messages],
    }


def list_sessions() -> list[dict]:
    """List all active sessions."""
    result = []
    # From memory
    for sid, session in _sessions.items():
        result.append({
            "session_id": sid,
            "novel_id": session.novel_id,
            "chapter_id": session.chapter_id,
            "messages_count": len(session.messages),
        })
    # From disk (not already in memory)
    if os.path.exists(SESSIONS_DIR):
        for fname in os.listdir(SESSIONS_DIR):
            if fname.endswith(".json"):
                sid = fname[:-5]
                if sid not in _sessions:
                    try:
                        with open(os.path.join(SESSIONS_DIR, fname), "r", encoding="utf-8") as f:
                            data = json.load(f)
                            result.append({
                                "session_id": sid,
                                "novel_id": data.get("novel_id", ""),
                                "chapter_id": data.get("chapter_id", ""),
                                "messages_count": len(data.get("messages", [])),
                            })
                    except Exception:
                        pass
    return result


def delete_session(session_id: str) -> bool:
    """Delete a game session."""
    deleted = False
    if session_id in _sessions:
        del _sessions[session_id]
        deleted = True
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        deleted = True
    return deleted
