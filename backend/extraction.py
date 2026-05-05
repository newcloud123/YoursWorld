import os
import json
import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from openai import AsyncOpenAI

from backend.config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM,
    NOVELS_DIR,
)
from backend.chapter_manager import (
    split_chapters, build_chapter_info, summarize_chapter,
    get_novel_dir, save_chapters,
)
from backend.models import CharacterState, CharacterTimeline, SceneInfo

_embedding_client = None

def _get_embedding_client():
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY)
    return _embedding_client


async def llm_model_func(prompt, system_prompt=None, history_messages=[], keyword_extraction=False, **kwargs) -> str:
    return await openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        **kwargs,
    )


async def embedding_func(texts: list[str]) -> np.ndarray:
    response = await _get_embedding_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return np.array([item.embedding for item in response.data], dtype=np.float32)


def _get_rag(novel_id: str):
    rag_dir = os.path.join(get_novel_dir(novel_id), "rag_storage")
    os.makedirs(rag_dir, exist_ok=True)
    return LightRAG(
        working_dir=rag_dir,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,
            func=embedding_func,
        ),
        addon_params={
            "entity_types": ["person", "organization", "location", "event"],
            "language": "Chinese",
        },
    )


async def _llm_call(prompt: str, system_prompt: str = "") -> str:
    """Simple LLM call wrapper for chapter summarization etc."""
    return await openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        system_prompt=system_prompt or "你是一个小说分析助手。",
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
    )


def _parse_json_from_text(text, default):
    """Extract JSON array or object from LLM response text."""
    import re
    if not text or not isinstance(text, str):
        return default
    json_match = re.search(r'[\[\{].*[\]\}]', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


async def extract_novel(file_path: str, novel_id: str) -> dict:
    """Full novel extraction pipeline: chapter split + timeline extraction.

    Args:
        file_path: path to the novel text file
        novel_id: unique identifier for this novel

    Returns:
        dict with extraction statistics
    """
    novel_dir = get_novel_dir(novel_id)
    os.makedirs(novel_dir, exist_ok=True)

    with open(file_path, "r", encoding="utf-8") as f:
        novel_text = f.read()

    # Copy raw file to novel directory
    raw_path = os.path.join(novel_dir, "raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(novel_text)

    # Step 1: Split into chapters
    chapters_raw = split_chapters(novel_text)
    print(f"Split into {len(chapters_raw)} chapters")

    # Step 2: Generate chapter summaries
    chapter_infos = []
    for ch in chapters_raw:
        info = build_chapter_info(ch)
        info.summary = await summarize_chapter(ch, _llm_call)
        chapter_infos.append(info)

    save_chapters(novel_id, chapter_infos)

    # Step 3: Build global knowledge graph with LightRAG
    rag = _get_rag(novel_id)
    await rag.initialize_storages()
    await rag.ainsert(novel_text)

    # Step 4: Extract global character list and relationships
    characters_raw = await _query_rag(rag,
        "请列出这部小说中的所有主要人物，包括每个人物的姓名、性格特点、背景故事。"
        "请用JSON格式输出：[{\"name\": \"姓名\", \"personality\": \"性格\", \"background\": \"背景\"}]"
    )
    global_characters = _parse_json_from_text(characters_raw, [])
    print(f"Extracted {len(global_characters)} characters")

    relationships_raw = await _query_rag(rag,
        "请列出这部小说中所有人物之间的关系，用JSON格式输出："
        "[{\"source\": \"人物A\", \"target\": \"人物B\", \"relation\": \"关系描述\"}]"
    )
    global_relationships = _parse_json_from_text(relationships_raw, [])
    print(f"Extracted {len(global_relationships)} relationships")

    # Step 5: Save characters immediately (without timeline) so the UI works
    _save_characters(novel_id, global_characters, global_relationships, {})

    # Step 6: Extract scenes (batch all chapters into one query to reduce LLM calls)
    scenes = await _extract_scenes_batch(rag, chapters_raw)
    _save_scenes(novel_id, scenes)
    print(f"Extracted {len(scenes)} scenes")

    # Step 7: Build per-chapter timeline (may be slow, do last)
    try:
        timeline = await _build_timeline(rag, chapters_raw, global_characters, global_relationships)
        _save_timeline(novel_id, timeline)
        # Re-save characters with timeline states
        _save_characters(novel_id, global_characters, global_relationships, timeline)
        print(f"Timeline built for {len(timeline)} chapters")
    except Exception as e:
        print(f"Timeline building failed (non-fatal): {e}")
        _save_timeline(novel_id, {})

    await rag.finalize_storages()

    return {
        "novel_id": novel_id,
        "chapters_count": len(chapters_raw),
        "characters_count": len(global_characters),
        "scenes_count": len(scenes),
        "relationships_count": len(global_relationships),
    }


async def _query_rag(rag, query: str) -> str:
    """Query RAG with error handling."""
    try:
        return await rag.aquery(query, param=QueryParam(mode="hybrid"))
    except Exception as e:
        print(f"RAG query failed: {e}")
        return ""


async def _build_timeline(rag, chapters: list[dict], global_chars: list[dict], global_rels: list[dict]) -> dict:
    """Build per-chapter character state timeline.

    Returns: { chapter_id: { character_name: CharacterState } }
    """
    timeline = {}
    # Accumulated state across chapters
    accumulated = {}  # character_name -> accumulated state dict

    for ch in chapters:
        ch_id = f"ch_{ch['index']}"
        content = ch["content"]

        # Query LLM for character state changes in this chapter
        if len(content) > 6000:
            content = content[:6000] + "\n...(截断)"

        char_names = [c["name"] for c in global_chars]
        prompt = (
            f"以下是小说【{ch['title']}】的内容：\n\n{content}\n\n"
            f"已知主要人物：{'、'.join(char_names)}\n\n"
            "请分析本章中每个出场人物的状态变化，用JSON格式输出：\n"
            "[{\n"
            '  "name": "人物名",\n'
            '  "location": "本章所在位置",\n'
            '  "abilities": ["本章拥有的能力/修为"],\n'
            '  "knowledge": ["本章新知道的信息"],\n'
            '  "relationships": {"其他人名": "关系描述"},\n'
            '  "status": "身份状态",\n'
            '  "events": ["本章经历的关键事件"]\n'
            "}]\n"
            "只输出本章有出场或状态变化的人物。如果没有人物出场，输出空数组 []。"
        )

        try:
            result = await _llm_call(prompt, "你是一个小说分析助手，精确分析每章的人物状态。")
            chapter_states_raw = _parse_json_from_text(result, [])
        except Exception as e:
            print(f"Chapter {ch_id} extraction failed: {e}")
            chapter_states_raw = []

        ch_states = {}
        for item in chapter_states_raw:
            name = item.get("name", "")
            if not name:
                continue

            # Merge with accumulated state
            prev = accumulated.get(name, {})
            # Handle relationships: LLM might return list or dict
            raw_rels = item.get("relationships", {})
            if isinstance(raw_rels, list):
                # Convert list format [{"target": "x", "relation": "y"}] to dict
                rels_dict = {}
                for r in raw_rels:
                    if isinstance(r, dict):
                        target = r.get("target", r.get("name", ""))
                        relation = r.get("relation", r.get("desc", ""))
                        if target:
                            rels_dict[target] = relation
                    elif isinstance(r, str):
                        rels_dict[r] = ""
                raw_rels = rels_dict

            state = CharacterState(
                location=item.get("location") or prev.get("location", "未知"),
                abilities=item.get("abilities") or prev.get("abilities", []),
                knowledge=(prev.get("knowledge", []) + item.get("knowledge", [])),
                relationships={**prev.get("relationships", {}), **raw_rels},
                status=item.get("status") or prev.get("status", ""),
                events=item.get("events", []),
            )
            ch_states[name] = state
            # Update accumulated
            accumulated[name] = {
                "location": state.location,
                "abilities": state.abilities,
                "knowledge": state.knowledge,
                "relationships": state.relationships,
                "status": state.status,
            }

        # Carry forward characters not mentioned in this chapter
        for char_name, prev_state in accumulated.items():
            if char_name not in ch_states:
                ch_states[char_name] = CharacterState(
                    location=prev_state.get("location", "未知"),
                    abilities=prev_state.get("abilities", []),
                    knowledge=prev_state.get("knowledge", []),
                    relationships=prev_state.get("relationships", {}),
                    status=prev_state.get("status", ""),
                )

        timeline[ch_id] = ch_states

    return timeline


async def _extract_scenes_batch(rag, chapters: list[dict]) -> list[dict]:
    """Extract scenes for all chapters in a single batch call."""
    all_scenes = []

    # Build a combined prompt with chapter summaries
    chapters_desc = []
    for ch in chapters:
        content = ch["content"]
        if len(content) > 2000:
            content = content[:2000] + "\n...(截断)"
        chapters_desc.append(f"【{ch['title']}】(index={ch['index']})\n{content}")

    combined_text = "\n\n---\n\n".join(chapters_desc)
    if len(combined_text) > 12000:
        combined_text = combined_text[:12000] + "\n...(总文本过长已截断)"

    prompt = (
        f"以下是小说的多个章节内容：\n\n{combined_text}\n\n"
        "请为每个章节列出最精彩的场景（每章1-2个），用JSON格式输出：\n"
        "[{\"chapter_index\": 0, \"name\": \"场景名\", \"location\": \"地点\", "
        "\"participants\": [\"人物1\", \"人物2\"], \"description\": \"事件描述\"}]\n"
        "注意 chapter_index 必须对应章节的序号（从0开始）。如果没有精彩场景，可以跳过该章。"
    )

    try:
        result = await _llm_call(prompt, "你是一个小说分析助手，提取各章节的关键场景。")
        scenes_raw = _parse_json_from_text(result, [])
    except Exception as e:
        print(f"Batch scene extraction failed: {e}")
        scenes_raw = []

    for s in scenes_raw:
        ch_idx = s.get("chapter_index", 0)
        ch_id = f"ch_{ch_idx}"
        existing_count = sum(1 for sc in all_scenes if sc["chapter_id"] == ch_id)
        scene = {
            "id": f"{ch_id}_scene_{existing_count}",
            "name": s.get("name", ""),
            "location": s.get("location", ""),
            "participants": s.get("participants", []),
            "description": s.get("description", ""),
            "source_text": "",
            "chapter_id": ch_id,
        }
        all_scenes.append(scene)

    return all_scenes


def _save_characters(novel_id: str, characters: list[dict], relationships: list[dict], timeline: dict):
    """Save characters with their timeline states."""
    novel_dir = get_novel_dir(novel_id)
    result = []
    for i, char in enumerate(characters):
        name = char.get("name", "")
        char_data = {
            "id": f"char_{i}",
            "name": name,
            "personality": char.get("personality", ""),
            "background": char.get("background", ""),
            "relationships": [
                r for r in relationships
                if r.get("source") == name or r.get("target") == name
            ],
            "states": {},
        }
        # Collect states from timeline
        for ch_id, ch_states in timeline.items():
            if name in ch_states:
                state = ch_states[name]
                char_data["states"][ch_id] = state.model_dump() if hasattr(state, 'model_dump') else state
        result.append(char_data)

    path = os.path.join(novel_dir, "characters.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def _save_scenes(novel_id: str, scenes: list[dict]):
    novel_dir = get_novel_dir(novel_id)
    path = os.path.join(novel_dir, "scenes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)


def _save_timeline(novel_id: str, timeline: dict):
    """Save the full timeline data."""
    novel_dir = get_novel_dir(novel_id)
    # Convert CharacterState objects to dicts
    serializable = {}
    for ch_id, ch_states in timeline.items():
        serializable[ch_id] = {}
        for name, state in ch_states.items():
            if hasattr(state, 'model_dump'):
                serializable[ch_id][name] = state.model_dump()
            else:
                serializable[ch_id][name] = state

    path = os.path.join(novel_dir, "timeline.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


# === Data loading functions ===

def load_novel_characters(novel_id: str) -> list[dict]:
    path = os.path.join(get_novel_dir(novel_id), "characters.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_novel_scenes(novel_id: str) -> list[dict]:
    path = os.path.join(get_novel_dir(novel_id), "scenes.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_novel_timeline(novel_id: str) -> dict:
    path = os.path.join(get_novel_dir(novel_id), "timeline.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_novel_graph_data(novel_id: str, chapter_id: str = None) -> dict:
    """Build graph data, optionally filtered by chapter."""
    characters = load_novel_characters(novel_id)
    timeline = load_novel_timeline(novel_id)

    nodes = []
    edges = []
    edge_set = set()

    # Filter characters that exist in the given chapter
    active_chars = set()
    if chapter_id and chapter_id in timeline and timeline[chapter_id]:
        active_chars = set(timeline[chapter_id].keys())
    # Fallback: if no timeline data for this chapter, show all characters
    if not active_chars:
        active_chars = {c["name"] for c in characters}

    for char in characters:
        name = char["name"]
        if name not in active_chars:
            continue

        # Get current state for tooltip
        state_info = ""
        if chapter_id and chapter_id in timeline and name in timeline[chapter_id]:
            state = timeline[chapter_id][name]
            state_info = f"位置: {state.get('location', '?')}\n状态: {state.get('status', '?')}"

        nodes.append({
            "id": char["id"],
            "label": name,
            "title": state_info or char.get("personality", ""),
        })

        for rel in char.get("relationships", []):
            source_name = rel.get("source", "")
            target_name = rel.get("target", "")
            # Only include edges where both nodes are active
            if source_name not in active_chars or target_name not in active_chars:
                continue
            source_id = next((c["id"] for c in characters if c["name"] == source_name), None)
            target_id = next((c["id"] for c in characters if c["name"] == target_name), None)
            if source_id and target_id:
                edge_key = tuple(sorted([source_id, target_id]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        "from": source_id,
                        "to": target_id,
                        "label": rel.get("relation", ""),
                    })

    return {"nodes": nodes, "edges": edges}


def list_novels() -> list[dict]:
    """List all extracted novels."""
    if not os.path.exists(NOVELS_DIR):
        return []
    novels = []
    for novel_id in sorted(os.listdir(NOVELS_DIR)):
        novel_dir = os.path.join(NOVELS_DIR, novel_id)
        if not os.path.isdir(novel_dir):
            continue
        chapters_path = os.path.join(novel_dir, "chapters.json")
        characters_path = os.path.join(novel_dir, "characters.json")
        chapters_count = 0
        characters_count = 0
        if os.path.exists(chapters_path):
            with open(chapters_path, "r", encoding="utf-8") as f:
                chapters_count = len(json.load(f))
        if os.path.exists(characters_path):
            with open(characters_path, "r", encoding="utf-8") as f:
                characters_count = len(json.load(f))
        novels.append({
            "novel_id": novel_id,
            "chapters_count": chapters_count,
            "characters_count": characters_count,
        })
    return novels
