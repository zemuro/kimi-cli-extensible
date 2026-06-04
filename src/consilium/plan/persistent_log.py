"""Persistent append-only log with in-memory indices."""

from __future__ import annotations

import json
from pathlib import Path

from consilium.plan.log_entry import LogEntry


class PersistentLog:
    """Append-only log with in-memory indices.

    Each log is owned by exactly one mode ("think" or "do").
    Entries are hash-linked via prev_id. Indices are rebuilt on load.
    """

    def __init__(self, path: Path, log_owner: str = "unknown") -> None:
        self.path = path
        self.log_owner = log_owner
        self._entries: list[LogEntry] = []
        self._id_index: dict[str, int] = {}  # entry_id → list index
        self._type_index: dict[str, list[str]] = {}  # type → entry_ids
        self._checkpoint_index: dict[str, str] = {}  # label → entry_id
        self._tail_id: str | None = None
        self._load()

    @classmethod
    def for_session(cls, session_id: str, log_owner: str) -> PersistentLog:
        """Load a persistent log for a given session."""
        log_dir = Path.home() / ".consilium" / f"{log_owner}_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return cls(log_dir / f"{session_id}.jsonl", log_owner=log_owner)

    # ── Public API ──

    def append(self, entry: LogEntry) -> None:
        """Append an entry. Validate prev_id links and log_owner."""
        if entry.log_owner != self.log_owner:
            raise ValueError(
                f"Entry log_owner mismatch: {entry.log_owner} != {self.log_owner}"
            )
        if self._tail_id is not None and entry.prev_id != self._tail_id:
            raise ValueError(
                f"prev_id mismatch: {entry.prev_id} != {self._tail_id}"
            )
        if entry.id in self._id_index:
            raise ValueError(f"Duplicate entry id: {entry.id}")

        self._entries.append(entry)
        idx = len(self._entries) - 1
        self._id_index[entry.id] = idx
        self._type_index.setdefault(entry.type, []).append(entry.id)
        if entry.type == "checkpoint":
            label = entry.payload.get("label")
            if label:
                self._checkpoint_index[str(label)] = entry.id
        self._tail_id = entry.id
        self._append_to_disk(entry)

    def get_entry(self, entry_id: str) -> LogEntry | None:
        """Look up an entry by its ID."""
        idx = self._id_index.get(entry_id)
        return self._entries[idx] if idx is not None else None

    def find_entries_by_type(
        self,
        entry_type: str,
        after_id: str | None = None,
    ) -> list[LogEntry]:
        """All entries of a given type, optionally after a specific entry."""
        ids = self._type_index.get(entry_type, [])
        if not ids:
            return []

        if after_id is None:
            return [self._entries[self._id_index[eid]] for eid in ids]

        after_idx = self._id_index.get(after_id)
        if after_idx is None:
            return []

        result = []
        for eid in ids:
            idx = self._id_index[eid]
            if idx > after_idx:
                result.append(self._entries[idx])
        return result

    def find_checkpoint(self, label: str) -> LogEntry | None:
        """Find a checkpoint entry by its label."""
        entry_id = self._checkpoint_index.get(label)
        return self.get_entry(entry_id) if entry_id else None

    def tail_id(self) -> str | None:
        """Return the ID of the last entry in the log."""
        return self._tail_id

    def all_entries(self) -> list[LogEntry]:
        """Return all entries in order."""
        return list(self._entries)

    def entry_count(self) -> int:
        """Return the total number of entries."""
        return len(self._entries)

    # ── Private ──

    def _load(self) -> None:
        """Load from disk on init and build indices."""
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = LogEntry.from_dict(data)
                # Skip validation during load (prev_id chain may reference
                # entries loaded earlier in the same file)
                self._load_entry(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    def _load_entry(self, entry: LogEntry) -> None:
        """Insert an entry into memory structures without disk write."""
        self._entries.append(entry)
        idx = len(self._entries) - 1
        self._id_index[entry.id] = idx
        self._type_index.setdefault(entry.type, []).append(entry.id)
        if entry.type == "checkpoint":
            label = entry.payload.get("label")
            if label:
                self._checkpoint_index[str(label)] = entry.id
        self._tail_id = entry.id

    def _append_to_disk(self, entry: LogEntry) -> None:
        """Append a single entry to the JSONL file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
