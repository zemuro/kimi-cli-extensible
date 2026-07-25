"""DoSession wraps ConsiliumSoul with git snapshotting and change journaling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from consilium.do.diff_computer import compute_unified_diff, is_binary_file
from consilium.do.git_snapshot import GitSnapshot
from consilium.do.journal import ChangeJournal
from consilium.do.plan_review import PlanReviewer, PlanReviewReport
from consilium.utils.logging import logger
from consilium.wire.types import PlanReviewEvent

if TYPE_CHECKING:
    from typing import Any, Literal

    from kosong.message import Message, ToolCall
    from kosong.tooling import ToolResult

    from consilium.soul.consiliumsoul import ConsiliumSoul

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
    """Wraps a ConsiliumSoul session with full versioning support.

    Responsibilities:
    - Git snapshotting (stash on start, pop on abort, commit on demand)
    - Change journaling (record every file-modifying tool call)
    - Blob storage (content-addressed baselines)

    Note on turn indices: The turn index is incremented inside ConsiliumSoul._turn()
    for every LLM invocation. This includes user-facing turns as well as internal
    turns such as context compaction. Turn indices are therefore coarse grouping
    keys rather than 1:1 mappings with chat turns.
    """

    def __init__(
        self,
        soul: ConsiliumSoul,
        work_dir: Path,
        seeded_from_think: bool = False,
        reviewer: PlanReviewer | None = None,
        plan_file: Path | None = None,
        phase: str | None = None,
    ) -> None:
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
        # Key: (turn_index, step_index, path) → baseline content (str for text, bytes for binary)
        self._baseline_cache: dict[tuple[int, int, str], str | bytes] = {}
        # Plan review gate state
        self._seeded_from_think = seeded_from_think
        self._reviewer = reviewer
        self._pending_review: Any | None = None
        self._state: Literal["idle", "running", "awaiting_review"] = "idle"
        if seeded_from_think and reviewer is not None:
            self.register_pre_run_hook()
        # Plan-driven orchestration (Phase 4d)
        self._plan_file = plan_file
        self._phase = phase
        self._plan: Any | None = None

    def _ensure_reviewer(self) -> PlanReviewer:
        """Lazy-create a PlanReviewer if one was not provided at init."""
        if self._reviewer is None:
            from consilium.config import DoConfig

            do_config = getattr(self.soul._runtime.config, "do", None)
            if do_config is None:
                do_config = DoConfig()
            self._reviewer = PlanReviewer(self.soul._runtime, do_config)
        return self._reviewer

    async def trigger_manual_review(self) -> PlanReviewReport:
        """Manually trigger a plan review (e.g. from /review slash command).

        Returns the review report.  Caller should set state and emit events.
        """
        plan_text = self._extract_plan_from_context()
        if not plan_text:
            raise RuntimeError("No plan found in context to review.")

        reviewer = self._ensure_reviewer()
        review = await reviewer.review(plan_text)
        self._pending_review = review
        self._state = "awaiting_review"
        self._emit_plan_review_event(review)

        # Phase 13: Write audit report to Think inbox
        do_config = getattr(self.soul._runtime.config, "do", None)
        if do_config and do_config.enable_reverse_bridge:
            think_id = getattr(self.soul._runtime.session.state, "paired_session_id", None)
            if think_id and self._phase:
                from consilium.think.inbox import write_report
                write_report(
                    think_session_id=think_id,
                    source_session_id=self.soul._runtime.session.id,
                    phase_id=self._phase,
                    report_type="audit",
                    content=review.model_dump_json(indent=2),
                )

        return review

    async def start(self) -> None:
        """Initialize Do session: git stash, create journal, archive old journals."""
        session_id = self.soul._runtime.session.id
        self.journal = ChangeJournal(session_id)

        git_state = self.git.start_session(session_id)
        self.journal.record_session_start(
            work_dir=str(self.work_dir),
            initial_git_head=git_state.head,
        )

        # Fire-and-forget archive of old journals
        do_config = getattr(self.soul._runtime.config, "do", None)
        retention_days = getattr(do_config, "journal_retention_days", 30)
        if not isinstance(retention_days, int):
            retention_days = 30
        if retention_days > 0:
            from consilium.do.journal import archive_old_journals
            try:
                archived = archive_old_journals(retention_days)
                if archived:
                    logger.info(
                        "Archived {count} old journal(s) to .archive/",
                        count=len(archived),
                    )
            except Exception:
                logger.exception("Failed to archive old journals")

        logger.info(
            "Do session started: {session_id}, git={git}",
            session_id=session_id,
            git=git_state.head or "N/A",
        )

        # Load plan document if --plan-file was provided
        if self._plan_file is not None:
            await self._load_plan_context()

    async def _load_plan_context(self) -> None:
        """Parse plan file and inject phase context into the soul."""
        from kosong.message import Message, TextPart

        from consilium.plan.docs_index import generate_docs_index
        from consilium.plan.parser import (
            is_plan_directory,
            parse_plan_directory_from_path,
            parse_plan_file,
        )

        # Detect directory-based vs single-file plan
        if is_plan_directory(self._plan_file):
            try:
                self._plan = parse_plan_directory_from_path(self._plan_file)
            except Exception as exc:
                logger.warning(
                    "Failed to parse plan directory {path}: {exc}",
                    path=self._plan_file,
                    exc=exc,
                )
                return
        else:
            try:
                self._plan = parse_plan_file(self._plan_file)
            except Exception as exc:
                logger.warning(
                    "Failed to parse plan file {path}: {exc}",
                    path=self._plan_file,
                    exc=exc,
                )
                return

        # Validate the requested phase exists
        target_phase = None
        if self._phase is not None:
            target_phase = self._plan.get_phase(self._phase)
            if target_phase is None:
                logger.warning(
                    "Phase {phase} not found in plan {plan}",
                    phase=self._phase,
                    plan=self._plan.metadata.plan_id,
                )
                return

        # Build context injection message
        lines: list[str] = []
        lines.append(f"# Plan: {self._plan.metadata.plan_id or 'Untitled'}")
        lines.append("")

        # For directory-based plans, include index overview if available
        if hasattr(self._plan, "index_path"):
            index_path = self._plan.index_path
            if index_path.exists():
                try:
                    index_text = index_path.read_text(encoding="utf-8")
                    # Strip frontmatter if present
                    from consilium.plan.parser import _parse_yaml_frontmatter
                    _, index_body = _parse_yaml_frontmatter(index_text)
                    # Include a brief summary: first few non-empty lines
                    index_lines = [line for line in index_body.splitlines() if line.strip()][:5]
                    if index_lines:
                        lines.append("## Plan Overview")
                        lines.extend(index_lines)
                        lines.append("")
                except Exception:
                    pass

        if target_phase is not None:
            lines.append(f"## Target Phase: {target_phase.phase_id} — {target_phase.title}")
            lines.append(f"**Status:** {target_phase.status.value}")
            if target_phase.files_involved:
                lines.append(f"**Files involved:** {', '.join(target_phase.files_involved)}")
            if target_phase.dependencies:
                lines.append(f"**Dependencies:** {', '.join(target_phase.dependencies)}")
            lines.append("")
            if target_phase.description:
                lines.append("### Description")
                lines.append(target_phase.description)
                lines.append("")
            if target_phase.acceptance_criteria:
                lines.append("### Acceptance Criteria")
                for criterion in target_phase.acceptance_criteria:
                    lines.append(f"- {criterion}")
                lines.append("")
            if target_phase.completion_criteria:
                lines.append("### Completion Criteria")
                for criterion in target_phase.completion_criteria:
                    lines.append(f"- {criterion}")
                lines.append("")

            # For directory-based plans, include the full phase file content
            if hasattr(self._plan, "get_phase_file"):
                phase_file = self._plan.get_phase_file(target_phase.phase_id)
                if phase_file.exists():
                    try:
                        phase_text = phase_file.read_text(encoding="utf-8")
                        lines.append("### Full Phase Document")
                        lines.append("```markdown")
                        lines.append(phase_text)
                        lines.append("```")
                        lines.append("")
                    except Exception:
                        pass

        # Load relevant docs from docs index
        readme_path = self.work_dir / "docs" / "README.md"
        if readme_path.exists() and target_phase is not None:
            try:
                docs_index = generate_docs_index(readme_path)
                relevant = docs_index.get_relevant_docs(target_phase.phase_id)
                if relevant:
                    lines.append("### Relevant Documentation")
                    for doc in relevant:
                        lines.append(f"- {doc.path}: {doc.purpose}")
                    lines.append("")
            except Exception:
                logger.exception("Failed to generate docs index")

        # Inject as system context message
        context_text = "\n".join(lines)
        await self.soul.context.append_message(
            Message(role="system", content=[TextPart(text=context_text)])
        )
        logger.info(
            "Injected plan context for {phase} from {plan}",
            phase=self._phase,
            plan=self._plan_file,
        )

        # Emit plan loaded event if wire is available
        from consilium.wire.types import PlanLoadedEvent

        if getattr(self.soul, "wire", None) is not None:
            event = PlanLoadedEvent(
                plan_id=self._plan.metadata.plan_id,
                phases=[p.model_dump() for p in self._plan.phases],
            )
            self.soul.wire.emit(event)

    # ------------------------------------------------------------------
    # Plan-review gate
    # ------------------------------------------------------------------

    def register_pre_run_hook(self) -> None:
        """Register the plan-review gate as a ConsiliumSoul pre-run hook."""
        self.soul.register_pre_run_hook(self._pre_run_hook)

    @property
    def state(self) -> str:
        """Return the current session state."""
        return self._state

    async def _pre_run_hook(self, user_message: Message) -> bool:
        """Pre-run hook that fires for Think-seeded sessions.

        Returns ``True`` to pause execution while the review is pending,
        ``False`` to allow the turn to proceed.
        """
        if not self._seeded_from_think:
            return False
        if self._state == "running":
            return False
        if self._state == "awaiting_review":
            return True

        plan_text = self._extract_plan_from_context()
        if not plan_text:
            return False

        logger.info("Plan-review gate: starting review")
        self._state = "awaiting_review"

        try:
            review = await self._reviewer.review(plan_text)
        except Exception:
            logger.exception("Plan-review gate failed; allowing execution")
            self._state = "running"
            return False

        self._pending_review = review
        self._emit_plan_review_event(review)
        return True

    def _extract_plan_from_context(self) -> str | None:
        """Search the soul's conversation context for the latest plan text.

        Looks for messages whose content starts with common plan markers,
        e.g. ``## Plan`` or ``# Implementation Plan``.
        """
        if not hasattr(self.soul, "context") or self.soul.context is None:
            return None
        ctx = self.soul.context
        messages = getattr(ctx, "messages", None)
        if messages is None:
            return None

        markers = ("## plan", "# implementation plan", "## implementation plan", "## action plan")
        for msg in reversed(messages):
            content = getattr(msg, "content", None) or ""
            text = self._extract_text_from_content(content)
            if text and any(text.lower().strip().startswith(m) for m in markers):
                return text.strip()
        return None

    @staticmethod
    def _extract_text_from_content(content: Any) -> str | None:
        """Extract plain text from a kosong Message content field."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            from kosong.message import TextPart

            parts = []
            for part in content:
                if isinstance(part, TextPart):
                    parts.append(part.text)
            return "".join(parts) if parts else None
        return None

    def _emit_plan_review_event(self, review: PlanReviewReport) -> None:
        """Emit a ``PlanReviewEvent`` onto the soul's wire stream."""
        session_id = self.soul._runtime.session.id
        event = PlanReviewEvent(
            session_id=session_id,
            feasible=review.feasible,
            risks=review.risks,
            recommendations=review.recommendations,
            questions=review.questions,
            summary=review.summary,
        )
        if self.soul.wire is not None:
            self.soul.wire.emit(event)

    async def approve_review(self) -> None:
        """Approve a pending plan review and allow execution to proceed."""
        if self._state != "awaiting_review":
            raise RuntimeError(f"Cannot approve review in state '{self._state}'")
        logger.info("Plan-review gate: approved")
        self._state = "running"

    async def reject_review(self, reason: str | None = None) -> None:
        """Reject a pending plan review and clear the gate."""
        if self._state != "awaiting_review":
            raise RuntimeError(f"Cannot reject review in state '{self._state}'")
        logger.info("Plan-review gate: rejected", reason=reason)
        self._state = "idle"
        self._pending_review = None

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
        elif is_binary_file(absolute_path):
            baseline = self._read_file_bytes_or_empty(absolute_path)
        else:
            baseline = self._read_file_or_empty(absolute_path)

        cache_key = (self.soul._current_turn_index, self._current_step_index, str(path))
        self._baseline_cache[cache_key] = baseline

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
        is_binary = False
        if tool_name == "delete_file":
            post_content = ""
        elif is_binary_file(absolute_path):
            is_binary = True
            post_content = self._read_file_bytes_or_empty(absolute_path)
            if isinstance(baseline_content, str):
                baseline_content = b""
        else:
            post_content = self._read_file_or_empty(absolute_path)
            if isinstance(baseline_content, bytes):
                baseline_content = ""

        if not is_binary:
            unified_diff = compute_unified_diff(baseline_content, post_content, str(path))
            if not unified_diff:
                return  # No actual change
        else:
            # For binary files, skip unified diff but still record if content changed
            if baseline_content == post_content:
                return  # No actual change
            unified_diff = ""

        entry = self.journal.record_diff(
            turn_index=self.soul._current_turn_index,
            step_index=self._current_step_index,
            tool_call_id=tool_result.tool_call_id or "",
            tool_name=tool_name,
            path=str(path),
            baseline_content=baseline_content,
            post_content=post_content,
            unified_diff=unified_diff,
            is_binary=is_binary,
        )

        # Notify extension via wire protocol (best-effort; wire may not be set in tests)
        from consilium.soul import get_wire_or_none
        from consilium.wire.types import ToolFileModifiedEvent

        wire = get_wire_or_none()
        if wire is not None:
            wire.soul_side.send(ToolFileModifiedEvent(
                entry_id=entry.id,
                turn_index=entry.turn_index,
                step_index=entry.step_index,
                tool_call_id=entry.tool_call_id,
                tool_name=entry.tool_name,
                path=entry.path,
                baseline_hash=entry.baseline_hash,
                post_hash=entry.post_hash,
                lines_added=entry.lines_added,
                lines_removed=entry.lines_removed,
            ))

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

    def _read_file_bytes_or_empty(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except (FileNotFoundError, OSError):
            return b""
