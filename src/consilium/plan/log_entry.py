"""LogEntry dataclass and type constants for persistent logs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Entry type constants
# ---------------------------------------------------------------------------

ENTRY_SYSTEM = "system"
ENTRY_MESSAGE = "message"
ENTRY_EDIT = "edit"
ENTRY_DELETE = "delete"
ENTRY_CHECKPOINT = "checkpoint"
ENTRY_COMPACT = "compact"
ENTRY_TOOL_CALL = "tool_call"
ENTRY_TOOL_RESULT = "tool_result"
ENTRY_DIFF = "diff"
ENTRY_REVIEW = "review"
ENTRY_BRIDGE_OUT = "bridge_out"
ENTRY_BRIDGE_IN = "bridge_in"
ENTRY_PHASE_COMPLETE = "phase_complete"
ENTRY_SESSION_END = "session_end"

VALID_ENTRY_TYPES: set[str] = {
    ENTRY_SYSTEM,
    ENTRY_MESSAGE,
    ENTRY_EDIT,
    ENTRY_DELETE,
    ENTRY_CHECKPOINT,
    ENTRY_COMPACT,
    ENTRY_TOOL_CALL,
    ENTRY_TOOL_RESULT,
    ENTRY_DIFF,
    ENTRY_REVIEW,
    ENTRY_BRIDGE_OUT,
    ENTRY_BRIDGE_IN,
    ENTRY_PHASE_COMPLETE,
    ENTRY_SESSION_END,
}

# ---------------------------------------------------------------------------
# LogEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogEntry:
    """A single entry in a persistent append-only log.

    Attributes:
        id: Globally unique entry identifier.
        type: Entry type (see VALID_ENTRY_TYPES).
        payload: Type-specific data dictionary.
        prev_id: Previous entry in this log (linked list). None for first entry.
        timestamp: Unix timestamp (float, UTC).
        log_owner: "think" or "do".
    """

    id: str
    type: str
    payload: dict[str, Any]
    prev_id: str | None
    timestamp: float
    log_owner: str

    def __post_init__(self) -> None:
        if self.type not in VALID_ENTRY_TYPES:
            raise ValueError(f"Invalid entry type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON encoding."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "prev_id": self.prev_id,
            "timestamp": self.timestamp,
            "log_owner": self.log_owner,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogEntry:
        """Deserialize from a plain dict."""
        return cls(
            id=data["id"],
            type=data["type"],
            payload=data.get("payload", {}),
            prev_id=data.get("prev_id"),
            timestamp=data["timestamp"],
            log_owner=data.get("log_owner", "unknown"),
        )


def new_entry_id(prefix: str = "le") -> str:
    """Generate a new globally unique entry ID."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def make_log_entry(
    type: str,
    payload: dict[str, Any],
    prev_id: str | None,
    log_owner: str,
    entry_id: str | None = None,
    timestamp: float | None = None,
) -> LogEntry:
    """Factory for creating a LogEntry with auto-generated ID and timestamp."""
    return LogEntry(
        id=entry_id or new_entry_id(),
        type=type,
        payload=payload,
        prev_id=prev_id,
        timestamp=timestamp if timestamp is not None else time.time(),
        log_owner=log_owner,
    )
