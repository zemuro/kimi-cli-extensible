"""Finding (research output) render and parse."""

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


class Finding:
    """In-memory representation of a research finding."""

    def __init__(
        self,
        finding_id: str,
        title: str,
        date: float | None = None,
        related_phases: list[str] | None = None,
        summary: str = "",
        evidence: list[str] | None = None,
        impact: str = "",
    ) -> None:
        self.finding_id = finding_id
        self.title = title
        self.date = date
        self.related_phases = related_phases or []
        self.summary = summary
        self.evidence = evidence or []
        self.impact = impact


def render_finding(finding: Finding) -> str:
    """Render a Finding to Markdown."""
    lines = ["---"]
    lines.append(f'finding_id: "{finding.finding_id}"')
    lines.append(f"title: {finding.title}")
    if finding.date is not None:
        lines.append(f"date: {format_date(finding.date)}")
    if finding.related_phases:
        lines.append("related_phases:")
        for phase in finding.related_phases:
            lines.append(f"  - {phase}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Finding {finding.finding_id}: {finding.title}")
    lines.append("")
    lines.append("## Summary")
    lines.append(finding.summary or "_No summary provided._")
    lines.append("")
    lines.append("## Evidence")
    if finding.evidence:
        for item in finding.evidence:
            lines.append(f"- {item}")
    else:
        lines.append("_No evidence recorded._")
    lines.append("")
    lines.append("## Impact")
    lines.append(finding.impact or "_No impact recorded._")
    lines.append("")
    return "\n".join(lines)


def parse_finding(text: str) -> Finding:
    """Parse a Finding from Markdown text."""
    if not _HAS_YAML:
        raise PlanParseError("PyYAML is required to parse finding frontmatter")

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not fm_match:
        raise PlanParseError("Finding missing YAML frontmatter")

    frontmatter_text = fm_match.group(1)
    body = fm_match.group(2)

    try:
        fm = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise PlanParseError(f"Invalid YAML frontmatter: {exc}") from exc

    finding_id = str(fm.get("finding_id", ""))
    title = str(fm.get("title", ""))
    date = parse_timestamp(fm.get("date")) if fm.get("date") else None
    related_phases = fm.get("related_phases", []) or []

    # Parse body sections
    summary = ""
    evidence: list[str] = []
    impact = ""

    current_section: str | None = None
    section_lines: list[str] = []

    for line in body.splitlines():
        header_match = re.match(r"^##\s+(.*)$", line)
        if header_match:
            if current_section == "Summary":
                summary = "\n".join(section_lines).strip()
            elif current_section == "Evidence":
                evidence = [
                    re.sub(r"^[-*+]\s+", "", line)
                    for line in section_lines
                    if line.strip() and not line.strip().startswith("_")
                ]
            elif current_section == "Impact":
                impact = "\n".join(section_lines).strip()
            current_section = header_match.group(1).strip()
            section_lines = []
        else:
            section_lines.append(line)

    if current_section == "Summary":
        summary = "\n".join(section_lines).strip()
    elif current_section == "Evidence":
        evidence = [
            re.sub(r"^[-*+]\s+", "", line)
            for line in section_lines
            if line.strip() and not line.strip().startswith("_")
        ]
    elif current_section == "Impact":
        impact = "\n".join(section_lines).strip()

    return Finding(
        finding_id=finding_id,
        title=title,
        date=date,
        related_phases=related_phases,
        summary=summary,
        evidence=evidence,
        impact=impact,
    )


def read_finding(path: Path) -> Finding:
    """Read a Finding from disk."""
    if not path.exists():
        raise FileNotFoundError(f"Finding not found: {path}")
    return parse_finding(path.read_text(encoding="utf-8"))
