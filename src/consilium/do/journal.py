"""Change journal for Do mode — turn-scoped versioning metadata.

Storage:
    ~/.consilium/do_sessions/{session_id}/
    ├── journal.jsonl      # Append-only metadata entries
    └── diffs/
        └── {turn_index:04d}-{step_index:04d}-{entry_id}.patch  # Unified diff files

Journal entry format (JSONL):
    {"type": "session_start", "session_id": "...", "timestamp": "..."}
    {"type": "diff", "id": "...", "turn_index": 3, "step_index": 2, ...}
    {"type": "review", "diff_id": "...", "hunk_id": "...", "accepted": true, ...}
    {"type": "checkpoint", "commit_hash": "abc123", "message": "...", ...}
    {"type": "session_end", "reason": "abort|commit|normal", ...}
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from consilium.do.blob_store import store

JOURNAL_DIR = Path.home() / ".consilium" / "do_sessions"
DO_LOGS_DIR = Path.home() / ".consilium" / "do_logs"


@dataclass(slots=True)
class JournalEntry:
    """Base journal entry. Use subclasses for specific types."""

    id: str = field(default_factory=lambda: f"je_{uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    type: str = "unknown"


@dataclass(slots=True)
class SessionStartEntry(JournalEntry):
    session_id: str = ""
    work_dir: str = ""
    initial_git_head: str | None = None
    type: str = "session_start"


@dataclass(slots=True)
class DiffEntry(JournalEntry):
    """A single file-modifying tool call."""

    session_id: str = ""
    turn_index: int = 0
    step_index: int = 0
    tool_call_id: str = ""
    tool_name: str = ""
    path: str = ""  # relative path
    operation: Literal["write", "edit", "delete", "create", "append", "other"] = "other"
    baseline_hash: str = ""  # SHA256 of pre-edit content
    post_hash: str = ""  # SHA256 of post-edit content
    is_binary: bool = False
    unified_diff: str = ""  # filename reference, not inline text (empty for binaries)
    size_before: int = 0
    size_after: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    type: str = "diff"


@dataclass(slots=True)
class ReviewEntry(JournalEntry):
    """User review decision for a hunk or entire diff."""

    diff_id: str = ""
    hunk_id: str | None = None  # None = entire diff
    accepted: bool = True
    type: str = "review"


@dataclass(slots=True)
class CheckpointEntry(JournalEntry):
    commit_hash: str = ""
    message: str = ""
    type: str = "checkpoint"


@dataclass(slots=True)
class SessionEndEntry(JournalEntry):
    reason: Literal["normal", "abort", "checkpoint", "error"] = "normal"
    type: str = "session_end"


@dataclass(slots=True)
class PhaseCompleteEntry(JournalEntry):
    """A phase was marked as complete in Do mode."""

    phase_id: str = ""
    report_path: str = ""
    type: str = "phase_complete"


class ChangeJournal:
    """Append-only change journal for a Do mode session."""

    # Mapping from exact tool names to operation types.
    # Add new tools here as they are introduced.
    _TOOL_OPERATION_MAP: dict[str, Literal["write", "edit", "delete", "create", "append", "other"]] = {
        "WriteFile": "write",
        "CreateFile": "create",
        "StrReplaceFile": "edit",
        "PatchFile": "edit",
        "DeleteFile": "delete",
        "AppendFile": "append",
        "write_file": "write",
        "edit_file": "edit",
        "create_file": "create",
        "delete_file": "delete",
        "append_file": "append",
        "str_replace_file": "edit",
        "patch_file": "edit",
    }

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._journal_dir = JOURNAL_DIR / session_id
        self._journal_file = self._journal_dir / "journal.jsonl"
        self._diffs_dir = self._journal_dir / "diffs"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._diffs_dir.mkdir(parents=True, exist_ok=True)
        # Phase 6a: lazy-init persistent log
        self._persistent_log = None

    def _get_persistent_log(self):
        """Get or create the persistent Do log."""
        if self._persistent_log is None:
            from consilium.plan.persistent_log import PersistentLog

            path = DO_LOGS_DIR / f"{self.session_id}.jsonl"
            self._persistent_log = PersistentLog(path, log_owner="do")
        return self._persistent_log

    def _append(self, entry: JournalEntry) -> None:
        """Append a single entry to the journal file."""
        data = asdict(entry)
        # Remove None values for compactness
        data = {k: v for k, v in data.items() if v is not None}
        with open(self._journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, separators=(",", ":")) + "\n")

    def _append_to_persistent_log(self, type: str, payload: dict) -> None:
        """Phase 6a: also append to the persistent Do log."""
        try:
            log = self._get_persistent_log()
            from consilium.plan.log_entry import make_log_entry

            log.append(
                make_log_entry(
                    type=type,
                    payload=payload,
                    prev_id=log.tail_id(),
                    log_owner="do",
                )
            )
        except Exception:
            # Parallel logging is best-effort in Phase 6a
            pass

    # ── Public API ──

    def record_session_start(self, work_dir: str, initial_git_head: str | None) -> None:
        self._append(SessionStartEntry(
            session_id=self.session_id,
            work_dir=work_dir,
            initial_git_head=initial_git_head,
        ))
        self._append_to_persistent_log(
            "checkpoint",
            {"label": "session_start", "work_dir": work_dir, "initial_git_head": initial_git_head},
        )

    def record_diff(
        self,
        turn_index: int,
        step_index: int,
        tool_call_id: str,
        tool_name: str,
        path: str,
        baseline_content: str | bytes,
        post_content: str | bytes,
        unified_diff: str,
        is_binary: bool = False,
    ) -> DiffEntry:
        """Record a file-modifying tool call.

        Stores baseline and post content in the blob store, then records
        metadata in the journal.
        """
        baseline_hash = store(baseline_content)
        post_hash = store(post_content)

        if is_binary:
            # No unified diff for binary files
            diff_filename = ""
            lines_added = 0
            lines_removed = 0
        else:
            # Store unified diff in separate file for readability
            diff_filename = f"{turn_index:04d}-{step_index:04d}-{uuid4().hex[:8]}.patch"
            diff_path = self._diffs_dir / diff_filename
            diff_path.write_text(unified_diff, encoding="utf-8")

            # Count lines
            diff_lines = unified_diff.splitlines()
            lines_added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
            lines_removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

        entry = DiffEntry(
            session_id=self.session_id,
            turn_index=turn_index,
            step_index=step_index,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            path=path,
            operation=self._infer_operation(tool_name),
            baseline_hash=baseline_hash,
            post_hash=post_hash,
            is_binary=is_binary,
            unified_diff=diff_filename,  # reference to file, not inline
            size_before=len(baseline_content) if isinstance(baseline_content, bytes) else len(baseline_content.encode("utf-8")),
            size_after=len(post_content) if isinstance(post_content, bytes) else len(post_content.encode("utf-8")),
            lines_added=max(0, lines_added),
            lines_removed=max(0, lines_removed),
        )
        self._append(entry)
        self._append_to_persistent_log(
            "diff",
            {
                "turn_index": entry.turn_index,
                "step_index": entry.step_index,
                "tool_call_id": entry.tool_call_id,
                "tool_name": entry.tool_name,
                "path": entry.path,
                "operation": entry.operation,
                "baseline_hash": entry.baseline_hash,
                "post_hash": entry.post_hash,
                "is_binary": entry.is_binary,
                "lines_added": entry.lines_added,
                "lines_removed": entry.lines_removed,
            },
        )
        return entry

    def record_review(self, diff_id: str, accepted: bool, hunk_id: str | None = None) -> None:
        self._append(ReviewEntry(
            diff_id=diff_id,
            hunk_id=hunk_id,
            accepted=accepted,
        ))
        self._append_to_persistent_log(
            "review",
            {"diff_id": diff_id, "hunk_id": hunk_id, "accepted": accepted},
        )

    def record_checkpoint(self, commit_hash: str, message: str) -> None:
        self._append(CheckpointEntry(
            commit_hash=commit_hash,
            message=message,
        ))
        self._append_to_persistent_log(
            "checkpoint",
            {"label": "git_checkpoint", "commit_hash": commit_hash, "message": message},
        )

    def record_session_end(self, reason: Literal["normal", "abort", "checkpoint", "error"]) -> None:
        self._append(SessionEndEntry(reason=reason))
        self._append_to_persistent_log(
            "session_end",
            {"reason": reason},
        )

    def record_phase_complete(self, phase_id: str, report_path: str) -> None:
        """Record that a phase was marked complete."""
        self._append(PhaseCompleteEntry(phase_id=phase_id, report_path=report_path))
        self._append_to_persistent_log(
            "phase_complete",
            {"phase_id": phase_id, "report_path": report_path},
        )

    # ── Queries ──

    def get_entries(self, entry_type: str | None = None) -> list[dict]:
        """Read all (or filtered) entries from the journal."""
        entries: list[dict] = []
        if not self._journal_file.exists():
            return entries

        with open(self._journal_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if entry_type is None or data.get("type") == entry_type:
                    entries.append(data)
        return entries

    def get_diffs_for_path(self, path: str) -> list[dict]:
        """Get all diff entries for a specific file path."""
        return [e for e in self.get_entries("diff") if e.get("path") == path]

    def get_diffs_since_turn(self, turn_index: int) -> list[dict]:
        """Get all diff entries from a given turn onwards."""
        return [e for e in self.get_entries("diff") if e.get("turn_index", 0) >= turn_index]

    def get_turn_summary(self, turn_index: int) -> dict:
        """Get summary of changes for a specific turn."""
        diffs = [e for e in self.get_entries("diff") if e.get("turn_index") == turn_index]
        return {
            "turn_index": turn_index,
            "files_changed": len({d["path"] for d in diffs}),
            "total_additions": sum(d.get("lines_added", 0) for d in diffs),
            "total_deletions": sum(d.get("lines_removed", 0) for d in diffs),
            "diffs": diffs,
        }

    def get_unified_diff(self, diff_entry: dict) -> str | None:
        """Retrieve the unified diff text for a diff entry."""
        diff_filename = diff_entry.get("unified_diff")
        if not diff_filename:
            return None
        diff_path = self._diffs_dir / diff_filename
        if not diff_path.exists():
            return None
        return diff_path.read_text(encoding="utf-8")

    @classmethod
    def _infer_operation(cls, tool_name: str) -> Literal["write", "edit", "delete", "create", "append", "other"]:
        return cls._TOOL_OPERATION_MAP.get(tool_name, "other")


# ── Retention / archiving ──

def archive_old_journals(max_age_days: int = 30) -> list[Path]:
    """Move journal directories older than *max_age_days* to the archive.

    Returns a list of archived directory paths.
    """
    if max_age_days <= 0:
        return []

    archive_dir = JOURNAL_DIR / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    cutoff = time.time() - (max_age_days * 86400)
    archived: list[Path] = []

    for entry in JOURNAL_DIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == ".archive":
            continue

        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue

        if mtime < cutoff:
            dest = archive_dir / entry.name
            # If destination exists, append a counter
            counter = 1
            original_dest = dest
            while dest.exists():
                dest = Path(f"{original_dest}-{counter}")
                counter += 1
            try:
                entry.rename(dest)
                archived.append(dest)
            except OSError:
                continue

    return archived
