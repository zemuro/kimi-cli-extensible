"""Tests for DoSession."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from kosong.message import Message

from consilium.do.plan_review import PlanReviewer, PlanReviewReport
from consilium.do.registry import get_do_session, register_do_session, unregister_do_session
from consilium.do.session import DoSession


class MockToolCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments
        self.id = "tc_123"


class MockToolResult:
    def __init__(self) -> None:
        self.tool_call_id = "tc_123"


@pytest.fixture
def mock_soul() -> MagicMock:
    soul = MagicMock()
    soul._runtime.session.id = "test-session-id"
    soul._current_turn_index = 1
    return soul


@pytest.fixture
def do_session(mock_soul: MagicMock, tmp_path: Path) -> DoSession:
    # Create a temp git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path, check=True, capture_output=True,
    )

    return DoSession(mock_soul, work_dir=tmp_path)


@pytest.mark.asyncio
async def test_do_session_start_creates_journal(do_session: DoSession) -> None:
    await do_session.start()
    assert do_session.journal is not None
    entries = do_session.journal.get_entries("session_start")
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_do_session_capture_baseline_and_record_diff(do_session: DoSession, tmp_path: Path) -> None:
    await do_session.start()

    file_path = tmp_path / "test.py"
    file_path.write_text("original\n")

    tool_call = MockToolCall("write_file", json.dumps({"path": "test.py", "content": "modified\n"}))
    await do_session.capture_baseline(tool_call)

    # Modify the file
    file_path.write_text("modified\n")

    tool_result = MockToolResult()
    await do_session.on_tool_result(tool_call, tool_result)

    diffs = do_session.journal.get_entries("diff")
    assert len(diffs) == 1
    assert diffs[0]["path"] == "test.py"
    assert diffs[0]["tool_name"] == "write_file"


@pytest.mark.asyncio
async def test_do_session_abort_reverts_git(do_session: DoSession, tmp_path: Path) -> None:
    import subprocess

    # Commit a file
    file_path = tmp_path / "a.txt"
    file_path.write_text("original")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    # Modify it
    file_path.write_text("changed")

    await do_session.start()
    assert do_session.git._initial_stash is not None

    ok = await do_session.abort()
    assert ok is True
    assert file_path.read_text() == "changed"  # pre-session dirty state restored


@pytest.mark.asyncio
async def test_do_session_commit_creates_checkpoint(do_session: DoSession, tmp_path: Path) -> None:
    import subprocess

    file_path = tmp_path / "a.txt"
    file_path.write_text("original")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    await do_session.start()

    # Modify and commit via DoSession
    file_path.write_text("changed")
    commit_hash = await do_session.commit("test checkpoint")
    assert commit_hash is not None

    checkpoints = do_session.journal.get_entries("checkpoint")
    assert len(checkpoints) == 1
    assert checkpoints[0]["commit_hash"] == commit_hash


def test_registry() -> None:
    mock = MagicMock()
    register_do_session("sess-1", mock)
    assert get_do_session("sess-1") is mock
    unregister_do_session("sess-1")
    assert get_do_session("sess-1") is None



# ---------------------------------------------------------------------------
# Plan-review gate tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_reviewer() -> MagicMock:
    reviewer = MagicMock(spec=PlanReviewer)
    reviewer.review = AsyncMock()
    return reviewer


def _make_seeded_session(mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock | None = None) -> DoSession:
    """Helper to create a DoSession seeded from Think with an optional reviewer."""
    return DoSession(mock_soul, work_dir=tmp_path, seeded_from_think=True, reviewer=mock_reviewer)


@pytest.mark.asyncio
async def test_plan_review_gate_non_seeded_returns_false(mock_soul: MagicMock, tmp_path: Path) -> None:
    """For non-seeded sessions the pre-run hook should always return False."""
    session = DoSession(mock_soul, work_dir=tmp_path, seeded_from_think=False)
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)
    assert result is False
    assert session.state == "idle"


@pytest.mark.asyncio
async def test_plan_review_gate_no_plan_returns_false(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """If no plan text is found in context, the hook returns False."""
    mock_soul.context = MagicMock()
    mock_soul.context.messages = []
    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)
    assert result is False
    assert session.state == "idle"


@pytest.mark.asyncio
async def test_plan_review_gate_finds_plan_and_pauses(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """When a plan is present, the hook spawns review and pauses execution."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X\n2. Do Y")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()

    report = PlanReviewReport(
        feasible=True,
        risks=["risk1"],
        recommendations=["rec1"],
        questions=["q1"],
        summary="Looks good",
    )
    mock_reviewer.review.return_value = report

    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)

    assert result is True
    assert session.state == "awaiting_review"
    assert session._pending_review is report
    mock_reviewer.review.assert_awaited_once_with("## Plan\n1. Do X\n2. Do Y")
    mock_soul.wire.emit.assert_called_once()
    emitted = mock_soul.wire.emit.call_args[0][0]
    assert emitted.type == "plan_review"
    assert emitted.feasible is True


@pytest.mark.asyncio
async def test_plan_review_approve_transitions_to_running(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """Approving a pending review transitions state to 'running'."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()

    mock_reviewer.review.return_value = PlanReviewReport(
        feasible=True, risks=[], recommendations=[], questions=[], summary="ok",
    )

    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    msg = Message(role="user", content="hello")
    await session._pre_run_hook(msg)
    assert session.state == "awaiting_review"

    await session.approve_review()
    assert session.state == "running"


@pytest.mark.asyncio
async def test_plan_review_reject_transitions_to_idle(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """Rejecting a pending review transitions state to 'idle' and clears report."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()

    mock_reviewer.review.return_value = PlanReviewReport(
        feasible=False, risks=[], recommendations=[], questions=[], summary="bad",
    )

    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    msg = Message(role="user", content="hello")
    await session._pre_run_hook(msg)
    assert session.state == "awaiting_review"

    await session.reject_review("Too risky")
    assert session.state == "idle"
    assert session._pending_review is None


@pytest.mark.asyncio
async def test_plan_review_running_state_short_circuits(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """If state is already 'running', the hook returns False immediately."""
    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    session._state = "running"
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)
    assert result is False
    mock_reviewer.review.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_review_awaiting_state_returns_true(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """If state is 'awaiting_review', the hook returns True without re-spawning review."""
    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    session._state = "awaiting_review"
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)
    assert result is True
    mock_reviewer.review.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_review_review_failure_allows_execution(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """If the reviewer raises an exception, the gate logs and allows execution."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()

    mock_reviewer.review.side_effect = RuntimeError("LLM down")

    session = _make_seeded_session(mock_soul, tmp_path, mock_reviewer)
    msg = Message(role="user", content="hello")
    result = await session._pre_run_hook(msg)

    assert result is False
    assert session.state == "running"


def test_approve_review_raises_when_not_awaiting(mock_soul: MagicMock, tmp_path: Path) -> None:
    """approve_review raises RuntimeError if not in awaiting_review state."""
    session = DoSession(mock_soul, work_dir=tmp_path)
    with pytest.raises(RuntimeError, match="Cannot approve review"):
        import asyncio
        asyncio.run(session.approve_review())


def test_reject_review_raises_when_not_awaiting(mock_soul: MagicMock, tmp_path: Path) -> None:
    """reject_review raises RuntimeError if not in awaiting_review state."""
    session = DoSession(mock_soul, work_dir=tmp_path)
    with pytest.raises(RuntimeError, match="Cannot reject review"):
        import asyncio
        asyncio.run(session.reject_review())



# ---------------------------------------------------------------------------
# Phase 7: /review slash command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_manual_review_no_plan_raises(mock_soul: MagicMock, tmp_path: Path) -> None:
    """trigger_manual_review raises RuntimeError when no plan is in context."""
    mock_soul.context = MagicMock()
    mock_soul.context.messages = []
    session = DoSession(mock_soul, work_dir=tmp_path)
    with pytest.raises(RuntimeError, match="No plan found"):
        await session.trigger_manual_review()


@pytest.mark.asyncio
async def test_trigger_manual_review_creates_lazy_reviewer(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """trigger_manual_review lazily creates a reviewer, runs review, and sets state."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()
    mock_soul._runtime.config.do.plan_review.enabled = True

    report = PlanReviewReport(
        feasible=True,
        risks=["risk1"],
        recommendations=["rec1"],
        questions=["q1"],
        summary="Looks good",
    )
    mock_reviewer.review.return_value = report

    # Patch PlanReviewer so lazy creation returns our mock
    monkeypatch.setattr(
        "consilium.do.session.PlanReviewer", lambda _rt, _cfg: mock_reviewer
    )

    # DoSession with NO reviewer — lazy creation
    session = DoSession(mock_soul, work_dir=tmp_path)
    assert session._reviewer is None

    result = await session.trigger_manual_review()

    assert session._reviewer is mock_reviewer
    assert result is report
    assert session.state == "awaiting_review"
    assert session._pending_review is report
    mock_reviewer.review.assert_awaited_once_with("## Plan\n1. Do X")


@pytest.mark.asyncio
async def test_ensure_reviewer_reuses_existing(
    mock_soul: MagicMock, tmp_path: Path, mock_reviewer: MagicMock
) -> None:
    """_ensure_reviewer does not recreate if a reviewer is already present."""
    plan_msg = Message(role="assistant", content="## Plan\n1. Do X")
    mock_soul.context = MagicMock()
    mock_soul.context.messages = [plan_msg]
    mock_soul.wire = MagicMock()
    mock_soul._runtime.config.do.plan_review.enabled = True

    report = PlanReviewReport(
        feasible=True, risks=[], recommendations=[], questions=[], summary="ok",
    )
    mock_reviewer.review.return_value = report

    # Pre-seed the reviewer
    session = DoSession(mock_soul, work_dir=tmp_path, reviewer=mock_reviewer)
    assert session._reviewer is mock_reviewer

    reviewer_2 = session._ensure_reviewer()
    assert reviewer_2 is mock_reviewer


# ---------------------------------------------------------------------------
# Phase 8: Directory-based plan loading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_plan_context_single_file(
    mock_soul: MagicMock, tmp_path: Path
) -> None:
    """_load_plan_context parses a single-file plan and injects it."""

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("""# Plan

**plan_id:** test-plan
**created:** 2026-05-24

## Phase 1: First
### Description
Do the first thing.

### Acceptance Criteria
- [x] Done
""", encoding="utf-8")

    mock_soul.context = MagicMock()
    mock_soul.context.append_message = AsyncMock()
    session = DoSession(mock_soul, work_dir=tmp_path, plan_file=plan_file, phase="phase-1")
    await session._load_plan_context()

    assert session._plan is not None
    assert session._plan.metadata.plan_id == "test-plan"
    call_args = mock_soul.context.append_message.call_args[0][0]
    text = call_args.content[0].text
    assert "Plan: test-plan" in text
    assert "Target Phase: phase-1" in text
    assert "Do the first thing" in text


@pytest.mark.asyncio
async def test_load_plan_context_directory(
    mock_soul: MagicMock, tmp_path: Path
) -> None:
    """_load_plan_context parses a directory-based plan and injects target phase."""

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "index.md").write_text("""---
plan_id: dir-plan
---
# Plan Overview
This is the overview.
""", encoding="utf-8")
    (plan_dir / "phase-01.md").write_text("""---
title: "First Phase"
status: pending
files_involved:
  - src/main.py
dependencies: []
---
### Description
Do the first thing.

### Acceptance Criteria
- Create main.py
""", encoding="utf-8")
    (plan_dir / "phase-02.md").write_text("""---
title: "Second Phase"
status: pending
---
Do the second thing.
""", encoding="utf-8")

    mock_soul.context = MagicMock()
    mock_soul.context.append_message = AsyncMock()
    session = DoSession(mock_soul, work_dir=tmp_path, plan_file=plan_dir, phase="phase-01")
    await session._load_plan_context()

    assert session._plan is not None
    assert session._plan.metadata.plan_id == "dir-plan"
    call_args = mock_soul.context.append_message.call_args[0][0]
    text = call_args.content[0].text
    assert "Plan: dir-plan" in text
    assert "Target Phase: phase-01" in text
    assert "Do the first thing" in text
    # Should include full phase document for directory plans
    assert "Full Phase Document" in text


@pytest.mark.asyncio
async def test_load_plan_context_directory_no_phase(
    mock_soul: MagicMock, tmp_path: Path
) -> None:
    """_load_plan_context loads all phases when no target phase is specified."""

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "index.md").write_text("**plan_id:** all-phases\n", encoding="utf-8")
    (plan_dir / "phase-01.md").write_text("---\ntitle: A\n---\nBody A\n", encoding="utf-8")

    mock_soul.context = MagicMock()
    mock_soul.context.append_message = AsyncMock()
    session = DoSession(mock_soul, work_dir=tmp_path, plan_file=plan_dir)
    await session._load_plan_context()

    assert session._plan is not None
    assert len(session._plan.phases) == 1
    call_args = mock_soul.context.append_message.call_args[0][0]
    text = call_args.content[0].text
    assert "Plan: all-phases" in text
    # No target phase means no phase-specific details
    assert "Target Phase" not in text


@pytest.mark.asyncio
async def test_load_plan_context_missing_phase_logs_warning(
    mock_soul: MagicMock, tmp_path: Path
) -> None:
    """_load_plan_context logs a warning when the requested phase is not found."""

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("""## Phase 1: Only
### Description
Only phase.
""", encoding="utf-8")

    mock_soul.context = MagicMock()
    mock_soul.context.append_message = AsyncMock()
    session = DoSession(mock_soul, work_dir=tmp_path, plan_file=plan_file, phase="phase-99")
    await session._load_plan_context()

    # Plan is parsed but phase not found — _plan should be set
    assert session._plan is not None
    # No message appended because phase was not found
    mock_soul.context.append_message.assert_not_called()
