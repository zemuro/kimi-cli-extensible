"""Tests for ChangeJournal."""

from __future__ import annotations

from pathlib import Path

import pytest

from consilium.do.journal import ChangeJournal, DiffEntry


@pytest.fixture
def journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChangeJournal:
    from consilium.do import journal as journal_mod
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path / "do_sessions")
    return ChangeJournal("test-session")


def test_journal_append_and_read(journal: ChangeJournal) -> None:
    journal.record_session_start(work_dir="/tmp/test", initial_git_head="abc123")
    journal.record_checkpoint(commit_hash="def456", message="checkpoint")

    entries = journal.get_entries()
    assert len(entries) == 2
    assert entries[0]["type"] == "session_start"
    assert entries[1]["type"] == "checkpoint"


def test_journal_record_diff(journal: ChangeJournal) -> None:
    entry = journal.record_diff(
        turn_index=1,
        step_index=0,
        tool_call_id="tc1",
        tool_name="write_file",
        path="src/main.py",
        baseline_content="",
        post_content="print('hello')",
        unified_diff="+print('hello')",
    )

    assert isinstance(entry, DiffEntry)
    assert entry.turn_index == 1
    assert entry.step_index == 0
    assert entry.tool_name == "write_file"
    assert entry.path == "src/main.py"
    assert entry.operation == "write"

    diffs = journal.get_entries("diff")
    assert len(diffs) == 1
    assert diffs[0]["path"] == "src/main.py"


def test_journal_get_diffs_for_path(journal: ChangeJournal) -> None:
    journal.record_diff(
        turn_index=1, step_index=0, tool_call_id="tc1",
        tool_name="write_file", path="a.py",
        baseline_content="", post_content="a", unified_diff="+a",
    )
    journal.record_diff(
        turn_index=1, step_index=1, tool_call_id="tc2",
        tool_name="write_file", path="b.py",
        baseline_content="", post_content="b", unified_diff="+b",
    )
    journal.record_diff(
        turn_index=2, step_index=0, tool_call_id="tc3",
        tool_name="write_file", path="a.py",
        baseline_content="a", post_content="a2", unified_diff="-a\n+a2",
    )

    a_diffs = journal.get_diffs_for_path("a.py")
    assert len(a_diffs) == 2

    b_diffs = journal.get_diffs_for_path("b.py")
    assert len(b_diffs) == 1


def test_journal_get_diffs_since_turn(journal: ChangeJournal) -> None:
    journal.record_diff(
        turn_index=1, step_index=0, tool_call_id="tc1",
        tool_name="write_file", path="a.py",
        baseline_content="", post_content="a", unified_diff="+a",
    )
    journal.record_diff(
        turn_index=3, step_index=0, tool_call_id="tc2",
        tool_name="write_file", path="b.py",
        baseline_content="", post_content="b", unified_diff="+b",
    )

    diffs = journal.get_diffs_since_turn(2)
    assert len(diffs) == 1
    assert diffs[0]["turn_index"] == 3


def test_journal_get_turn_summary(journal: ChangeJournal) -> None:
    journal.record_diff(
        turn_index=2, step_index=0, tool_call_id="tc1",
        tool_name="write_file", path="a.py",
        baseline_content="", post_content="line1\nline2", unified_diff="+line1\n+line2",
    )
    journal.record_diff(
        turn_index=2, step_index=1, tool_call_id="tc2",
        tool_name="write_file", path="b.py",
        baseline_content="", post_content="line3", unified_diff="+line3",
    )

    summary = journal.get_turn_summary(2)
    assert summary["turn_index"] == 2
    assert summary["files_changed"] == 2
    assert summary["total_additions"] == 3
    assert summary["total_deletions"] == 0
