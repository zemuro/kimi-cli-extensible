"""JSONL storage for Think mode sessions and checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

from consilium.think.models import ThinkMessage, ThinkSession
from consilium.utils.timestamp import parse_timestamp

THINK_DIR = Path.home() / ".consilium" / "think_sessions"
THINK_LOGS_DIR = Path.home() / ".consilium" / "think_logs"


def think_path(session_id: str) -> Path:
    return THINK_DIR / f"{session_id}.jsonl"


# Backwards-compatible alias
_think_path = think_path


def _checkpoint_dir(session_id: str) -> Path:
    return THINK_DIR / session_id / "checkpoints"


def _think_log_path(session_id: str) -> Path:
    return THINK_LOGS_DIR / f"{session_id}.jsonl"


def _get_think_log(session_id: str):
    """Get or create the persistent log for a Think session."""
    from consilium.plan.persistent_log import PersistentLog

    return PersistentLog(_think_log_path(session_id), log_owner="think")


def save_session(session: ThinkSession) -> None:
    """Save a ThinkSession to JSONL.

    Phase 6a: Also writes to the persistent think_log (parallel logging).
    """
    path = _think_path(session.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for msg in session.messages:
            data = {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "tokens_in": msg.tokens_in,
                "tokens_out": msg.tokens_out,
                "deleted": msg.deleted,
                "edited_at": msg.edited_at if msg.edited_at else None,
            }
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    # Phase 6a: parallel logging — write a checkpoint entry to the persistent log
    try:
        log = _get_think_log(session.id)
        from consilium.plan.log_entry import make_log_entry

        log.append(
            make_log_entry(
                type="checkpoint",
                payload={
                    "label": "session_save",
                    "message_count": len(session.messages),
                    "session_id": session.id,
                },
                prev_id=log.tail_id(),
                log_owner="think",
            )
        )
    except Exception:
        # Parallel logging is best-effort in Phase 6a
        pass


def load_session(session_id: str) -> ThinkSession | None:
    """Load a ThinkSession from JSONL."""
    path = _think_path(session_id)
    if not path.exists():
        return None
    messages: list[ThinkMessage] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            messages.append(
                ThinkMessage(
                    id=data["id"],
                    role=data["role"],
                    content=data["content"],
                    timestamp=parse_timestamp(data["timestamp"]),
                    tokens_in=data.get("tokens_in"),
                    tokens_out=data.get("tokens_out"),
                    deleted=data.get("deleted", False),
                    edited_at=parse_timestamp(data["edited_at"]) if data.get("edited_at") else None,
                )
            )
    return ThinkSession(id=session_id, messages=messages)


def list_sessions() -> list[tuple[str, float]]:
    """Return (session_id, modified_time) for all think sessions."""
    sessions: list[tuple[str, float]] = []
    if not THINK_DIR.exists():
        return sessions
    for path in THINK_DIR.glob("*.jsonl"):
        stat = path.stat()
        sessions.append((path.stem, stat.st_mtime))
    return sorted(sessions, key=lambda x: x[1], reverse=True)


def save_checkpoint(session: ThinkSession, name: str) -> Path:
    """Save a full ThinkSession snapshot as a checkpoint."""
    checkpoint_dir = _checkpoint_dir(session.id)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = checkpoint_dir / f"{name}.json"
    data = {
        "id": session.id,
        "created_at": session.created_at,
        "checkpoint_name": name,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "tokens_in": msg.tokens_in,
                "tokens_out": msg.tokens_out,
                "deleted": msg.deleted,
                "edited_at": msg.edited_at if msg.edited_at else None,
            }
            for msg in session.messages
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Phase 6a: parallel logging
    try:
        log = _get_think_log(session.id)
        from consilium.plan.log_entry import make_log_entry

        log.append(
            make_log_entry(
                type="checkpoint",
                payload={
                    "label": f"checkpoint:{name}",
                    "checkpoint_name": name,
                    "message_count": len(session.messages),
                    "session_id": session.id,
                },
                prev_id=log.tail_id(),
                log_owner="think",
            )
        )
    except Exception:
        pass

    return path


def load_checkpoint(session_id: str, name: str) -> ThinkSession | None:
    """Load a ThinkSession from a checkpoint."""
    path = _checkpoint_dir(session_id) / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = [
        ThinkMessage(
            id=msg["id"],
            role=msg["role"],
            content=msg["content"],
            timestamp=parse_timestamp(msg["timestamp"]),
            tokens_in=msg.get("tokens_in"),
            tokens_out=msg.get("tokens_out"),
            deleted=msg.get("deleted", False),
            edited_at=parse_timestamp(msg["edited_at"]) if msg.get("edited_at") else None,
        )
        for msg in data["messages"]
    ]
    return ThinkSession(
        id=data["id"],
        created_at=parse_timestamp(data["created_at"]),
        messages=messages,
        checkpoint_name=name,
    )


def list_checkpoints(session_id: str) -> list[str]:
    """List checkpoint names for a session."""
    checkpoint_dir = _checkpoint_dir(session_id)
    if not checkpoint_dir.exists():
        return []
    return sorted(p.stem for p in checkpoint_dir.glob("*.json"))
