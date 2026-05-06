"""Spatiotemporal coordinate system for memory management.

Coordinates follow the format: {novel_id}-{chapter:04d}-{scene:04d}-{event:04d}
All numeric fields are zero-padded to 4 digits, enabling lexicographic comparison.
"""

import re


class TimeCoord:
    """Spatiotemporal coordinate that locks a character's cognition to a specific story point."""

    _PATTERN = re.compile(r'^(.+)-(\d{4})-(\d{4})-(\d{4})$')

    def __init__(self, novel_id: str, chapter: int, scene: int, event: int):
        self.novel_id = novel_id
        self.chapter = chapter
        self.scene = scene
        self.event = event

    @classmethod
    def parse(cls, coord_str: str) -> "TimeCoord":
        m = cls._PATTERN.match(coord_str)
        if not m:
            raise ValueError(f"Invalid time coordinate format: {coord_str}")
        return cls(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)))

    @classmethod
    def from_scene_id(cls, novel_id: str, chapter_id: str, scene_id: str = None) -> "TimeCoord":
        """Convert existing ch_X / ch_X_scene_Y format to TimeCoord."""
        chapter_num = int(chapter_id.replace("ch_", "")) if chapter_id else 0
        scene_num = 0
        if scene_id and "_scene_" in scene_id:
            parts = scene_id.split("_scene_")
            scene_num = int(parts[-1])
        return cls(novel_id, chapter_num, scene_num, 0)

    @classmethod
    def permanent(cls, novel_id: str) -> "TimeCoord":
        """Sentinel coordinate for memories that never expire."""
        return cls(novel_id, 9999, 9999, 9999)

    def advance_event(self) -> "TimeCoord":
        """Return a new coordinate with event incremented by 1."""
        return TimeCoord(self.novel_id, self.chapter, self.scene, self.event + 1)

    def to_chapter_coord(self) -> "TimeCoord":
        """Return coordinate at chapter level (scene=0, event=0)."""
        return TimeCoord(self.novel_id, self.chapter, 0, 0)

    def to_scene_coord(self) -> "TimeCoord":
        """Return coordinate at scene level (event=0)."""
        return TimeCoord(self.novel_id, self.chapter, self.scene, 0)

    def to_key(self) -> str:
        """Serialize to comparable string."""
        return f"{self.novel_id}-{self.chapter:04d}-{self.scene:04d}-{self.event:04d}"

    def __str__(self) -> str:
        return self.to_key()

    def __repr__(self) -> str:
        return f"TimeCoord({self.to_key()})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, TimeCoord):
            return NotImplemented
        return self.to_key() == other.to_key()

    def __lt__(self, other) -> bool:
        if not isinstance(other, TimeCoord):
            return NotImplemented
        return self.to_key() < other.to_key()

    def __le__(self, other) -> bool:
        if not isinstance(other, TimeCoord):
            return NotImplemented
        return self.to_key() <= other.to_key()

    def __gt__(self, other) -> bool:
        if not isinstance(other, TimeCoord):
            return NotImplemented
        return self.to_key() > other.to_key()

    def __ge__(self, other) -> bool:
        if not isinstance(other, TimeCoord):
            return NotImplemented
        return self.to_key() >= other.to_key()

    def __hash__(self) -> int:
        return hash(self.to_key())
