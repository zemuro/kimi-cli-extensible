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
            if "nothing to commit" in commit_result.stdout or "nothing to commit" in commit_result.stderr:
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
