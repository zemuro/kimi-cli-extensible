"""Shared timestamp parsing and formatting utilities.

Rule: Unix float (UTC) for everything internal; ISO 8601 only for
human-facing Markdown output.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def parse_timestamp(value: str | float | int | None) -> float:
    """Parse a timestamp from legacy or new format, returning Unix timestamp (UTC).

    Accepts:
      - float / int: Unix timestamp (new format)
      - str: ISO 8601 string (legacy format, with or without timezone)

    Naive ISO strings are interpreted as UTC.
    """
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)

    # ISO string (legacy)
    s = str(value).strip()
    # Normalize Z suffix to +00:00 for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except ValueError:
        pass

    # Final fallback — try as raw number
    return float(s)


def format_iso(ts: float) -> str:
    """Format a Unix timestamp as ISO 8601 string in UTC.

    Use this for human-facing Markdown output.
    """
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def format_date(ts: float) -> str:
    """Format a Unix timestamp as YYYY-MM-DD in UTC.

    Use this for plan documents where day-precision is sufficient.
    """
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
