"""Peer status file I/O for Think + Do process coordination.

Two independent CLI processes on the same workDir read/write a shared JSON file
to discover each other's existence and state. No daemon, no socket server —
just advisory status sharing via atomic writes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from consilium.utils.io import atomic_json_write
from consilium.utils.logging import logger


@dataclass(slots=True)
class PeerStatus:
    """Status of a single peer process."""

    session_id: str
    pid: int
    mode: str  # "think" | "do"
    status: str  # "idle" | "working" | "awaiting_review" | "stopped"
    updated_at: float


@dataclass(slots=True)
class PeerStatusFile:
    """Combined status for both peers on a workDir."""

    think: PeerStatus | None = None
    do: PeerStatus | None = None


def _is_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        # Fallback without psutil
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False


def _status_file_path(sessions_dir: Path) -> Path:
    return sessions_dir / ".peer-status.json"


def read_peer_status(sessions_dir: Path) -> PeerStatusFile:
    """Read peer status from disk. Returns empty if file missing or corrupt.

    Stale entries (dead PIDs) are automatically removed.
    """
    path = _status_file_path(sessions_dir)
    if not path.exists():
        return PeerStatusFile()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        peer = PeerStatusFile(
            think=PeerStatus(**data["think"]) if data.get("think") else None,
            do=PeerStatus(**data["do"]) if data.get("do") else None,
        )
        # Filter stale entries
        changed = False
        if peer.think and not _is_alive(peer.think.pid):
            peer.think = None
            changed = True
        if peer.do and not _is_alive(peer.do.pid):
            peer.do = None
            changed = True
        if changed:
            write_peer_status(sessions_dir, peer)
        return peer
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Corrupt peer status file, resetting: {path}", path=path)
        return PeerStatusFile()


def write_peer_status(sessions_dir: Path, status: PeerStatusFile) -> None:
    """Atomically write peer status to disk."""
    path = _status_file_path(sessions_dir)
    payload: dict[str, dict[str, object] | None] = {}
    if status.think:
        payload["think"] = asdict(status.think)
    if status.do:
        payload["do"] = asdict(status.do)
    atomic_json_write(payload, path)


def update_own_peer_status(
    sessions_dir: Path,
    session_id: str,
    mode: str,
    status: str,
) -> None:
    """Update this process's entry in the peer status file."""
    peer = read_peer_status(sessions_dir)
    entry = PeerStatus(
        session_id=session_id,
        pid=os.getpid(),
        mode=mode,
        status=status,
        updated_at=time.time(),
    )
    if mode == "think":
        peer.think = entry
    else:
        peer.do = entry
    write_peer_status(sessions_dir, peer)


def clear_own_peer_status(sessions_dir: Path, mode: str) -> None:
    """Remove this process's entry on clean shutdown."""
    peer = read_peer_status(sessions_dir)
    if mode == "think":
        peer.think = None
    else:
        peer.do = None
    write_peer_status(sessions_dir, peer)
