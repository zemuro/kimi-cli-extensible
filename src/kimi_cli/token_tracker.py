"""Global token usage logging across all sessions."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path


@dataclass(slots=True)
class TokenLogEntry:
    timestamp: float
    session_id: str
    turn_id: str
    model: str
    tokens_in: int
    tokens_out: int
    active_context: int


class BudgetExceededError(Exception):
    """Raised when the token budget for a session is exceeded."""


class TokenTracker:
    """Append-only CSV logger for token usage across all sessions."""

    CSV_HEADER = "timestamp,session_id,turn_id,model,tokens_in,tokens_out,active_context\n"
    LOG_DIR: Path = Path.home() / ".kimi" / "token_log"

    def __init__(self) -> None:
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        self._current_file = self.LOG_DIR / f"{datetime.now(UTC):%Y-%m-%d}.csv"
        if not self._current_file.exists():
            self._current_file.write_text(self.CSV_HEADER, encoding="utf-8")

    def log(self, entry: TokenLogEntry) -> None:
        """Append a single entry to today's CSV."""
        from datetime import datetime

        with self._current_file.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.fromtimestamp(entry.timestamp, tz=UTC).isoformat(),
                entry.session_id,
                entry.turn_id,
                entry.model,
                entry.tokens_in,
                entry.tokens_out,
                entry.active_context,
            ])

    def _read_all_entries(self) -> list[dict[str, str]]:
        """Read all CSV entries from all log files."""
        entries: list[dict[str, str]] = []
        for csv_file in sorted(self.LOG_DIR.glob("*.csv")):
            with csv_file.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                entries.extend(reader)
        return entries

    def get_session_summary(self, session_id: str) -> dict[str, object]:
        """Return aggregated stats for a session."""
        burned_tokens = 0
        active_context_max = 0
        model_breakdown: dict[str, int] = {}

        for row in self._read_all_entries():
            if row["session_id"] != session_id:
                continue
            tokens_in = int(row["tokens_in"])
            tokens_out = int(row["tokens_out"])
            active_context = int(row["active_context"])
            model = row["model"]

            burned_tokens += tokens_in + tokens_out
            active_context_max = max(active_context_max, active_context)
            model_breakdown[model] = model_breakdown.get(model, 0) + tokens_in + tokens_out

        return {
            "burned_tokens": burned_tokens,
            "active_context_max": active_context_max,
            "model_breakdown": model_breakdown,
        }

    def get_global_summary(self, since: float | None = None) -> dict[str, object]:
        """Return global aggregated stats across all sessions."""
        from kimi_cli.utils.timestamp import parse_timestamp

        total_burned = 0
        session_breakdown: dict[str, int] = {}
        model_breakdown: dict[str, int] = {}

        for row in self._read_all_entries():
            if since is not None:
                row_ts = parse_timestamp(row["timestamp"])
                if row_ts < since:
                    continue

            tokens_in = int(row["tokens_in"])
            tokens_out = int(row["tokens_out"])
            burned = tokens_in + tokens_out
            session_id = row["session_id"]
            model = row["model"]

            total_burned += burned
            session_breakdown[session_id] = session_breakdown.get(session_id, 0) + burned
            model_breakdown[model] = model_breakdown.get(model, 0) + burned

        return {
            "total_burned": total_burned,
            "session_breakdown": session_breakdown,
            "model_breakdown": model_breakdown,
        }
