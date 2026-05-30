"""Session handover document creation and reading."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.plan.models import CompletedPhaseEntry, Handover, Plan


HANDOVER_DIR = Path("docs")
HANDOVER_PREFIX = "session_handover_"


def write_handover(
    plan: Plan,
    from_session: str = "",
    to_session: str = "",
    completed_phases: list[CompletedPhaseEntry] | None = None,
    knowledge_updates: list[str] | None = None,
    active_hypotheses: list[str] | None = None,
    open_questions: list[str] | None = None,
    recommended_first_action: str = "",
) -> Path:
    """Write a session handover document to docs/session_handover_YYYYMMDD.md.

    Returns:
        Path to the written handover file.
    """
    from kimi_cli.plan.models import Handover

    handover = Handover(
        from_session=from_session,
        to_session=to_session,
        plan_version=plan.metadata.plan_id,
        completed_phases=completed_phases or [],
        knowledge_updates=knowledge_updates or [],
        active_hypotheses=active_hypotheses or [],
        open_questions=open_questions or [],
        recommended_first_action=recommended_first_action,
    )

    from kimi_cli.utils.timestamp import format_date

    path = HANDOVER_DIR / f"{HANDOVER_PREFIX}{format_date(time.time())}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_handover(handover), encoding="utf-8")
    return path


def _render_handover(h: Handover) -> str:
    """Render a Handover model as Markdown."""
    lines: list[str] = []
    from kimi_cli.utils.timestamp import format_date

    lines.append(f"# Session Handover {format_date(h.created_at)}")
    lines.append("")
    lines.append("## Session Continuity")
    lines.append(f"- **From:** {h.from_session or 'N/A'}")
    lines.append(f"- **To:** {h.to_session or 'N/A'}")
    lines.append(f"- **Plan version:** {h.plan_version or 'N/A'}")
    lines.append("")

    if h.completed_phases:
        lines.append("## Completed Since Last Handover")
        lines.append("")
        lines.append("| Phase | Status | Key Output |")
        lines.append("|-------|--------|------------|")
        for entry in h.completed_phases:
            lines.append(f"| {entry.phase_id} | {entry.status.value} | {entry.key_output} |")
        lines.append("")

    if h.knowledge_updates:
        lines.append("## Knowledge Base Updates")
        for update in h.knowledge_updates:
            lines.append(f"- {update}")
        lines.append("")

    if h.active_hypotheses:
        lines.append("## Active Hypotheses")
        for hypothesis in h.active_hypotheses:
            lines.append(f"- {hypothesis}")
        lines.append("")

    if h.open_questions:
        lines.append("## Open Questions")
        for i, question in enumerate(h.open_questions, 1):
            lines.append(f"{i}. {question}")
        lines.append("")

    if h.recommended_first_action:
        lines.append("## Recommended First Action")
        lines.append(h.recommended_first_action)
        lines.append("")

    return "\n".join(lines)


def find_latest_handover(work_dir: Path | None = None) -> Path | None:
    """Find the most recent handover document in docs/.

    Args:
        work_dir: Optional working directory. Defaults to current directory.

    Returns:
        Path to the latest handover file, or None if none found.
    """
    base = work_dir or Path.cwd()
    handover_dir = base / HANDOVER_DIR
    if not handover_dir.exists():
        return None

    handovers = sorted(
        handover_dir.glob(f"{HANDOVER_PREFIX}*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return handovers[0] if handovers else None


def read_handover(path: Path) -> Handover:
    """Read a handover Markdown file back into a Handover model.

    Uses defensive parsing — missing fields get defaults.
    """
    from kimi_cli.plan.models import CompletedPhaseEntry, Handover, PhaseStatus

    text = path.read_text(encoding="utf-8")

    # Parse timestamp from header
    ts_match = re.search(r"# Session Handover (\d{4}-\d{2}-\d{2})", text)
    if ts_match:
        from kimi_cli.utils.timestamp import parse_timestamp

        created_at = parse_timestamp(ts_match.group(1) + "T00:00:00+00:00")
    else:
        created_at = time.time()

    h = Handover(created_at=created_at)

    # Parse completed phases table
    table_match = re.search(
        r"##\s*Completed Since Last Handover\s*\n\n?\|[^\n]+\|\n\|[-| ]+\|\n((?:\|[^\n]+\|\n?)+)",
        text,
        re.IGNORECASE,
    )
    if table_match:
        for line in table_match.group(1).strip().split("\n"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 3:
                try:
                    status = PhaseStatus(cells[1])
                except ValueError:
                    status = PhaseStatus.PENDING
                h.completed_phases.append(
                    CompletedPhaseEntry(
                        phase_id=cells[0],
                        status=status,
                        key_output=cells[2],
                    )
                )

    # Parse simple lists
    h.knowledge_updates = _extract_bullet_list(text, "Knowledge Base Updates")
    h.active_hypotheses = _extract_bullet_list(text, "Active Hypotheses")
    h.open_questions = _extract_numbered_list(text, "Open Questions")

    # Recommended first action
    action_match = re.search(
        r"##\s*Recommended First Action\s*\n(.+?)(?=\n##|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if action_match:
        h.recommended_first_action = action_match.group(1).strip()

    return h


def _extract_bullet_list(text: str, header: str) -> list[str]:
    """Extract a bullet list from a markdown section."""
    pattern = rf"##\s*{re.escape(header)}\s*\n((?:\s*[-*]\s*.+\n?)+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return []
    items = []
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        cleaned = re.sub(r"^[-*]\s+", "", line)
        if cleaned:
            items.append(cleaned)
    return items


def _extract_numbered_list(text: str, header: str) -> list[str]:
    """Extract a numbered list from a markdown section."""
    pattern = rf"##\s*{re.escape(header)}\s*\n((?:\s*\d+\.\s*.+\n?)+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return []
    items = []
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        cleaned = re.sub(r"^\d+\.\s+", "", line)
        if cleaned:
            items.append(cleaned)
    return items
