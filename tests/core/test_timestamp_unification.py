"""Tests for timestamp format unification (Phase 10)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from consilium.utils.timestamp import format_date, format_iso, parse_timestamp


class TestParseTimestamp:
    def test_parses_unix_float(self) -> None:
        ts = 1716912000.0  # 2024-05-28 16:00:00 UTC
        result = parse_timestamp(ts)
        assert result == pytest.approx(ts)

    def test_parses_unix_int(self) -> None:
        ts = 1716912000
        result = parse_timestamp(ts)
        assert result == pytest.approx(float(ts))

    def test_parses_iso_string_with_timezone(self) -> None:
        result = parse_timestamp("2026-05-24T14:00:00+00:00")
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        assert result == pytest.approx(dt.timestamp())

    def test_parses_iso_string_with_z_suffix(self) -> None:
        result = parse_timestamp("2026-05-24T14:00:00Z")
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        assert result == pytest.approx(dt.timestamp())

    def test_parses_naive_iso_string_as_utc(self) -> None:
        result = parse_timestamp("2026-05-24T14:00:00")
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        assert result == pytest.approx(dt.timestamp())

    def test_parses_date_only_string(self) -> None:
        result = parse_timestamp("2026-05-24")
        dt = datetime(2026, 5, 24, 0, 0, 0, tzinfo=UTC)
        assert result == pytest.approx(dt.timestamp())

    def test_none_returns_current_time(self) -> None:
        before = time.time()
        result = parse_timestamp(None)
        after = time.time()
        assert before <= result <= after

    def test_parses_iso_with_offset(self) -> None:
        result = parse_timestamp("2026-05-24T10:00:00-04:00")
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        assert result == pytest.approx(dt.timestamp())


class TestFormatIso:
    def test_formats_to_iso_utc(self) -> None:
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        result = format_iso(dt.timestamp())
        assert result == "2026-05-24T14:00:00+00:00"


class TestFormatDate:
    def test_formats_to_date(self) -> None:
        dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC)
        result = format_date(dt.timestamp())
        assert result == "2026-05-24"


class TestThinkModels:
    def test_think_message_timestamp_is_float(self) -> None:
        from consilium.think.models import ThinkMessage

        msg = ThinkMessage()
        assert isinstance(msg.timestamp, float)

    def test_think_session_created_at_is_float(self) -> None:
        from consilium.think.models import ThinkSession

        session = ThinkSession()
        assert isinstance(session.created_at, float)


class TestPlanModels:
    def test_plan_metadata_created_is_float(self) -> None:
        from consilium.plan.models import PlanMetadata

        ts = time.time()
        meta = PlanMetadata(created=ts)
        assert isinstance(meta.created, float)
        assert meta.created == pytest.approx(ts)

    def test_audit_report_timestamp_is_float(self) -> None:
        from consilium.plan.models import AuditReport

        report = AuditReport(phase_id="p1")
        assert isinstance(report.timestamp, float)

    def test_doc_entry_last_updated_is_float(self) -> None:
        from consilium.plan.models import DocEntry

        ts = time.time()
        entry = DocEntry(path="x.md", last_updated=ts)
        assert isinstance(entry.last_updated, float)

    def test_dispatch_dispatched_at_is_float(self) -> None:
        from consilium.plan.models import Dispatch, DispatchAction

        d = Dispatch(
            dispatch_id="d1",
            plan_id="p1",
            action=DispatchAction.START_REVIEW,
            target_phase="phase-1",
        )
        assert isinstance(d.dispatched_at, float)

    def test_handover_created_at_is_float(self) -> None:
        from consilium.plan.models import Handover

        h = Handover()
        assert isinstance(h.created_at, float)


class TestJournalTimestamp:
    def test_journal_entry_timestamp_is_float(self) -> None:
        from consilium.do.journal import JournalEntry

        entry = JournalEntry()
        assert isinstance(entry.timestamp, float)


class TestTokenTracker:
    def test_token_log_entry_timestamp_is_float(self) -> None:
        from consilium.token_tracker import TokenLogEntry

        entry = TokenLogEntry(
            timestamp=time.time(),
            session_id="s1",
            turn_id="t1",
            model="m1",
            tokens_in=10,
            tokens_out=5,
            active_context=100,
        )
        assert isinstance(entry.timestamp, float)


class TestBackwardCompat:
    def test_think_storage_roundtrip_with_float(self, tmp_path) -> None:

        from consilium.think.models import ThinkMessage, ThinkSession
        from consilium.think.storage import load_session, save_session

        session = ThinkSession()
        msg = ThinkMessage(content="hello", timestamp=1716912000.0)
        session.messages.append(msg)
        save_session(session, work_dir=tmp_path)

        loaded = load_session(session.id, work_dir=tmp_path)
        assert loaded is not None
        assert loaded.messages[0].timestamp == 1716912000.0

    def test_think_storage_loads_legacy_iso(self, tmp_path) -> None:
        """Old JSONL with ISO strings should still load."""
        import json

        from consilium.think.storage import load_session

        session_id = "test-legacy"
        # Write to the workspace-local path
        session_dir = tmp_path / ".consilium" / "sessions" / "think"
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{session_id}.jsonl"
        legacy_msg = {
            "id": "msg_abc",
            "role": "user",
            "content": "hello",
            "timestamp": "2026-05-24T14:00:00+00:00",
            "deleted": False,
            "edited_at": None,
        }
        path.write_text(json.dumps(legacy_msg) + "\n", encoding="utf-8")

        loaded = load_session(session_id, work_dir=tmp_path)
        assert loaded is not None
        assert loaded.messages[0].timestamp == pytest.approx(
            datetime(2026, 5, 24, 14, 0, 0, tzinfo=UTC).timestamp()
        )

    def test_plan_parser_parses_date_to_float(self) -> None:
        from consilium.plan.parser import parse_plan

        text = """# Plan
**plan_id:** test-plan
**created:** 2026-05-24

## Phase 1: Setup
### Description
Do setup.
"""
        plan = parse_plan(text)
        assert isinstance(plan.metadata.created, float)
        from consilium.utils.timestamp import format_date

        assert format_date(plan.metadata.created) == "2026-05-24"

    def test_audit_report_roundtrip(self) -> None:
        from consilium.plan.audit_report import parse_audit_report, render_audit_report
        from consilium.plan.models import AuditReport

        report = AuditReport(phase_id="phase-1", timestamp=1716912000.0)
        text = render_audit_report(report)
        assert "2024-05-28T16:00:00+00:00" in text

        parsed = parse_audit_report(text, phase_id="phase-1")
        assert isinstance(parsed.timestamp, float)
        assert parsed.timestamp == pytest.approx(1716912000.0)

    def test_handover_read_preserves_timestamp(self, tmp_path) -> None:
        from consilium.plan.handover import _render_handover, read_handover
        from consilium.plan.models import Handover

        ts = 1716854400.0  # 2024-05-28 00:00:00 UTC (date-only precision)
        handover = Handover(created_at=ts)
        text = _render_handover(handover)

        path = tmp_path / "handover.md"
        path.write_text(text, encoding="utf-8")

        loaded = read_handover(path)
        assert isinstance(loaded.created_at, float)
        assert loaded.created_at == pytest.approx(ts)
