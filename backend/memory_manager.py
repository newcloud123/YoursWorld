"""High-level memory API coordinating all four layers."""

import os
import time
from datetime import datetime

import numpy as np

from backend.config import NOVELS_DIR
from backend.memory_models import MemoryFragment, MemoryQueryRequest, MemoryQueryResult, MemoryStats
from backend.memory_store import MemoryStore
from backend.spatiotemporal import TimeCoord


class MemoryManager:
    """Coordinates L1-L4 memory layers for a novel."""

    def __init__(self, novel_id: str):
        self.novel_id = novel_id
        self.store = MemoryStore(novel_id)

    def has_memory_data(self) -> bool:
        return self.store.has_memory_data()

    def initialize(self):
        """Load embeddings into cache if available."""
        t0 = time.time()
        self.store.load_embeddings()
        print(f"[memory] initialize() load_embeddings: {(time.time()-t0)*1000:.0f}ms, cache_size={len(self.store._embedding_cache)}")

    # === L1: Character persona ===

    def get_persona_prompt(self, role_id: str) -> str:
        """Get L1 persona text for system prompt injection."""
        l1 = self.store.load_l1(role_id)
        if not l1:
            return ""
        return "\n".join(f.content for f in l1)

    def get_persona_fragments(self, role_id: str) -> list[MemoryFragment]:
        return self.store.load_l1(role_id)

    # === L2: Chapter state ===

    def load_chapter_memories(self, chapter_key: str) -> list[MemoryFragment]:
        return self.store.load_l2(chapter_key)

    def get_cognitive_boundary(self, role_id: str, current_coord: str) -> dict:
        """Get what a character knows/doesn't know at the given coordinate."""
        t0 = time.time()
        request = MemoryQueryRequest(
            role_id=role_id,
            current_coord=current_coord,
            query_text="",
            max_results=100,
            include_private=True,
        )
        result = self.store.retrieve(request)
        print(f"[memory] get_cognitive_boundary({role_id}): {(time.time()-t0)*1000:.0f}ms, {len(result.fragments)} fragments")
        knowledge = []
        abilities = []
        relationships = {}
        for f in result.fragments:
            if f.memory_type == "info" or f.memory_type == "event":
                knowledge.append(f.content)
            elif f.memory_type == "ability":
                abilities.append(f.content)
            elif f.memory_type == "relationship":
                # Format: "target: description"
                if ":" in f.content:
                    target, desc = f.content.split(":", 1)
                    relationships[target.strip()] = desc.strip()
                else:
                    relationships[f.content] = ""
        return {
            "knowledge": knowledge,
            "abilities": abilities,
            "relationships": relationships,
            "total_memories": len(result.fragments),
        }

    # === L3: Scene memory ===

    def start_scene(self, scene_coord: str):
        self.store.start_scene(scene_coord)

    def end_scene(self, scene_coord: str):
        self.store.archive_scene(scene_coord)

    def write_interaction(self, role_id: str, coord: TimeCoord, content: str,
                          memory_type: str = "event", source: str = "player_interaction",
                          memory_private: bool = False) -> MemoryFragment:
        """Write a new L3 interaction fragment."""
        fragment = MemoryFragment(
            novel_id=self.novel_id,
            role_id=role_id,
            memory_type=memory_type,
            content=content,
            valid_time_coord=coord.to_key(),
            expire_time_coord=TimeCoord.permanent(self.novel_id).to_key(),
            memory_private=memory_private,
            source=source,
        )
        scene_coord = coord.to_scene_coord().to_key()
        self.store.write_l3(scene_coord, fragment)
        return fragment

    # === L4: Working memory ===

    def set_working_memory(self, session_key: str, fragments: list[MemoryFragment]):
        self.store.set_l4(session_key, fragments)

    def get_working_memory(self, session_key: str) -> list[MemoryFragment]:
        return self.store.get_l4(session_key)

    def clear_working_memory(self, session_key: str):
        self.store.clear_l4(session_key)

    # === Core retrieval ===

    async def retrieve_for_agent(self, role_id: str, current_coord: str,
                                  query_text: str, max_results: int = 10) -> MemoryQueryResult:
        """Full retrieval pipeline: temporal filter + vector search + priority sort."""
        query_embedding = None
        if query_text:
            try:
                from backend.extraction import embedding_func
                emb = await embedding_func([query_text])
                if emb is not None and len(emb) > 0:
                    query_embedding = emb[0]
            except Exception as e:
                print(f"Embedding generation failed: {e}")

        request = MemoryQueryRequest(
            role_id=role_id,
            current_coord=current_coord,
            query_text=query_text,
            max_results=max_results,
        )
        return self.store.retrieve(request, query_embedding)

    # === Stats ===

    def get_stats(self, role_id: str = None) -> MemoryStats:
        return self.store.get_stats(role_id)
