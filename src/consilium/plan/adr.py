"""ADR (Architecture Decision Record) render and parse."""

from __future__ import annotations

import re
from pathlib import Path

from consilium.plan.parser import PlanParseError
from consilium.utils.timestamp import format_date, parse_timestamp

# YAML support
try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


class ADR:
    """In-memory representation of an Architecture Decision Record."""

    def __init__(
        self,
        adr_id: str,
        title: str,
        status: str = "accepted",
        date: float | None = None,
        supersedes: str | None = None,
        superseded_by: str | None = None,
        context: str = "",
        decision: str = "",
        consequences: list[str] | None = None,
    ) -> None:
        self.adr_id = adr_id
        self.title = title
        self.status = status
        self.date = date
        self.supersedes = supersedes
        self.superseded_by = superseded_by
        self.context = context
        self.decision = decision
        self.consequences = consequences or []


def render_adr(adr: ADR) -> str:
    """Render an ADR to Markdown."""
    lines = ["---"]
    lines.append(f'adr_id: "{adr.adr_id}"')
    lines.append(f"title: {adr.title}")
    lines.append(f"status: {adr.status}")
    if adr.date is not None:
        lines.append(f"date: {format_date(adr.date)}")
    if adr.supersedes:
        lines.append(f'supersedes: "{adr.supersedes}"')
    if adr.superseded_by:
        lines.append(f'superseded_by: "{adr.superseded_by}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# ADR {adr.adr_id}: {adr.title}")
    lines.append("")
    lines.append("## Context")
    lines.append(adr.context or "_No context provided._")
    lines.append("")
    lines.append("## Decision")
    lines.append(adr.decision or "_No decision recorded._")
    lines.append("")
    lines.append("## Consequences")
    if adr.consequences:
        for item in adr.consequences:
            lines.append(f"- {item}")
    else:
        lines.append("_No consequences recorded._")
    lines.append("")
    return "\n".join(lines)


def parse_adr(text: str) -> ADR:
    """Parse an ADR from Markdown text."""
    if not _HAS_YAML:
        raise PlanParseError("PyYAML is required to parse ADR frontmatter")

    # Split frontmatter and body
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not fm_match:
        raise PlanParseError("ADR missing YAML frontmatter")

    frontmatter_text = fm_match.group(1)
    body = fm_match.group(2)

    try:
        fm = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise PlanParseError(f"Invalid YAML frontmatter: {exc}") from exc

    adr_id = str(fm.get("adr_id", ""))
    title = str(fm.get("title", ""))
    status = str(fm.get("status", "accepted"))
    date = parse_timestamp(fm.get("date")) if fm.get("date") else None
    supersedes = fm.get("supersedes")
    superseded_by = fm.get("superseded_by")

    # Parse body sections
    context = ""
    decision = ""
    consequences: list[str] = []

    current_section: str | None = None
    section_lines: list[str] = []

    for line in body.splitlines():
        header_match = re.match(r"^##\s+(.*)$", line)
        if header_match:
            if current_section == "Context":
                context = "\n".join(section_lines).strip()
            elif current_section == "Decision":
                decision = "\n".join(section_lines).strip()
            elif current_section == "Consequences":
                consequences = [
                    re.sub(r"^[-*+]\s+", "", line)
                    for line in section_lines
                    if line.strip() and not line.strip().startswith("_")
                ]
            current_section = header_match.group(1).strip()
            section_lines = []
        else:
            section_lines.append(line)

    # Final section
    if current_section == "Context":
        context = "\n".join(section_lines).strip()
    elif current_section == "Decision":
        decision = "\n".join(section_lines).strip()
    elif current_section == "Consequences":
        consequences = [
            re.sub(r"^[-*+]\s+", "", line)
            for line in section_lines
            if line.strip() and not line.strip().startswith("_")
        ]

    return ADR(
        adr_id=adr_id,
        title=title,
        status=status,
        date=date,
        supersedes=supersedes,
        superseded_by=superseded_by,
        context=context,
        decision=decision,
        consequences=consequences,
    )


def read_adr(path: Path) -> ADR:
    """Read an ADR from disk."""
    if not path.exists():
        raise FileNotFoundError(f"ADR not found: {path}")
    return parse_adr(path.read_text(encoding="utf-8"))
