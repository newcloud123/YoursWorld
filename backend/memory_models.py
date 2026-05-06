"""Pydantic models for the 4-layer spatiotemporal memory system."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MemoryLayer(str, Enum):
    L1 = "L1"  # Long-term persona (read-only)
    L2 = "L2"  # Mid-term chapter state (append-only)
    L3 = "L3"  # Short-term scene memory (read-write)
    L4 = "L4"  # Working memory (ephemeral)


MemoryType = Literal["persona", "event", "ability", "relationship", "info", "environment"]
MemorySource = Literal["novel_extract", "player_interaction", "agent_interaction", "system_generated"]


class MemoryFragment(BaseModel):
    """A single memory fragment bound to a spatiotemporal coordinate."""
    memory_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:16])
    novel_id: str
    role_id: str
    memory_type: MemoryType
    content: str
    embedding: Optional[list[float]] = None  # 1024-dim BGE-M3
    valid_time_coord: str   # Memory becomes accessible at this coordinate
    expire_time_coord: str  # Memory stops being accessible after this coordinate
    memory_private: bool = True  # True = only owner role can retrieve
    source: MemorySource
    create_time: datetime = Field(default_factory=datetime.now)
    update_time: datetime = Field(default_factory=datetime.now)

    def is_valid_at(self, current_coord: str) -> bool:
        """Check if this memory is accessible at the given coordinate."""
        return self.valid_time_coord <= current_coord <= self.expire_time_coord


class MemoryQueryRequest(BaseModel):
    """Request for memory retrieval."""
    role_id: str
    current_coord: str
    query_text: str
    max_results: int = 10
    include_private: bool = True  # Whether to include the role's own private memories


class MemoryQueryResult(BaseModel):
    """Result from memory retrieval."""
    fragments: list[MemoryFragment]
    layer_counts: dict[str, int] = Field(default_factory=dict)  # layer -> count


class MemoryStats(BaseModel):
    """Memory statistics for a novel/character."""
    novel_id: str
    role_id: Optional[str] = None
    l1_count: int = 0
    l2_count: int = 0
    l3_count: int = 0
    total_fragments: int = 0
    has_embeddings: bool = False
