"""Audit report model, Markdown renderer, and parser."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.plan.models import AuditReport


def render_audit_report(report: AuditReport) -> str:
    """Render an AuditReport as Markdown.

    Format matches the specification in §4d.7 of the implementation plan.
    """
    lines: list[str] = []
    lines.append(f"# Audit Report: {report.phase_id}")
    lines.append("")
    from kimi_cli.utils.timestamp import format_iso

    lines.append(f"_Generated: {format_iso(report.timestamp)}_")
    lines.append("")

    # Feasibility
    feasible_emoji = "✅" if report.feasible else "❌"
    lines.append(f"## Feasibility: {feasible_emoji} {'Yes' if report.feasible else 'No'}")
    lines.append("")

    # L1 summary (if available)
    if report.l1_result is not None:
        lines.append("## L1 Heuristic Check")
        if report.l1_result.passed:
            lines.append("L1 audit passed.")
        else:
            lines.append("L1 audit flagged issues:")
            for msg in report.l1_result.messages:
                lines.append(f"- {msg}")
        if not report.l2_used:
            lines.append("L2 audit skipped (L1 sufficient).")
        lines.append("")

    # Risks
    if report.risks:
        lines.append("## Risks")
        for i, risk in enumerate(report.risks, 1):
            lines.append(f"{i}. {risk}")
        lines.append("")

    # Recommendations
    if report.recommendations:
        lines.append("## Recommendations")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    # Discovery
    if report.discoveries:
        lines.append("## Discovery")
        for i, discovery in enumerate(report.discoveries, 1):
            lines.append(f"{i}. {discovery}")
        lines.append("")

    # Questions
    if report.questions:
        lines.append("## Questions")
        for i, question in enumerate(report.questions, 1):
            lines.append(f"{i}. {question}")
        lines.append("")

    return "\n".join(lines)


def parse_audit_report(text: str, phase_id: str = "") -> AuditReport:
    """Parse a Markdown audit report back into an AuditReport model.

    Uses defensive regex parsing with sensible defaults.
    """
    from kimi_cli.plan.models import AuditReport

    # Feasibility
    feasible_match = re.search(
        r"##\s*Feasibility:\s*[✅✓✔✕❌×X]?\s*(Yes|No)",
        text,
        re.IGNORECASE,
    )
    feasible = feasible_match.group(1).lower() == "yes" if feasible_match else False

    # Extract sections
    risks = _extract_numbered_section(text, "Risks")
    recommendations = _extract_numbered_section(text, "Recommendations")
    discoveries = _extract_numbered_section(text, "Discovery")
    questions = _extract_numbered_section(text, "Questions")

    # Timestamp
    from kimi_cli.utils.timestamp import parse_timestamp

    ts_match = re.search(
        r"_Generated:\s*(\d{4}-\d{2}-\d{2}T[\d:.]+(?:[+-]\d{2}:\d{2}|Z)?)_",
        text,
    )
    timestamp = parse_timestamp(ts_match.group(1)) if ts_match else __import__("time").time()

    return AuditReport(
        phase_id=phase_id,
        timestamp=timestamp,
        feasible=feasible,
        risks=risks,
        recommendations=recommendations,
        discoveries=discoveries,
        questions=questions,
        l2_used=True,  # Assume L2 was used if parsing from Markdown
    )


def _extract_numbered_section(text: str, header: str) -> list[str]:
    """Extract numbered list items from a markdown section.

    Looks for:
    ## Header
    1. Item one
    2. Item two
    """
    pattern = rf"##\s*{re.escape(header)}\s*\n((?:\s*\d+\.\s*.+\n?)+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return []
    lines = match.group(1).strip().split("\n")
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Remove leading number and dot
        cleaned = re.sub(r"^\d+\.\s*", "", line)
        if cleaned:
            items.append(cleaned)
    return items
