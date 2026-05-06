"""Migration script: convert existing novel data to 4-layer memory format."""

import json
import os
from datetime import datetime

from backend.config import NOVELS_DIR
from backend.memory_models import MemoryFragment
from backend.memory_store import MemoryStore
from backend.spatiotemporal import TimeCoord


def _load_json(path: str, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else []


async def migrate_novel_to_memory(novel_id: str) -> dict:
    """Convert existing characters.json + timeline.json to 4-layer memory format.

    Returns migration statistics.
    """
    novel_dir = os.path.join(NOVELS_DIR, novel_id)
    if not os.path.exists(novel_dir):
        return {"error": f"Novel directory not found: {novel_id}"}

    store = MemoryStore(novel_id)
    now = datetime.now()
    l1_fragments = []
    l2_fragments = []
    all_fragments = []  # For embedding generation

    # Load existing data
    characters = _load_json(os.path.join(novel_dir, "characters.json"), [])
    timeline = _load_json(os.path.join(novel_dir, "timeline.json"), {})
    scenes = _load_json(os.path.join(novel_dir, "scenes.json"), [])

    # === L1: Character persona from characters.json ===
    for char in characters:
        role_id = char.get("id", "")
        name = char.get("name", "")
        personality = char.get("personality", "")
        background = char.get("background", "")

        if personality:
            frag = MemoryFragment(
                novel_id=novel_id,
                role_id=role_id,
                memory_type="persona",
                content=f"【{name}性格】{personality}",
                valid_time_coord=TimeCoord(novel_id, 0, 0, 0).to_key(),
                expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                memory_private=True,
                source="novel_extract",
                create_time=now,
                update_time=now,
            )
            l1_fragments.append(frag)
            all_fragments.append(frag)

        if background:
            frag = MemoryFragment(
                novel_id=novel_id,
                role_id=role_id,
                memory_type="persona",
                content=f"【{name}背景】{background}",
                valid_time_coord=TimeCoord(novel_id, 0, 0, 0).to_key(),
                expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                memory_private=True,
                source="novel_extract",
                create_time=now,
                update_time=now,
            )
            l1_fragments.append(frag)
            all_fragments.append(frag)

        # Save L1 per character
        if l1_fragments:
            char_l1 = [f for f in l1_fragments if f.role_id == role_id]
            if char_l1:
                store.save_l1(role_id, char_l1)

    # === L2: Chapter state from timeline.json ===
    for ch_key, ch_states in timeline.items():
        ch_fragments = []
        for char_name, state in ch_states.items():
            # Find role_id from characters list
            role_id = ""
            for c in characters:
                if c.get("name") == char_name:
                    role_id = c.get("id", "")
                    break
            if not role_id:
                role_id = char_name  # Fallback to name as role_id

            # Parse chapter index from ch_key (e.g., "ch_0" -> 0)
            ch_num = int(ch_key.replace("ch_", "")) if ch_key.startswith("ch_") else 0
            coord = TimeCoord(novel_id, ch_num, 0, 0)

            # Location
            location = state.get("location", "未知") if isinstance(state, dict) else "未知"
            if location and location != "未知":
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="environment",
                    content=f"当前位置：{location}",
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=False,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

            # Abilities
            abilities = state.get("abilities", []) if isinstance(state, dict) else []
            for ability in abilities:
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="ability",
                    content=ability,
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=True,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

            # Knowledge
            knowledge = state.get("knowledge", []) if isinstance(state, dict) else []
            for k in knowledge:
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="info",
                    content=k,
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=False,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

            # Relationships
            rels = state.get("relationships", {}) if isinstance(state, dict) else {}
            if isinstance(rels, list):
                # Convert list format to dict
                rel_dict = {}
                for r in rels:
                    if isinstance(r, dict):
                        target = r.get("target", r.get("name", ""))
                        relation = r.get("relation", r.get("desc", ""))
                        if target:
                            rel_dict[target] = relation
                rels = rel_dict
            for target, relation in rels.items():
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="relationship",
                    content=f"{target}: {relation}",
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=True,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

            # Status
            status = state.get("status", "") if isinstance(state, dict) else ""
            if status:
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="info",
                    content=f"身份状态：{status}",
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=False,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

            # Events
            events = state.get("events", []) if isinstance(state, dict) else []
            for evt in events:
                frag = MemoryFragment(
                    novel_id=novel_id,
                    role_id=role_id,
                    memory_type="event",
                    content=evt,
                    valid_time_coord=coord.to_key(),
                    expire_time_coord=TimeCoord.permanent(novel_id).to_key(),
                    memory_private=False,
                    source="novel_extract",
                    create_time=now,
                    update_time=now,
                )
                ch_fragments.append(frag)
                all_fragments.append(frag)

        # Save L2 per chapter
        if ch_fragments:
            store.save_l2(ch_key, ch_fragments)
            l2_fragments.extend(ch_fragments)

    # === Generate embeddings ===
    try:
        from backend.extraction import embedding_func
        contents = [f.content for f in all_fragments if f.content]
        if contents:
            # Batch embedding generation
            batch_size = 32
            for i in range(0, len(contents), batch_size):
                batch = contents[i:i + batch_size]
                embeddings = await embedding_func(batch)
                for j, emb in enumerate(embeddings):
                    idx = i + j
                    if idx < len(all_fragments):
                        all_fragments[idx].embedding = emb.tolist()
            store.save_embeddings(all_fragments)
    except Exception as e:
        print(f"Embedding generation failed (non-fatal): {e}")

    # Save migration metadata
    meta = {
        "novel_id": novel_id,
        "migrated_at": now.isoformat(),
        "l1_count": len(l1_fragments),
        "l2_count": len(l2_fragments),
        "total_fragments": len(all_fragments),
        "characters_count": len(characters),
        "chapters_count": len(timeline),
    }
    meta_path = os.path.join(NOVELS_DIR, novel_id, "memory", "meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta
