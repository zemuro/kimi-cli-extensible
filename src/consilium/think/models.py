"""Data models for Think mode sessions and messages."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4


@dataclass
class ThinkMessage:
    """A single message in a Think mode session."""

    id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:8]}")
    role: Literal["system", "user", "assistant"] = "user"
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    tokens_in: int | None = None
    tokens_out: int | None = None
    deleted: bool = False
    edited_at: float | None = None
    compacted_into: str | None = None  # summary message id that replaced this message


@dataclass
class CompactResult:
    """Result of a compaction operation."""

    removed: int
    summary: str
    summary_msg_id: str
    old_usage_pct: float
    new_usage_pct: float


@dataclass
class ThinkSession:
    """A mutable-history Think mode session."""

    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: float = field(default_factory=time.time)
    messages: list[ThinkMessage] = field(default_factory=list[ThinkMessage])
    checkpoint_name: str | None = None

    @property
    def title(self) -> str:
        """Derive a title from the first user message, or fall back to session id."""
        for msg in self.messages:
            if msg.role == "user" and msg.content.strip():
                first_line = msg.content.strip().split("\n")[0]
                return first_line[:60] + "..." if len(first_line) > 60 else first_line
        return f"think-{self.id[:8]}"
