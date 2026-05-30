"""Think → Do bridge: export Think history to the outbox."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.think.models import ThinkSession

OUTBOX_DIR = Path.home() / ".kimi" / "think_outbox"


def export_to_outbox(session: ThinkSession) -> Path:
    """Export active Think messages to the outbox for Do-mode seeding.

    Returns the path to the exported file.
    """
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

    active_messages = [
        msg for msg in session.messages
        if not msg.deleted and msg.role in ("user", "assistant")
    ]

    payload = {
        "source_session_id": session.id,
        "exported_at": time.time(),
        "messages": [
            {"role": msg.role, "content": msg.content}
            for msg in active_messages
        ],
    }

    out_path = OUTBOX_DIR / f"{session.id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_outbox(session_id: str) -> list[dict[str, str]] | None:
    """Load messages from the outbox for a given session ID.

    Returns the message list or None if no outbox file exists.
    """
    path = OUTBOX_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("messages")


def clear_outbox(session_id: str) -> None:
    """Remove the outbox file for a given session ID."""
    path = OUTBOX_DIR / f"{session_id}.json"
    path.unlink(missing_ok=True)
