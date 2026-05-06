import os
import re
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.models import (
    GameStartRequest, GameStartResponse, GameChatRequest, GameChatResponse,
    GameSessionState, NovelUploadResponse, GameMessage, MessageType,
)
from backend.extraction import (
    extract_novel, load_novel_characters, load_novel_scenes,
    load_novel_timeline, get_novel_graph_data, list_novels,
)
from backend.chapter_manager import load_chapters
from backend.chat import start_game, game_chat, get_session_state, list_sessions, delete_session
from backend.memory_manager import MemoryManager
from backend.migrate_memory import migrate_novel_to_memory

app = FastAPI(title="小说世界 D&D - 沉浸式小说角色扮演")


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# === Novel Management ===

@app.get("/novels")
async def get_novels():
    """List all extracted novels."""
    return list_novels()


@app.post("/novel/upload")
async def upload_novel(file: UploadFile = File(...)):
    """Upload a novel text file, split chapters, and extract timeline."""
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="仅支持 .txt 文件")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="文件过大，请小于 10MB")

    # Decode with multiple encoding support
    text = None
    for encoding in ["utf-8", "gbk", "gb18030", "gb2312", "big5"]:
        try:
            text = content.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = content.decode("utf-8", errors="replace")

    # Generate novel_id from filename
    novel_id = re.sub(r'[^\w一-鿿]', '_', file.filename.replace('.txt', ''))

    # Save temp file for extraction
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"temp_{novel_id}.txt")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(text)

    try:
        result = await extract_novel(temp_path, novel_id)
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return result


# === Novel Data ===

@app.get("/novel/{novel_id}/chapters")
async def get_chapters(novel_id: str):
    """Get chapter list for a novel."""
    chapters = load_chapters(novel_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="小说未找到")
    return chapters


@app.get("/novel/{novel_id}/characters")
async def get_characters(novel_id: str, chapter_id: str = None):
    """Get characters, optionally filtered by chapter state."""
    characters = load_novel_characters(novel_id)
    if not characters:
        raise HTTPException(status_code=404, detail="小说未找到")

    if chapter_id:
        timeline = load_novel_timeline(novel_id)
        ch_states = timeline.get(chapter_id, {})
        result = []
        for char in characters:
            name = char["name"]
            if ch_states and name in ch_states:
                result.append({**char, "current_state": ch_states[name]})
            else:
                # Include default state when timeline is empty or char not in timeline
                result.append({
                    **char,
                    "current_state": {
                        "location": "未知",
                        "abilities": [],
                        "knowledge": [],
                        "relationships": {},
                        "status": "",
                        "events": [],
                    },
                })
        return result

    return characters


@app.get("/novel/{novel_id}/characters/{character_id}")
async def get_character(novel_id: str, character_id: str, chapter_id: str = None):
    """Get single character detail with optional chapter state."""
    characters = load_novel_characters(novel_id)
    character = next((c for c in characters if c["id"] == character_id), None)
    if not character:
        raise HTTPException(status_code=404, detail="角色未找到")

    if chapter_id:
        timeline = load_novel_timeline(novel_id)
        ch_states = timeline.get(chapter_id, {})
        name = character["name"]
        if name in ch_states:
            character["current_state"] = ch_states[name]

    return character


@app.get("/novel/{novel_id}/graph")
async def get_graph(novel_id: str, chapter_id: str = None):
    """Get relationship graph data, optionally filtered by chapter."""
    return get_novel_graph_data(novel_id, chapter_id)


@app.get("/novel/{novel_id}/scenes")
async def get_scenes(novel_id: str, chapter_id: str = None):
    """Get scenes, optionally filtered by chapter."""
    scenes = load_novel_scenes(novel_id)
    if chapter_id:
        return [s for s in scenes if s.get("chapter_id") == chapter_id]
    return scenes


# === Game Session ===

@app.post("/game/start")
async def start_game_session(req: GameStartRequest):
    """Start a new game session."""
    try:
        result = await start_game(
            novel_id=req.novel_id,
            chapter_id=req.chapter_id,
            player_identity=req.player_identity,
            scene_id=req.scene_id,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/{session_id}/chat")
async def game_chat_endpoint(session_id: str, req: GameChatRequest):
    """Send a message in an active game session."""
    messages = await game_chat(session_id, req.message)
    return {"messages": [m.model_dump() for m in messages]}


@app.get("/game/{session_id}/state")
async def get_game_state(session_id: str):
    """Get current game session state."""
    state = get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")
    return state


@app.delete("/game/{session_id}")
async def end_game(session_id: str):
    """End a game session."""
    delete_session(session_id)
    return {"status": "ok"}


@app.get("/sessions")
async def get_sessions():
    """List all active game sessions."""
    return list_sessions()


# === Memory System ===

@app.get("/novel/{novel_id}/memory/{role_id}")
async def get_character_memory(novel_id: str, role_id: str, coord: str = None):
    """Get character's memory state at a given coordinate."""
    mm = MemoryManager(novel_id)
    if not mm.has_memory_data():
        raise HTTPException(status_code=404, detail="该小说尚未迁移记忆数据")
    mm.initialize()
    if coord:
        boundary = mm.get_cognitive_boundary(role_id, coord)
        return boundary
    else:
        persona = mm.get_persona_prompt(role_id)
        return {"persona": persona, "has_memory_data": True}


@app.post("/novel/{novel_id}/memory/migrate")
async def trigger_memory_migration(novel_id: str):
    """Trigger memory migration for a novel."""
    result = await migrate_novel_to_memory(novel_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/novel/{novel_id}/memory/stats")
async def get_memory_stats(novel_id: str, role_id: str = None):
    """Get memory fragment counts per layer."""
    mm = MemoryManager(novel_id)
    if not mm.has_memory_data():
        return {"novel_id": novel_id, "has_memory_data": False}
    return mm.get_stats(role_id)
