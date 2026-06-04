"""Tests for Phase 4b.2 (journal retention) and 4b.3 (binary diffs)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from consilium.do.diff_computer import is_binary_file
from consilium.do.journal import (
    JOURNAL_DIR,
    ChangeJournal,
    DiffEntry,
    archive_old_journals,
)
from consilium.do.session import DoSession


class TestArchiveOldJournals:
    def test_archives_journals_older_than_threshold(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("consilium.do.journal.JOURNAL_DIR", tmp_path)

        # Create a "recent" journal dir
        recent = tmp_path / "recent-session"
        recent.mkdir()
        (recent / "journal.jsonl").write_text("{}", encoding="utf-8")

        # Create an "old" journal dir
        old = tmp_path / "old-session"
        old.mkdir()
        (old / "journal.jsonl").write_text("{}", encoding="utf-8")
        # Backdate its mtime to 60 days ago
        old_mtime = time.time() - 60 * 86400
        os.utime(old, (old_mtime, old_mtime))

        archived = archive_old_journals(max_age_days=30)

        assert len(archived) == 1
        assert archived[0].name.startswith("old-session")
        assert not old.exists()
        assert (tmp_path / ".archive" / archived[0].name).exists()
        assert recent.exists()  # Recent journal untouched

    def test_disabled_when_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("consilium.do.journal.JOURNAL_DIR", tmp_path)

        old = tmp_path / "old-session"
        old.mkdir()
        old_mtime = time.time() - 60 * 86400
        os.utime(old, (old_mtime, old_mtime))

        archived = archive_old_journals(max_age_days=0)

        assert archived == []
        assert old.exists()

    def test_skips_non_directories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("consilium.do.journal.JOURNAL_DIR", tmp_path)

        # A plain file in the journal dir should be ignored
        (tmp_path / "not-a-dir.txt").write_text("hello")

        archived = archive_old_journals(max_age_days=1)
        assert archived == []


class TestBinaryDiffHandling:
    def test_is_binary_file_detects_null_bytes(self, tmp_path: Path) -> None:
        binary_path = tmp_path / "image.png"
        binary_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        assert is_binary_file(binary_path) is True

    def test_is_binary_file_text_is_false(self, tmp_path: Path) -> None:
        text_path = tmp_path / "hello.py"
        text_path.write_text("print('hello')\n", encoding="utf-8")
        assert is_binary_file(text_path) is False

    def test_is_binary_file_missing_is_false(self, tmp_path: Path) -> None:
        assert is_binary_file(tmp_path / "nonexistent.bin") is False

    @pytest.mark.asyncio
    async def test_binary_diff_skips_unified_diff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from consilium.do import journal as journal_mod
        monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path / "do_sessions")

        mock_soul = MagicMock()
        mock_soul._runtime.session.id = "test-bin-session"
        mock_soul._current_turn_index = 1

        do_session = DoSession(mock_soul, work_dir=tmp_path)
        await do_session.start()

        # Create a binary file (contains null bytes)
        bin_path = tmp_path / "image.png"
        bin_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00OLD")

        from kosong.message import ToolCall
        tool_call = MagicMock()
        tool_call.function.name = "write_file"
        tool_call.function.arguments = '{"path": "image.png"}'
        tool_call.id = "tc_bin"

        await do_session.capture_baseline(tool_call)

        # Modify the binary file
        bin_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00NEW")

        tool_result = MagicMock()
        tool_result.tool_call_id = "tc_bin"

        with patch("consilium.soul.get_wire_or_none", return_value=None):
            await do_session.on_tool_result(tool_call, tool_result)

        diffs = do_session.journal.get_entries("diff")
        assert len(diffs) == 1
        entry = diffs[0]
        assert entry["is_binary"] is True
        assert entry["unified_diff"] == ""
        assert entry["lines_added"] == 0
        assert entry["lines_removed"] == 0
        assert entry["size_before"] == 12
        assert entry["size_after"] == 12

    @pytest.mark.asyncio
    async def test_text_diff_still_works(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from consilium.do import journal as journal_mod
        monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path / "do_sessions")

        mock_soul = MagicMock()
        mock_soul._runtime.session.id = "test-text-session"
        mock_soul._current_turn_index = 1

        do_session = DoSession(mock_soul, work_dir=tmp_path)
        await do_session.start()

        text_path = tmp_path / "hello.py"
        text_path.write_text("original\n", encoding="utf-8")

        from kosong.message import ToolCall
        tool_call = MagicMock()
        tool_call.function.name = "write_file"
        tool_call.function.arguments = '{"path": "hello.py"}'
        tool_call.id = "tc_text"

        await do_session.capture_baseline(tool_call)

        text_path.write_text("modified\n", encoding="utf-8")

        tool_result = MagicMock()
        tool_result.tool_call_id = "tc_text"

        with patch("consilium.soul.get_wire_or_none", return_value=None):
            await do_session.on_tool_result(tool_call, tool_result)

        diffs = do_session.journal.get_entries("diff")
        assert len(diffs) == 1
        entry = diffs[0]
        assert entry["is_binary"] is False
        assert entry["lines_added"] == 1
        assert entry["lines_removed"] == 1
