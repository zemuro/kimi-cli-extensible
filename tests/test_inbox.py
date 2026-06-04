"""Tests for the Think inbox (Phase 13 reverse bridge)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from consilium.think.inbox import (
    InboxReport,
    MAX_INBOX_SIZE,
    get_inbox_path,
    mark_report_read,
    read_unread_reports,
    write_report,
)


@pytest.fixture
def inbox_dir(tmp_path: Path):
    """Provide a temporary inbox directory."""
    with patch("consilium.think.inbox.INBOX_DIR", tmp_path):
        yield tmp_path


class TestWriteReport:
    def test_creates_report_file(self, inbox_dir: Path) -> None:
        report = write_report(
            think_session_id="think-123",
            source_session_id="do-456",
            phase_id="phase-01",
            report_type="completion",
            content="Done!",
        )
        inbox = get_inbox_path("think-123")
        assert inbox.exists()
        paths = list(inbox.glob("*.json"))
        assert len(paths) == 1
        assert report.report_id in paths[0].name

    def test_report_fields(self, inbox_dir: Path) -> None:
        report = write_report(
            think_session_id="think-123",
            source_session_id="do-456",
            phase_id="phase-02",
            report_type="audit",
            content="Audit result",
        )
        assert report.source_session_id == "do-456"
        assert report.phase_id == "phase-02"
        assert report.report_type == "audit"
        assert report.content == "Audit result"
        assert not report.read

    def test_inbox_cap_removes_oldest(self, inbox_dir: Path) -> None:
        """Write more than MAX_INBOX_SIZE reports; oldest should be pruned."""
        for i in range(MAX_INBOX_SIZE + 5):
            write_report(
                think_session_id="think-cap",
                source_session_id="do-456",
                phase_id=f"phase-{i:03d}",
                report_type="finding",
                content=f"Report {i}",
            )
        inbox = get_inbox_path("think-cap")
        assert len(list(inbox.glob("*.json"))) == MAX_INBOX_SIZE


class TestReadUnreadReports:
    def test_returns_only_unread(self, inbox_dir: Path) -> None:
        r1 = write_report("think-123", "do-456", "phase-01", "completion", "Done")
        r2 = write_report("think-123", "do-456", "phase-02", "audit", "Audit")
        mark_report_read(r1.report_id, "think-123")

        unread = read_unread_reports("think-123")
        assert len(unread) == 1
        assert unread[0].report_id == r2.report_id

    def test_returns_empty_when_none(self, inbox_dir: Path) -> None:
        assert read_unread_reports("think-empty") == []

    def test_returns_empty_when_all_read(self, inbox_dir: Path) -> None:
        r1 = write_report("think-123", "do-456", "phase-01", "completion", "Done")
        mark_report_read(r1.report_id, "think-123")
        assert read_unread_reports("think-123") == []


class TestMarkReportRead:
    def test_marks_read(self, inbox_dir: Path) -> None:
        r = write_report("think-123", "do-456", "phase-01", "completion", "Done")
        mark_report_read(r.report_id, "think-123")
        unread = read_unread_reports("think-123")
        assert len(unread) == 0

    def test_noop_on_missing_report(self, inbox_dir: Path) -> None:
        # Should not raise
        mark_report_read("nonexistent", "think-123")
