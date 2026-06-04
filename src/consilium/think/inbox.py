"""Think inbox for reverse bridge reports from Do mode."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

INBOX_DIR = Path.home() / ".consilium" / "think_inbox"
MAX_INBOX_SIZE = 100


@dataclass
class InboxReport:
    report_id: str
    source_session_id: str
    phase_id: str
    report_type: str  # "audit" | "completion" | "finding"
    content: str
    received_at: float
    read: bool = False


def get_inbox_path(think_session_id: str) -> Path:
    return INBOX_DIR / think_session_id


def _cleanup_oldest(inbox: Path, keep: int = MAX_INBOX_SIZE) -> None:
    """Remove oldest reports if inbox exceeds *keep* entries."""
    paths = sorted(inbox.glob("*.json"), key=lambda p: p.stat().st_mtime)
    while len(paths) > keep:
        paths.pop(0).unlink(missing_ok=True)


def write_report(
    think_session_id: str,
    source_session_id: str,
    phase_id: str,
    report_type: str,
    content: str,
) -> InboxReport:
    inbox = get_inbox_path(think_session_id)
    inbox.mkdir(parents=True, exist_ok=True)

    report = InboxReport(
        report_id=f"{uuid.uuid4().hex[:8]}_{int(time.time())}",
        source_session_id=source_session_id,
        phase_id=phase_id,
        report_type=report_type,
        content=content,
        received_at=time.time(),
    )
    report_path = inbox / f"{report.report_id}.json"
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    _cleanup_oldest(inbox)
    return report


def read_unread_reports(think_session_id: str) -> list[InboxReport]:
    inbox = get_inbox_path(think_session_id)
    if not inbox.exists():
        return []
    reports: list[InboxReport] = []
    for path in inbox.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        reports.append(InboxReport(**data))
    return [r for r in reports if not r.read]


def mark_report_read(report_id: str, think_session_id: str) -> None:
    inbox = get_inbox_path(think_session_id)
    path = inbox / f"{report_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["read"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
