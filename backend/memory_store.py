"""Four-layer memory storage engine with temporal filtering and vector search."""

import json
import os
from datetime import datetime

import numpy as np

from backend.config import NOVELS_DIR, EMBEDDING_DIM
from backend.memory_models import (
    MemoryFragment, MemoryLayer, MemoryQueryRequest, MemoryQueryResult, MemoryStats,
)


def _memory_dir(novel_id: str) -> str:
    return os.path.join(NOVELS_DIR, novel_id, "memory")


def _l1_dir(novel_id: str) -> str:
    return os.path.join(_memory_dir(novel_id), "l1")


def _l2_dir(novel_id: str) -> str:
    return os.path.join(_memory_dir(novel_id), "l2")


def _embed_dir(novel_id: str) -> str:
    return os.path.join(_memory_dir(novel_id), "embeddings")


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _load_json(path: str, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else []


class MemoryStore:
    """Four-layer memory storage with temporal hard-filtering and cosine similarity search."""

    def __init__(self, novel_id: str):
        self.novel_id = novel_id
        self._l3_active: dict[str, list[MemoryFragment]] = {}  # scene_coord -> fragments
        self._l4_working: dict[str, list[MemoryFragment]] = {}  # session_key -> fragments
        self._embedding_cache: dict[str, np.ndarray] = {}  # memory_id -> embedding vector

    # === L1: Long-term persona (read-only) ===

    def save_l1(self, role_id: str, fragments: list[MemoryFragment]):
        path = os.path.join(_l1_dir(self.novel_id), f"{role_id}.json")
        data = [f.model_dump(mode="json") for f in fragments]
        _save_json(path, data)

    def load_l1(self, role_id: str) -> list[MemoryFragment]:
        path = os.path.join(_l1_dir(self.novel_id), f"{role_id}.json")
        raw = _load_json(path, [])
        return [MemoryFragment(**item) for item in raw]

    # === L2: Mid-term chapter state (append-only) ===

    def save_l2(self, chapter_key: str, fragments: list[MemoryFragment]):
        """Save L2 fragments for a chapter. Appends to existing data."""
        path = os.path.join(_l2_dir(self.novel_id), f"{chapter_key}.json")
        existing_raw = _load_json(path, [])
        existing_ids = {item.get("memory_id") for item in existing_raw}
        new_data = []
        for f in fragments:
            if f.memory_id not in existing_ids:
                new_data.append(f.model_dump(mode="json"))
        existing_raw.extend(new_data)
        _save_json(path, existing_raw)

    def load_l2(self, chapter_key: str = None) -> list[MemoryFragment]:
        """Load L2 fragments. If chapter_key is None, load all chapters."""
        l2_path = _l2_dir(self.novel_id)
        if not os.path.exists(l2_path):
            return []
        if chapter_key:
            path = os.path.join(l2_path, f"{chapter_key}.json")
            raw = _load_json(path, [])
            return [MemoryFragment(**item) for item in raw]
        # Load all chapters
        all_fragments = []
        for fname in sorted(os.listdir(l2_path)):
            if fname.endswith(".json"):
                raw = _load_json(os.path.join(l2_path, fname), [])
                all_fragments.extend(MemoryFragment(**item) for item in raw)
        return all_fragments

    # === L3: Short-term scene memory (in-memory, archived to L2) ===

    def start_scene(self, scene_coord: str):
        if scene_coord not in self._l3_active:
            self._l3_active[scene_coord] = []

    def write_l3(self, scene_coord: str, fragment: MemoryFragment):
        if scene_coord not in self._l3_active:
            self._l3_active[scene_coord] = []
        self._l3_active[scene_coord].append(fragment)

    def load_l3(self, scene_coord: str) -> list[MemoryFragment]:
        return self._l3_active.get(scene_coord, [])

    def archive_scene(self, scene_coord: str):
        """Archive L3 fragments to L2 at scene end."""
        fragments = self._l3_active.pop(scene_coord, [])
        if not fragments:
            return
        # Group by chapter
        chapter_groups: dict[str, list[MemoryFragment]] = {}
        for f in fragments:
            parts = f.valid_time_coord.rsplit("-", 3)
            if len(parts) >= 2:
                ch_key = f"ch_{int(parts[-3])}"
            else:
                ch_key = "ch_0"
            chapter_groups.setdefault(ch_key, []).append(f)
        for ch_key, ch_fragments in chapter_groups.items():
            self.save_l2(ch_key, ch_fragments)

    # === L4: Working memory (ephemeral) ===

    def set_l4(self, session_key: str, fragments: list[MemoryFragment]):
        self._l4_working[session_key] = fragments

    def get_l4(self, session_key: str) -> list[MemoryFragment]:
        return self._l4_working.get(session_key, [])

    def clear_l4(self, session_key: str):
        self._l4_working.pop(session_key, None)

    # === Embedding management ===

    def save_embeddings(self, fragments: list[MemoryFragment]):
        """Save embeddings to numpy file and build index."""
        emb_dir = _embed_dir(self.novel_id)
        os.makedirs(emb_dir, exist_ok=True)

        embeddings = []
        index = {}
        for i, f in enumerate(fragments):
            if f.embedding:
                embeddings.append(f.embedding)
                index[str(i)] = f.memory_id
                self._embedding_cache[f.memory_id] = np.array(f.embedding, dtype=np.float32)

        if embeddings:
            arr = np.array(embeddings, dtype=np.float32)
            np.save(os.path.join(emb_dir, "fragment_embeddings.npy"), arr)
            _save_json(os.path.join(emb_dir, "fragment_index.json"), index)

    def load_embeddings(self):
        """Load embeddings into cache."""
        emb_dir = _embed_dir(self.novel_id)
        npy_path = os.path.join(emb_dir, "fragment_embeddings.npy")
        idx_path = os.path.join(emb_dir, "fragment_index.json")
        if not os.path.exists(npy_path) or not os.path.exists(idx_path):
            return
        arr = np.load(npy_path)
        index = _load_json(idx_path, {})
        for str_idx, mem_id in index.items():
            i = int(str_idx)
            if i < len(arr):
                self._embedding_cache[mem_id] = arr[i]

    def get_embedding(self, memory_id: str) -> np.ndarray | None:
        return self._embedding_cache.get(memory_id)

    # === Core retrieval: temporal filter + cosine similarity ===

    def retrieve(self, request: MemoryQueryRequest, query_embedding: np.ndarray = None) -> MemoryQueryResult:
        """Retrieve memories with temporal hard-filtering and semantic ranking."""
        # Collect all candidate fragments
        l1 = self.load_l1(request.role_id)
        l2 = self.load_l2()
        l3_all = []
        for frags in self._l3_active.values():
            l3_all.extend(frags)

        # Step 1: Temporal hard-filter
        def is_accessible(frag: MemoryFragment) -> bool:
            if not frag.is_valid_at(request.current_coord):
                return False
            if frag.memory_private and frag.role_id != request.role_id:
                return False
            return True

        l1_filtered = [f for f in l1 if is_accessible(f)]
        l2_filtered = [f for f in l2 if is_accessible(f)]
        l3_filtered = [f for f in l3_all if is_accessible(f)]

        # Step 2: Semantic ranking (if embedding available)
        if query_embedding is not None:
            l1_scored = self._rank_by_similarity(l1_filtered, query_embedding)
            l2_scored = self._rank_by_similarity(l2_filtered, query_embedding)
            l3_scored = self._rank_by_similarity(l3_filtered, query_embedding)
        else:
            # No embedding: sort by recency
            l1_scored = [(f, 1.0) for f in l1_filtered]
            l2_scored = [(f, 0.8) for f in sorted(l2_filtered, key=lambda x: x.valid_time_coord, reverse=True)]
            l3_scored = [(f, 0.6) for f in sorted(l3_filtered, key=lambda x: x.valid_time_coord, reverse=True)]

        # Step 3: Priority merge (L1 > L2 > L3), each layer sorted by score
        all_scored = (
            [(f, s + 3.0) for f, s in l1_scored]  # L1 gets +3.0 priority boost
            + [(f, s + 2.0) for f, s in l2_scored]  # L2 gets +2.0
            + [(f, s + 1.0) for f, s in l3_scored]  # L3 gets +1.0
        )
        all_scored.sort(key=lambda x: x[1], reverse=True)

        # Take top N
        top_fragments = [f for f, _ in all_scored[:request.max_results]]

        layer_counts = {
            "L1": len(l1_filtered),
            "L2": len(l2_filtered),
            "L3": len(l3_filtered),
        }
        return MemoryQueryResult(fragments=top_fragments, layer_counts=layer_counts)

    def _rank_by_similarity(self, fragments: list[MemoryFragment], query_emb: np.ndarray) -> list[tuple[MemoryFragment, float]]:
        """Rank fragments by cosine similarity to query embedding."""
        scored = []
        for f in fragments:
            f_emb = self.get_embedding(f.memory_id)
            if f_emb is not None:
                sim = self._cosine_similarity(query_emb, f_emb)
                scored.append((f, sim))
            else:
                scored.append((f, 0.0))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    # === Stats ===

    def get_stats(self, role_id: str = None) -> MemoryStats:
        l1_count = len(self.load_l1(role_id)) if role_id else 0
        l2_fragments = self.load_l2()
        l3_count = sum(len(frags) for frags in self._l3_active.values())
        return MemoryStats(
            novel_id=self.novel_id,
            role_id=role_id,
            l1_count=l1_count,
            l2_count=len(l2_fragments),
            l3_count=l3_count,
            total_fragments=l1_count + len(l2_fragments) + l3_count,
            has_embeddings=bool(self._embedding_cache),
        )

    def has_memory_data(self) -> bool:
        """Check if this novel has been migrated to the memory system."""
        return os.path.exists(_memory_dir(self.novel_id))
