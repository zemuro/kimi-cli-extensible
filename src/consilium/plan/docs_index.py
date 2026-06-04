"""Documentation index: parse docs/README.md → structured index → JSON cache."""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from consilium.plan.models import DocEntry, DocsIndex


_TABLE_ROW_RE = re.compile(
    r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$"
)


def _parse_date(value: str) -> float | None:
    """Parse a date string like '2026-05-24' into a Unix timestamp."""
    from consilium.utils.timestamp import parse_timestamp

    value = value.strip()
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


def _split_related_phases(value: str) -> list[str]:
    """Parse related phases like '1-3' or 'all' into phase IDs."""
    value = value.strip().lower()
    if value in ("all", "", "-"):
        return []
    phases: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            # Range like "1-3" → phase-1, phase-2, phase-3
            try:
                start, end = part.split("-", 1)
                for i in range(int(start), int(end) + 1):
                    phases.append(f"phase-{i}")
            except ValueError:
                pass
        else:
            with contextlib.suppress(ValueError):
                phases.append(f"phase-{int(part)}")
    return phases


def parse_docs_index(readme_text: str) -> DocsIndex:
    """Parse a docs/README.md markdown table into a DocsIndex.

    Expected table format:
    | Document | Purpose | Status | Updated | Policy | Related Phases |
    |----------|---------|--------|---------|--------|----------------|
    | architecture.md | System design | current | 2026-05-20 | think_and_do | 1-3 |
    """
    from consilium.plan.models import DocEntry, DocsIndex, DocStatus, UpdatePolicy

    documents: list[DocEntry] = []
    in_active_table = False

    for line in readme_text.splitlines():
        stripped = line.strip()

        # Detect table start
        if stripped.lower().startswith("| document"):
            in_active_table = True
            continue
        if in_active_table and stripped.startswith("|") and "---" in stripped.replace("|", ""):
            continue
        if not stripped.startswith("|"):
            in_active_table = False
            continue

        if in_active_table:
            match = _TABLE_ROW_RE.match(stripped)
            if match:
                path = match.group(1).strip()
                purpose = match.group(2).strip()
                status_str = match.group(3).strip().lower()
                updated_str = match.group(4).strip()
                policy_str = match.group(5).strip().lower()
                related_str = match.group(6).strip()

                try:
                    status = DocStatus(status_str)
                except ValueError:
                    status = DocStatus.CURRENT

                try:
                    policy = UpdatePolicy(policy_str)
                except ValueError:
                    policy = UpdatePolicy.THINK_AND_DO

                documents.append(
                    DocEntry(
                        path=path,
                        purpose=purpose,
                        status=status,
                        last_updated=_parse_date(updated_str),
                        update_policy=policy,
                        related_phases=_split_related_phases(related_str),
                    )
                )

    return DocsIndex(documents=documents)


def generate_docs_index(readme_path: Path) -> DocsIndex:
    """Read docs/README.md and parse it into a DocsIndex."""
    if not readme_path.exists():
        return DocsIndex()
    text = readme_path.read_text(encoding="utf-8")
    return parse_docs_index(text)


def write_docs_index_cache(index: DocsIndex, cache_path: Path) -> None:
    """Write the DocsIndex to .consilium/docs_index.json."""
    import json

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            index.model_dump(mode="json"),
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def read_docs_index_cache(cache_path: Path) -> DocsIndex:
    """Read the DocsIndex from .consilium/docs_index.json."""
    from consilium.plan.models import DocsIndex

    if not cache_path.exists():
        return DocsIndex()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    return DocsIndex.model_validate(data)
