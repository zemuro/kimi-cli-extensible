---
phase_id: phase-03
title: 3: Do Mode — Git Snapshotting, Change Journal & Web API
status: implemented
dependencies:
  - phase-02
files_involved:
  - src/kimi_cli/do/
  - src/kimi_cli/do/session.py
  - src/kimi_cli/do/journal.py
---

**Goal:** Immutable-history agent loop with full versioning backend: git safety net, content-addressed blob store, turn-scoped change journal with unified diffs, and HTTP API for the VS Code: extension.

**Design Decision:** Backend owns all versioning state. The extension renders it. This enables:
- Cross-client consistency (CLI, web, extension all see same state)
- Git as the session-level safety net
- Content-addressed deduplication
- Turn-scoped undo granularity

---

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (kimi-cli Python)                           │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │ GitSnapshot  │    │ ChangeJournal│    │ BlobStore    │    │ Web API  │  │
│  │ (stash/pop)  │    │ (JSONL)      │    │ (SHA256)     │    │ (Fastify)│  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘  │
│         │                   │                   │                  │        │
│         └───────────────────┴───────────────────┘                  │        │
│                             │                                      │        │
│                             ▼                                      ▼        │
│                    ┌─────────────────┐                    ┌─────────────┐   │
│                    │ KimiSoul hooks  │                    │ VS Code:    │   │
│                    │ (post-tool)     │                    │ Extension   │   │
│                    └─────────────────┘                    └─────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 Module: Git Snapshotting

**File:** `src/kimi_cli/do/git_snapshot.py`

```python
"""Git snapshotting for Do mode session safety."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kimi_cli.utils.logging import logger


@dataclass(frozen=True, slots=True)
class GitState:
    is_repo: bool
    head: str | None
    has_uncommitted_changes: bool
    has_untracked_files: bool
    branch: str | None


class GitSnapshotError(Exception):
    """Git operation failed."""


class GitSnapshot:
    """Manage git snapshots for a Do mode session.

    Responsibilities:
    - Detect if cwd is a git repo
    - Stash dirty tree on session start (preserving untracked files)
    - Pop stash on session abort
    - Create user-triggered intermediate commits
    - Report git status
    """

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self._is_repo = self._check_repo()
        self._initial_stash: str | None = None
        self._intermediate_commits: list[str] = []

    # ── Detection ──

    def _check_repo(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=self.cwd,
            capture_output=True,
        )
        return result.returncode == 0

    @property
    def is_repo(self) -> bool:
        return self._is_repo

    # ── State ──

    def capture_state(self) -> GitState:
        if not self._is_repo:
            return GitState(
                is_repo=False,
                head=None,
                has_uncommitted_changes=False,
                has_untracked_files=False,
                branch=None,
            )

        head = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
            ).stdout.strip()
            or None
        )

        branch = (
            subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
            ).stdout.strip()
            or None
        )

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        ).stdout.strip()

        has_changes = False
        has_untracked = False
        for line in status.split("\n"):
            if not line:
                continue
            status_code = line[:2]
            if status_code != "??":
                has_changes = True
            else:
                has_untracked = True

        return GitState(
            is_repo=True,
            head=head,
            has_uncommitted_changes=has_changes,
            has_untracked_files=has_untracked,
            branch=branch,
        )

    # ── Stash ──

    def stash(self, message: str, include_untracked: bool = False) -> str | None:
        """Stash current changes. Returns stash ref (e.g., 'stash@{0}') or None.

        Args:
            message: Stash message for identification.
            include_untracked: If True, also stash untracked files.
                WARNING: Only set to True with explicit user confirmation.
        """
        if not self._is_repo:
            return None

        cmd = ["git", "stash", "push", "-m", message]
        if include_untracked:
            cmd.append("--include-untracked")

        result = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if result.returncode != 0:
            raise GitSnapshotError(f"git stash failed: {result.stderr}")

        # Get the most recent stash ref
        list_result = subprocess.run(
            ["git", "stash", "list", "--format=%gd"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )
        stash_ref = list_result.stdout.strip().split("\n")[0] if list_result.stdout else None
        logger.info("Git stash created: {stash_ref}", stash_ref=stash_ref)
        return stash_ref

    def pop(self, stash_ref: str | None = None) -> bool:
        """Pop a stash. Returns True if successful."""
        if not self._is_repo:
            return False

        cmd = ["git", "stash", "pop"]
        if stash_ref:
            cmd.append(stash_ref)

        result = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Git stash pop failed: {stderr}", stderr=result.stderr)
            return False

        logger.info("Git stash popped: {stash_ref}", stash_ref=stash_ref)
        return True

    # ── Commit ──

    def commit(self, message: str) -> str | None:
        """Create a commit with all current changes. Returns commit hash or None."""
        if not self._is_repo:
            return None

        # Stage all tracked changes (NOT untracked — user must add those manually)
        add_result = subprocess.run(
            ["git", "add", "-u"],  # -u = update tracked files only
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )
        if add_result.returncode != 0:
            raise GitSnapshotError(f"git add failed: {add_result.stderr}")

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            # Nothing to commit is OK
            if "nothing to commit" in commit_result.stdout:
                return None
            raise GitSnapshotError(f"git commit failed: {commit_result.stderr}")

        # Get the new commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )
        commit_hash = hash_result.stdout.strip()
        self._intermediate_commits.append(commit_hash)
        logger.info("Git commit created: {hash}", hash=commit_hash)
        return commit_hash

    # ── Session lifecycle ──

    def start_session(self, session_id: str) -> GitState:
        """Call at Do mode session start. Stashes dirty tree if needed."""
        state = self.capture_state()
        if not state.is_repo:
            logger.warning("Not a git repo — no snapshotting available")
            return state

        if state.has_uncommitted_changes:
            self._initial_stash = self.stash(
                f"kimi-do-{session_id}-init",
                include_untracked=False,
            )
            logger.info(
                "Stashed uncommitted changes for session {session_id}",
                session_id=session_id,
            )

        if state.has_untracked_files:
            logger.warning(
                "Untracked files detected but NOT stashed. "
                "They will be left as-is during the session."
            )

        return state

    def abort_session(self) -> bool:
        """Call on session abort. Reverts to initial state."""
        if self._initial_stash:
            ok = self.pop(self._initial_stash)
            if ok:
                logger.info("Session aborted — reverted to initial state")
            else:
                logger.error("Session abort failed — manual git cleanup may be needed")
            return ok
        return True

    def checkpoint(self, message: str) -> str | None:
        """User-triggered intermediate commit."""
        return self.commit(message)

    # ── Status ──

    def status(self) -> dict[str, str]:
        """Human-readable git status for UI display."""
        state = self.capture_state()
        if not state.is_repo:
            return {"status": "not_a_repo"}

        return {
            "status": "ok",
            "head": state.head or "unknown",
            "branch": state.branch or "unknown",
            "dirty": "yes" if state.has_uncommitted_changes else "no",
            "initial_stash": self._initial_stash or "none",
            "intermediate_commits": str(len(self._intermediate_commits)),
        }
```

---

### 3.3 Module: Blob Store

**File:** `src/kimi_cli/do/blob_store.py`

Content-addressed storage for file baselines. Used by both the change journal and the extension.

```python
"""Content-addressed blob store for file snapshots.

Layout:
    ~/.kimi/blobs/
    ├── ab/
    │   └── cdef1234...  (full sha256 filename)
    └── 12/
        └── 3456abcd...  (full sha256 filename)

Storage format: raw file bytes, no compression.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BLOB_DIR = Path.home() / ".kimi" / "blobs"


def _blob_path(content_hash: str) -> Path:
    prefix = content_hash[:2]
    return BLOB_DIR / prefix / content_hash


def store(content: bytes | str) -> str:
    """Store content and return its SHA256 hash."""
    if isinstance(content, str):
        content = content.encode("utf-8")

    content_hash = hashlib.sha256(content).hexdigest()
    path = _blob_path(content_hash)

    if path.exists():
        return content_hash  # deduplication

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content_hash


def retrieve(content_hash: str) -> bytes | None:
    """Retrieve content by hash. Returns None if not found."""
    path = _blob_path(content_hash)
    if not path.exists():
        return None
    return path.read_bytes()


def retrieve_text(content_hash: str) -> str | None:
    """Retrieve content as UTF-8 text."""
    data = retrieve(content_hash)
    return data.decode("utf-8") if data is not None else None


def exists(content_hash: str) -> bool:
    return _blob_path(content_hash).exists()
```

---

### 3.4 Module: Change Journal

**File:** `src/kimi_cli/do/journal.py`

The journal is the single source of truth for all agent-made changes. It records metadata AND the unified diff for each file-modifying tool call.

```python
"""Change journal for Do mode — turn-scoped versioning metadata.

Storage:
    ~/.kimi/do_sessions/{session_id}/
    ├── journal.jsonl      # Append-only metadata entries
    └── diffs/
        └── {turn_index}-{step_index}-{entry_id}.patch  # Unified diff files

Journal entry format (JSONL):
    {"type": "session_start", "session_id": "...", "timestamp": "..."}
    {"type": "diff", "id": "...", "turn_index": 3, "step_index": 2, ...}
    {"type": "review", "diff_id": "...", "hunk_id": "...", "accepted": true, ...}
    {"type": "checkpoint", "commit_hash": "abc123", "message": "...", ...}
    {"type": "session_end", "reason": "abort|commit|normal", ...}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from kimi_cli.do.blob_store import store

JOURNAL_DIR = Path.home() / ".kimi" / "do_sessions"


@dataclass(slots=True)
class JournalEntry:
    """Base journal entry. Use subclasses for specific types."""

    id: str = field(default_factory=lambda: f"je_{uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
    unified_diff: str = ""  # unified diff text
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


class ChangeJournal:
    """Append-only change journal for a Do mode session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._journal_dir = JOURNAL_DIR / session_id
        self._journal_file = self._journal_dir / "journal.jsonl"
        self._diffs_dir = self._journal_dir / "diffs"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._diffs_dir.mkdir(parents=True, exist_ok=True)

    def _append(self, entry: JournalEntry) -> None:
        """Append a single entry to the journal file."""
        data = asdict(entry)
        # Remove None values for compactness
        data = {k: v for k, v in data.items() if v is not None}
        with open(self._journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, separators=(",", ":")) + "\n")

    # ── Public API ──

    def record_session_start(self, work_dir: str, initial_git_head: str | None) -> None:
        self._append(SessionStartEntry(
            session_id=self.session_id,
            work_dir=work_dir,
            initial_git_head=initial_git_head,
        ))

    def record_diff(
        self,
        turn_index: int,
        step_index: int,
        tool_call_id: str,
        tool_name: str,
        path: str,
        baseline_content: str,
        post_content: str,
        unified_diff: str,
    ) -> DiffEntry:
        """Record a file-modifying tool call.

        Stores baseline and post content in the blob store, then records
        metadata in the journal.
        """
        baseline_hash = store(baseline_content)
        post_hash = store(post_content)

        # Store unified diff in separate file for readability
        diff_filename = f"{turn_index:04d}-{step_index:04d}-{uuid4().hex[:8]}.patch"
        diff_path = self._diffs_dir / diff_filename
        diff_path.write_text(unified_diff, encoding="utf-8")

        # Count lines
        lines_added = unified_diff.count("\n+") - unified_diff.count("\n+++")
        lines_removed = unified_diff.count("\n-") - unified_diff.count("\n---")

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
            unified_diff=diff_filename,  # reference to file, not inline
            lines_added=max(0, lines_added),
            lines_removed=max(0, lines_removed),
        )
        self._append(entry)
        return entry

    def record_review(self, diff_id: str, accepted: bool, hunk_id: str | None = None) -> None:
        self._append(ReviewEntry(
            diff_id=diff_id,
            hunk_id=hunk_id,
            accepted=accepted,
        ))

    def record_checkpoint(self, commit_hash: str, message: str) -> None:
        self._append(CheckpointEntry(
            commit_hash=commit_hash,
            message=message,
        ))

    def record_session_end(self, reason: Literal["normal", "abort", "checkpoint", "error"]) -> None:
        self._append(SessionEndEntry(reason=reason))

    # ── Queries ──

    def get_entries(self, entry_type: str | None = None) -> list[dict]:
        """Read all (or filtered) entries from the journal."""
        entries: list[dict] = []
        if not self._journal_file.exists():
            return entries

        with open(self._journal_file, "r", encoding="utf-8") as f:
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

    @classmethod
    def _infer_operation(cls, tool_name: str) -> Literal["write", "edit", "delete", "create", "append", "other"]:
        return cls._TOOL_OPERATION_MAP.get(tool_name, "other")
```

---

### 3.5 Module: Unified Diff Computer

**File:** `src/kimi_cli/do/diff_computer.py`

```python
"""Compute unified diffs between two text contents."""

from __future__ import annotations

import difflib


def compute_unified_diff(
    baseline: str,
    current: str,
    path: str = "file",
    context_lines: int = 3,
) -> str:
    """Compute a unified diff between baseline and current content.

    Args:
        baseline: Pre-edit content.
        current: Post-edit content.
        path: File path for diff headers.
        context_lines: Number of context lines around changes.

    Returns:
        Unified diff text, or empty string if no changes.
    """
    baseline_lines = baseline.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)

    # Ensure all lines end with newline for clean diff
    if baseline_lines and not baseline_lines[-1].endswith("\n"):
        baseline_lines[-1] += "\n"
    if current_lines and not current_lines[-1].endswith("\n"):
        current_lines[-1] += "\n"

    diff = difflib.unified_diff(
        baseline_lines,
        current_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )

    return "".join(diff)
```

---

### 3.6 Module: Do Session Wrapper

**File:** `src/kimi_cli/do/session.py`

```python
"""DoSession wraps KimiSoul with git snapshotting and change journaling."""

from __future__ import annotations

from pathlib import Path

from kimi_cli.do.journal import ChangeJournal, DiffEntry
from kimi_cli.do.diff_computer import compute_unified_diff
from kimi_cli.do.git_snapshot import GitSnapshot
from kimi_cli.utils.logging import logger

# Tools that modify files (must match extension's FILE_TOOLS set)
FILE_MODIFYING_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "create_file",
    "delete_file",
    "append_file",
    "str_replace_file",
    "patch_file",
})


class DoSession:
    """Wraps a KimiSoul session with full versioning support.

    Responsibilities:
    - Git snapshotting (stash on start, pop on abort, commit on demand)
    - Change journaling (record every file-modifying tool call)
    - Blob storage (content-addressed baselines)
    - Wire protocol enhancements (notify extension of file changes)
    """

    async def start(self) -> None:
        """Initialize Do session: git stash, create journal."""
        session_id = self.soul._runtime.session.id
        self.journal = ChangeJournal(session_id)

        git_state = self.git.start_session(session_id)
        self.journal.record_session_start(
            work_dir=str(self.work_dir),
            initial_git_head=git_state.head,
        )

        logger.info(
            "Do session started: {session_id}, git={git}",
            session_id=session_id,
            git=git_state.head or "N/A",
        )

    def __init__(self, soul: KimiSoul, work_dir: Path) -> None:
        self.soul = soul
        self.work_dir = work_dir
        self.git = GitSnapshot(work_dir)
        self.journal: ChangeJournal | None = None
        # Track the last seen turn index to detect turn boundaries
        self._last_seen_turn_index: int = 0
        # Step index resets to 0 at each turn boundary, increments for each
        # file-modifying tool within the turn.
        self._current_step_index: int = 0
        # Cache of file baselines captured BEFORE tool execution.
        # Key: (turn_index, step_index, path) → baseline content
        self._baseline_cache: dict[tuple[int, int, str], str] = {}

    async def start(self) -> None:
        """Initialize Do session: git stash, create journal."""
        session_id = self.soul._runtime.session.id
        self.journal = ChangeJournal(session_id)

        git_state = self.git.start_session(session_id)
        self.journal.record_session_start(
            work_dir=str(self.work_dir),
            initial_git_head=git_state.head,
        )

        logger.info(
            "Do session started: {session_id}, git={git}",
            session_id=session_id,
            git=git_state.head or "N/A",
        )

    def _ensure_turn_sync(self) -> None:
        """Detect turn boundary and reset step index if turn changed."""
        soul_turn = self.soul._current_turn_index
        if soul_turn != self._last_seen_turn_index:
            self._last_seen_turn_index = soul_turn
            self._current_step_index = 0

    async def capture_baseline(self, tool_call: ToolCall) -> None:
        """Capture the pre-edit baseline for a file-modifying tool call.

        This MUST be called BEFORE the tool executes (via pre_tool_hook).
        It reads the current file content from disk and stores it in the
        baseline cache keyed by (turn_index, step_index, path).
        """
        self._ensure_turn_sync()

        path = self._extract_path_from_tool_call(tool_call)
        if not path:
            return

        tool_name = tool_call.function.name
        if tool_name not in FILE_MODIFYING_TOOLS:
            return

        absolute_path = self.work_dir / path
        if tool_name == "delete_file":
            baseline = self._read_file_or_empty(absolute_path)
        elif not absolute_path.exists():
            # New file — baseline is empty string
            baseline = ""
        else:
            baseline = self._read_file_or_empty(absolute_path)

        self._baseline_cache[(self.soul._current_turn_index, self._current_step_index, str(path))] = baseline

    async def on_tool_result(self, tool_call: ToolCall, tool_result: ToolResult) -> None:
        """Hook called after each tool execution.

        If the tool modified a file, record the change in the journal.
        """
        self._ensure_turn_sync()

        if self.journal is None:
            return

        tool_name = tool_call.function.name
        if tool_name not in FILE_MODIFYING_TOOLS:
            return

        # Extract file path from tool arguments
        path = self._extract_path_from_tool_call(tool_call)
        if not path:
            return

        cache_key = (self.soul._current_turn_index, self._current_step_index, str(path))
        baseline_content = self._baseline_cache.pop(cache_key, "")

        absolute_path = self.work_dir / path
        if tool_name == "delete_file":
            post_content = ""
        else:
            post_content = self._read_file_or_empty(absolute_path)

        unified_diff = compute_unified_diff(baseline_content, post_content, str(path))
        if not unified_diff:
            return  # No actual change

        self.journal.record_diff(
            turn_index=self.soul._current_turn_index,
            step_index=self._current_step_index,
            tool_call_id=tool_result.tool_call_id or "",
            tool_name=tool_name,
            path=str(path),
            baseline_content=baseline_content,
            post_content=post_content,
            unified_diff=unified_diff,
        )

        self._current_step_index += 1

    async def commit(self, message: str) -> str | None:
        """User-triggered intermediate commit."""
        commit_hash = self.git.checkpoint(message)
        if commit_hash and self.journal:
            self.journal.record_checkpoint(commit_hash, message)
        return commit_hash

    async def abort(self) -> bool:
        """Abort session: revert to initial git state."""
        if self.journal:
            self.journal.record_session_end(reason="abort")
        return self.git.abort_session()

    async def end(self, reason: str = "normal") -> None:
        """End session gracefully."""
        if self.journal:
            self.journal.record_session_end(reason=reason)  # type: ignore[arg-type]

    # ── Helpers ──

    def _extract_path_from_tool_call(self, tool_call: ToolCall) -> Path | None:
        """Extract relative file path from tool call arguments."""
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            return None

        path_str = args.get("path") or args.get("file_path") or args.get("filename")
        if not path_str:
            return None

        path = Path(path_str)
        # Make relative to work_dir if absolute
        if path.is_absolute():
            try:
                path = path.relative_to(self.work_dir)
            except ValueError:
                return path  # outside work_dir
        return path

    def _read_file_or_empty(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            return ""

    # Wire protocol notification deferred to Phase 5.
    # See scratch/frontend/inline_diff_implementation_plan.md for the extension contract.
```

> **Note on turn indices:** `KimiSoul._turn()` increments `_current_turn_index` for *every* turn, including context compaction, system prompt rewrites, and background tasks. The journal's turn indices are therefore grouping keys, not 1:1 mappings with user-visible chat turns. The extension (Phase 5) must not assume turn indices align with chat messages.

---

### 3.7 Hooking Into KimiSoul

**File:** `src/kimi_cli/soul/kimisoul.py` — modifications

We add a minimal, additive hook mechanism to `KimiSoul`. The hook receives **both** the `ToolCall` and the `ToolResult`, so the consumer can access tool name, arguments, and return value.

```python
# In KimiSoul.__init__(), add:
self._current_turn_index: int = 0
self._pre_tool_hooks: list[Callable[[ToolCall], Awaitable[None]]] = []
self._post_tool_hooks: list[Callable[[ToolCall, ToolResult], Awaitable[None]]] = []

# Add public methods:
def register_pre_tool_hook(self, hook: Callable[[ToolCall], Awaitable[None]]) -> None:
    """Register a callback to be called BEFORE each tool execution.

    Used to capture pre-edit file baselines for change journaling.
    Exceptions in hooks are logged but do not fail the tool execution.
    """
    self._pre_tool_hooks.append(hook)

def register_post_tool_hook(self, hook: Callable[[ToolCall, ToolResult], Awaitable[None]]) -> None:
    """Register a callback to be called AFTER each tool execution.

    The hook receives the original ToolCall (with function name and arguments)
    and the resulting ToolResult. Exceptions in hooks are logged but do not
    fail the tool execution.
    """
    self._post_tool_hooks.append(hook)

# In _agent_loop(), BEFORE executing tools:
# After tool calls are parsed from the LLM response:
for hook in self._pre_tool_hooks:
    for tool_call in tool_calls:
        try:
            await hook(tool_call)
        except Exception:
            logger.exception(
                "Pre-tool hook failed for {tool}",
                tool=tool_call.function.name,
            )

# In _agent_loop(), AFTER tool results are collected (around line 1197):
# After: results = await result.tool_results()
# The tool_calls are available from the agent state.
for hook in self._post_tool_hooks:
    for tool_call, tool_result in zip(tool_calls, results):
        try:
            await hook(tool_call, tool_result)
        except Exception:
            logger.exception(
                "Post-tool hook failed for {tool}",
                tool=tool_call.function.name,
            )

# In _turn(), increment turn counter at the start:
self._current_turn_index += 1
```

**File:** `src/kimi_cli/do/registry.py` — new module

Module-level registry for DoSession instances, avoiding dynamic attributes on Runtime:

```python
"""Module-level registry for active Do mode sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.do.session import DoSession

_DO_SESSIONS: dict[str, DoSession] = {}


def register_do_session(session_id: str, do_session: DoSession) -> None:
    _DO_SESSIONS[session_id] = do_session


def get_do_session(session_id: str) -> DoSession | None:
    return _DO_SESSIONS.get(session_id)


def unregister_do_session(session_id: str) -> None:
    _DO_SESSIONS.pop(session_id, None)
```

**File:** `src/kimi_cli/app.py` — modifications in `KimiCLI.create()`

After creating the `KimiSoul`, wrap it with `DoSession` when in Do mode:

```python
# After: soul = KimiSoul(agent, context=context)
if do_mode:
    from pathlib import Path
    from kimi_cli.do.registry import register_do_session
    from kimi_cli.do.session import DoSession

    do_session = DoSession(soul, work_dir=Path(session.work_dir))
    await do_session.start()

    # Register hooks
    soul.register_pre_tool_hook(do_session.capture_baseline)
    soul.register_post_tool_hook(do_session.on_tool_result)

    # Register for slash command lookup
    register_do_session(session.id, do_session)
```

---

### 3.8 Slash Commands for Do Mode

**File:** `src/kimi_cli/ui/shell/slash.py` — additions

```python
from kimi_cli.wire import wire_send
from kimi_cli.wire.types import TextPart
from kimi_cli.do.registry import get_do_session, unregister_do_session


@slash_command("/commit")
async def slash_commit(soul: KimiSoul, args: str) -> None:
    """Create an intermediate git commit with the current changes."""
    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    message = args.strip() or f"kimi-do checkpoint at turn {soul._current_turn_index}"
    commit_hash = await do_session.commit(message)
    if commit_hash:
        wire_send(TextPart(text=f"Committed: {commit_hash} — {message}"))
    else:
        wire_send(TextPart(text="Nothing to commit."))


@slash_command("/abort")
async def slash_abort(soul: KimiSoul, args: str) -> None:
    """Abort the session and revert to the initial git state."""
    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    wire_send(TextPart(text="Aborting session and reverting changes..."))
    ok = await do_session.abort()
    if ok:
        wire_send(TextPart(text="Reverted to initial state. Session ended."))
    else:
        wire_send(TextPart(text="Abort failed. Check git status manually."))

    unregister_do_session(soul._runtime.session.id)
    raise SessionAborted()


@slash_command("/status")
async def slash_status(soul: KimiSoul, args: str) -> None:
    """Show current git status and session versioning info."""
    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    git_status = do_session.git.status()
    lines = ["[Do Mode Status]"]
    for key, value in git_status.items():
        lines.append(f"  {key}: {value}")

    if do_session.journal:
        diffs = do_session.journal.get_entries("diff")
        lines.append(f"  changes_recorded: {len(diffs)}")

    wire_send(TextPart(text="\n".join(lines)))


class SessionAborted(Exception):
    """Raised when user aborts a Do session."""
```

> **Note on registry cleanup:** `/abort` calls `unregister_do_session()`, but normal exit (`/exit`, EOF) does not. For a single-session CLI process this is harmless. If session reload (`/new`, `Reload` exception) is supported without process restart, add cleanup in `KimiCLI` shutdown or a `SessionEnd` hook.

**File:** `src/kimi_cli/ui/shell/__init__.py` — or wherever `Shell.run_soul_command()` is defined

Add `SessionAborted` to the exception handling in the soul command runner:

```python
# In Shell.run_soul_command() (around the try/except block):
try:
    # ... existing execution ...
except SessionAborted:
    # Graceful exit — user explicitly aborted the Do session
    self._exit_after_run = True
    return
except LLMNotSet:
    # ... existing handlers ...
```

---

### 3.9 Web API Endpoints

**Status: DEFERRED to Phase 5.**

These endpoints are needed for the VS Code: extension frontend, but the extension integration happens in Phase 5. For Phase 3, the journal is written to disk and can be read directly by local consumers.

When implemented in Phase 5, add to `src/kimi_cli/web/api/sessions.py`:
- `GET /{session_id}/changes` — query journal entries
- `GET /{session_id}/baselines/{content_hash}` — retrieve blob content
- `GET /{session_id}/turns/{turn_index}/summary` — aggregated turn stats

See the original plan (git history) for the full endpoint implementations.

---

### 3.10 Wire Protocol Extension

**Status: DEFERRED to Phase 5.**

The `ToolFileModifiedEvent` wire message is needed to notify the VS Code: extension of file changes in real time. For Phase 3, the extension can poll the journal file or use the existing `FileChangesUpdated` event.

When implemented in Phase 5:
1. Define `ToolFileModifiedEvent(BaseModel)` in `src/kimi_cli/wire/types.py`
2. Ensure it's included in the `WireMessage` union type
3. Send it directly via `wire_send(ToolFileModifiedEvent(...))` (NOT wrapped in `ContentPart`)
4. Handle it in the extension's chat handler

---

### 3.11 Config Additions

**File:** `src/kimi_cli/config.py`

```python
class DoConfig(BaseModel):
    default_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    auto_git_snapshot: bool = Field(
        default=True,
        description="Automatically stash uncommitted changes on Do mode start",
    )
    max_iterations: int = Field(default=50, ge=1)
    enable_change_journal: bool = Field(
        default=True,
        description="Record all file-modifying tool calls in the change journal",
    )
    journal_include_diffs: bool = Field(
        default=True,
        description="Store unified diffs in the journal (increases storage)",
    )
```

---

### 3.12 Testing Requirements

| Test | File | Description |
|------|------|-------------|
| `test_git_snapshot_detects_repo` | `tests/core/test_git_snapshot.py` | Detect git repo vs non-repo |
| `test_git_snapshot_stash_and_pop` | `tests/core/test_git_snapshot.py` | Full stash/pop cycle in temp repo |
| `test_git_snapshot_commit` | `tests/core/test_git_snapshot.py` | Create commit, verify hash |
| `test_git_snapshot_start_session_stashes_dirty` | `tests/core/test_git_snapshot.py` | `start_session()` stashes dirty tree |
| `test_git_snapshot_abort_pops_stash` | `tests/core/test_git_snapshot.py` | `abort_session()` pops stash |
| `test_blob_store_roundtrip` | `tests/core/test_blob_store.py` | Store and retrieve by hash |
| `test_blob_store_deduplication` | `tests/core/test_blob_store.py` | Same content → same hash, no duplicate file |
| `test_journal_append_and_read` | `tests/core/test_journal.py` | Write entries, read back |
| `test_journal_record_diff` | `tests/core/test_journal.py` | Record diff, verify metadata |
| `test_journal_get_diffs_for_path` | `tests/core/test_journal.py` | Query by path |
| `test_journal_get_diffs_since_turn` | `tests/core/test_journal.py` | Query by turn index |
| `test_diff_computer_unified_diff` | `tests/core/test_diff_computer.py` | Compute diff, verify format |
| `test_diff_computer_no_change` | `tests/core/test_diff_computer.py` | Identical content → empty diff |
| `test_do_session_start_creates_journal` | `tests/core/test_do_session.py` | Start session, journal exists |
| `test_do_session_capture_baseline_and_record_diff` | `tests/core/test_do_session.py` | Pre-tool baseline + post-tool diff roundtrip |
| `test_do_session_abort_reverts_git` | `tests/core/test_do_session.py` | Abort resets to initial git state |
| `test_do_session_commit_creates_checkpoint` | `tests/core/test_do_session.py` | Commit records checkpoint in journal |

---
