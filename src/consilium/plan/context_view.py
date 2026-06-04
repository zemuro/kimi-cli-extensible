"""Materialized views over persistent logs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from consilium.plan.log_entry import LogEntry
from consilium.plan.persistent_log import PersistentLog


class ContextView:
    """An ephemeral materialized slice of a persistent log.

    Resolves edits, deletes, and compactions into a coherent message stream.
    Results are cached until the underlying log grows.
    """

    def __init__(
        self,
        log: PersistentLog,
        start_id: str | None = None,
        end_id: str | None = None,
        use_compacts: bool = True,
    ) -> None:
        self.log = log
        self.start_id = start_id
        self.end_id = end_id
        self.use_compacts = use_compacts
        self._cached_messages: list[dict[str, Any]] | None = None
        self._cache_tail: str | None = None

    # ── Public API ──

    def materialize(self) -> list[dict[str, Any]]:
        """Walk the log slice and resolve edits/deletes/compacts.

        Returns a list of message dicts with keys: role, content, entry_id.
        """
        if (
            self._cached_messages is not None
            and self._cache_tail == self.log.tail_id()
        ):
            return list(self._cached_messages)

        messages: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        edited: dict[str, str] = {}  # target_id → new_content
        deleted: set[str] = set()
        compacted_ids: set[str] = set()
        preserved_after_compact: set[str] = set()

        # First pass: collect edits, deletes, compacts
        for entry in self._walk():
            if entry.type == "edit":
                edited[entry.payload["target_id"]] = entry.payload.get(
                    "new_content", ""
                )
            elif entry.type == "delete":
                deleted.add(entry.payload["target_id"])
            elif entry.type == "compact" and self.use_compacts:
                compacted_ids.update(seen_ids)
                for preserved_id in entry.payload.get("preserved_ids", []):
                    preserved_after_compact.add(preserved_id)
                    compacted_ids.discard(preserved_id)
            elif entry.type == "message":
                seen_ids.add(entry.payload.get("target_id", entry.id))

        # Second pass: materialize messages, applying edits retroactively
        seen_ids.clear()
        for entry in self._walk():
            if entry.type == "message":
                target_id = entry.payload.get("target_id", entry.id)
                if target_id in deleted:
                    continue
                if target_id in seen_ids:
                    continue
                # If this message was compacted and not preserved, skip
                if target_id in compacted_ids and target_id not in preserved_after_compact:
                    continue
                content = edited.get(target_id, entry.payload.get("content", ""))
                messages.append({
                    "role": entry.payload.get("role", "unknown"),
                    "content": content,
                    "entry_id": target_id,
                })
                seen_ids.add(target_id)
            elif entry.type == "compact" and self.use_compacts:
                # Insert summary as a system message
                messages.append({
                    "role": "system",
                    "content": f"[Compacted] {entry.payload.get('summary', '')}",
                    "entry_id": entry.id,
                })
                # Add preserved messages that were compacted
                for preserved_id in entry.payload.get("preserved_ids", []):
                    preserved = self.log.get_entry(preserved_id)
                    if preserved and preserved.type == "message":
                        pid = preserved.payload.get("target_id", preserved.id)
                        if pid not in deleted and pid not in seen_ids:
                            content = edited.get(pid, preserved.payload.get("content", ""))
                            messages.append({
                                "role": preserved.payload.get("role", "unknown"),
                                "content": content,
                                "entry_id": pid,
                            })
                            seen_ids.add(pid)

        self._cached_messages = messages
        self._cache_tail = self.log.tail_id()
        return list(messages)

    def fork_at(self, entry_id: str) -> ContextView:
        """Create a new view starting at entry_id (inclusive)."""
        return ContextView(
            self.log,
            start_id=entry_id,
            end_id=self.end_id,
            use_compacts=self.use_compacts,
        )

    def invalidate_cache(self) -> None:
        """Force re-materialization on next call."""
        self._cached_messages = None
        self._cache_tail = None

    # ── Private ──

    def _walk(self) -> Iterator[LogEntry]:
        """Iterate entries from start to end (inclusive)."""
        entries = self.log.all_entries()
        if not entries:
            return

        start_idx = 0
        if self.start_id is not None:
            start_idx = self.log._id_index.get(self.start_id, 0)

        end_idx = len(entries) - 1
        if self.end_id is not None:
            end_idx = self.log._id_index.get(self.end_id, len(entries) - 1)

        for idx in range(start_idx, end_idx + 1):
            yield entries[idx]
