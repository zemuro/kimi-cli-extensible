"""Tests for the token tracker module."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from consilium.token_tracker import BudgetExceededError, TokenLogEntry, TokenTracker, get_quota_summary


@pytest.fixture
def tracker(tmp_path: Path):
    """Provide a TokenTracker that writes into a temporary directory."""
    with patch.object(TokenTracker, "LOG_DIR", tmp_path):
        yield TokenTracker()


class TestTokenTrackerLog:
    def test_log_appends_to_csv(self, tracker: TokenTracker, tmp_path: Path) -> None:
        entry = TokenLogEntry(
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            session_id="sess_123",
            turn_id="turn_abc",
            model="kimi-k2",
            tokens_in=100,
            tokens_out=50,
            active_context=200,
        )
        tracker.log(entry)

        csv_file = tmp_path / f"{datetime.now():%Y-%m-%d}.csv"
        assert csv_file.exists()
        rows = list(csv.reader(csv_file.open("r", encoding="utf-8")))
        assert len(rows) == 2  # header + 1 data row
        assert rows[1][1] == "sess_123"
        assert rows[1][3] == "kimi-k2"
        assert rows[1][4] == "100"
        assert rows[1][5] == "50"
        assert rows[1][6] == "200"

    def test_log_creates_file_with_header(self, tracker: TokenTracker, tmp_path: Path) -> None:
        csv_file = tmp_path / f"{datetime.now():%Y-%m-%d}.csv"
        assert csv_file.exists()
        content = csv_file.read_text(encoding="utf-8")
        assert content.startswith(TokenTracker.CSV_HEADER)


class TestTokenTrackerSessionSummary:
    def test_session_summary_aggregates_correctly(self, tracker: TokenTracker) -> None:
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_A",
                turn_id="t1",
                model="model_1",
                tokens_in=100,
                tokens_out=50,
                active_context=200,
            ),
            TokenLogEntry(
                timestamp=base_time + timedelta(minutes=1),
                session_id="sess_A",
                turn_id="t2",
                model="model_1",
                tokens_in=200,
                tokens_out=100,
                active_context=300,
            ),
            TokenLogEntry(
                timestamp=base_time + timedelta(minutes=2),
                session_id="sess_B",
                turn_id="t3",
                model="model_2",
                tokens_in=50,
                tokens_out=25,
                active_context=100,
            ),
        ]
        for entry in entries:
            tracker.log(entry)

        summary = tracker.get_session_summary("sess_A")
        assert summary["burned_tokens"] == 450  # (100+50) + (200+100)
        assert summary["active_context_max"] == 300
        assert summary["model_breakdown"] == {"model_1": 450}

    def test_session_summary_empty_session(self, tracker: TokenTracker) -> None:
        summary = tracker.get_session_summary("nonexistent")
        assert summary["burned_tokens"] == 0
        assert summary["active_context_max"] == 0
        assert summary["model_breakdown"] == {}


class TestTokenTrackerGlobalSummary:
    def test_global_summary(self, tracker: TokenTracker) -> None:
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_A",
                turn_id="t1",
                model="model_1",
                tokens_in=100,
                tokens_out=50,
                active_context=200,
            ),
            TokenLogEntry(
                timestamp=base_time + timedelta(minutes=1),
                session_id="sess_B",
                turn_id="t2",
                model="model_2",
                tokens_in=200,
                tokens_out=100,
                active_context=300,
            ),
        ]
        for entry in entries:
            tracker.log(entry)

        summary = tracker.get_global_summary()
        assert summary["total_burned"] == 450
        assert summary["session_breakdown"] == {"sess_A": 150, "sess_B": 300}
        assert summary["model_breakdown"] == {"model_1": 150, "model_2": 300}

    def test_global_summary_since_filter(self, tracker: TokenTracker) -> None:
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tracker.log(
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_A",
                turn_id="t1",
                model="model_1",
                tokens_in=100,
                tokens_out=50,
                active_context=200,
            )
        )
        tracker.log(
            TokenLogEntry(
                timestamp=base_time + timedelta(hours=2),
                session_id="sess_A",
                turn_id="t2",
                model="model_1",
                tokens_in=200,
                tokens_out=100,
                active_context=300,
            )
        )

        summary = tracker.get_global_summary(since=base_time + timedelta(hours=1))
        assert summary["total_burned"] == 300


class TestBudgetExceededError:
    def test_budget_exceeded_error_message(self) -> None:
        err = BudgetExceededError("Token budget exceeded: 1000 / 1000 tokens")
        assert str(err) == "Token budget exceeded: 1000 / 1000 tokens"


class TestGetQuotaSummary:
    def test_session_quota(self, tracker: TokenTracker) -> None:
        from datetime import datetime, timezone
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tracker.log(
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_quota",
                turn_id="t1",
                model="model_1",
                tokens_in=4000,
                tokens_out=2000,
                active_context=200,
            )
        )
        quota = get_quota_summary("sess_quota", budget_tokens=20_000)
        assert quota is not None
        assert quota.weekly_used_minutes == 3  # 6000 // 2000
        assert quota.weekly_limit_minutes == 10  # 20_000 // 2000
        assert quota.weekly_remaining_minutes == 7

    def test_global_quota(self, tracker: TokenTracker) -> None:
        from datetime import datetime, timezone
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tracker.log(
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_A",
                turn_id="t1",
                model="model_1",
                tokens_in=2000,
                tokens_out=0,
                active_context=200,
            )
        )
        tracker.log(
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_B",
                turn_id="t2",
                model="model_2",
                tokens_in=0,
                tokens_out=2000,
                active_context=200,
            )
        )
        quota = get_quota_summary(budget_tokens=10_000)
        assert quota is not None
        assert quota.weekly_used_minutes == 2  # 4000 // 2000
        assert quota.weekly_limit_minutes == 5  # 10_000 // 2000
        assert quota.weekly_remaining_minutes == 3

    def test_quota_no_data_returns_none(self, tracker: TokenTracker) -> None:
        quota = get_quota_summary("nonexistent")
        assert quota is None

    def test_quota_defaults_budget(self, tracker: TokenTracker) -> None:
        from datetime import datetime, timezone
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tracker.log(
            TokenLogEntry(
                timestamp=base_time,
                session_id="sess_default",
                turn_id="t1",
                model="model_1",
                tokens_in=200_000,
                tokens_out=0,
                active_context=200,
            )
        )
        quota = get_quota_summary("sess_default")
        assert quota is not None
        assert quota.weekly_limit_minutes == 50  # 100_000 // 2000
        assert quota.weekly_used_minutes == 100  # 200_000 // 2000
        assert quota.weekly_remaining_minutes == 0  # clamped at 0
