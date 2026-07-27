"""Markdown plan document parser.

Parses docs/plan.md into structured Pydantic models.
Uses regex for the rigid plan format rather than a full Markdown AST.
"""

from __future__ import annotations

import re
from pathlib import Path

from consilium.plan.models import Phase, PhaseStatus, Plan, PlanDirectory, PlanMetadata
from consilium.utils.timestamp import parse_timestamp

# YAML support for directory-based plans (Phase 8)
try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


class PlanParseError(Exception):
    """Raised when a plan document cannot be parsed."""

    def __init__(self, message: str, line_number: int | None = None) -> None:
        self.line_number = line_number
        if line_number is not None:
            message = f"Line {line_number}: {message}"
        super().__init__(message)


# Regex patterns for plan parsing
_PHASE_HEADER_RE = re.compile(
    r"^##\s+Phase\s+(?P<num>\d+):\s+(?P<title>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_KV_RE = re.compile(
    r"\*\*(?P<key>[\w_]+):\*\*\s*(?P<value>.+)",
    re.IGNORECASE,
)
_SUBSECTION_RE = re.compile(
    r"^###\s+(?P<title>[\w\s]+)",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_date(value: str) -> float | None:
    """Parse a date string like '2026-05-24' into Unix timestamp."""
    value = value.strip()
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


def _parse_list_block(lines: list[str]) -> list[str]:
    """Parse a list of items from markdown lines.

    Handles:
    - [x] Checked items
    - [ ] Unchecked items
    - Plain bullet points (-, *, +)

    Skips horizontal rules (---, ***, ___).
    """
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip horizontal rules
        if re.fullmatch(r"[-*_*]{3,}", line):
            continue
        # Remove leading list markers
        cleaned = re.sub(r"^[-*+]\s+", "", line)
        cleaned = re.sub(r"^\[\s*[xX]?\s*\]\s*", "", cleaned)
        if cleaned:
            items.append(cleaned)
    return items


def _parse_phase_block(block_text: str, line_offset: int) -> Phase:
    """Parse a single phase block into a Phase model."""

    lines = block_text.splitlines()
    if not lines:
        raise PlanParseError("Empty phase block", line_number=line_offset)

    # Parse header
    header_match = _PHASE_HEADER_RE.match(lines[0])
    if not header_match:
        raise PlanParseError(
            f"Invalid phase header: {lines[0]!r}",
            line_number=line_offset,
        )

    phase_num = header_match.group("num")
    title = header_match.group("title").strip()
    phase_id = f"phase-{phase_num}"

    # Parse key-value pairs and subsections
    status = PhaseStatus.PLANNING
    locked = False
    files_involved: list[str] = []
    dependencies: list[str] = []
    description_lines: list[str] = []
    acceptance_criteria: list[str] = []
    completion_criteria: list[str] = []
    risks: list[str] = []
    known: list[str] = []
    unknown: list[str] = []

    current_subsection: str | None = None
    current_subsection_lines: list[str] = []

    def _flush_subsection() -> None:
        nonlocal current_subsection, current_subsection_lines
        if current_subsection is None:
            return
        text = "\n".join(current_subsection_lines).strip()
        items = _parse_list_block(current_subsection_lines)

        if current_subsection.lower() == "description":
            nonlocal description_lines
            description_lines = [text]
        elif current_subsection.lower() == "acceptance criteria":
            nonlocal acceptance_criteria
            acceptance_criteria = items
        elif current_subsection.lower() == "completion criteria":
            nonlocal completion_criteria
            completion_criteria = items
        elif current_subsection.lower() == "risks":
            nonlocal risks
            risks = items
        elif current_subsection.lower() == "known":
            nonlocal known
            known = items
        elif current_subsection.lower() == "unknown":
            nonlocal unknown
            unknown = items

        current_subsection = None
        current_subsection_lines = []

    i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Key-value pairs (e.g., **status:** approved)
        kv_match = _KV_RE.match(stripped)
        if kv_match and current_subsection is None:
            key = kv_match.group("key").lower()
            value = kv_match.group("value").strip()

            if key == "status":
                try:
                    status = PhaseStatus(value.lower())
                except ValueError:
                    status = PhaseStatus.PLANNING
            elif key == "locked":
                locked = value.lower() in ("true", "yes", "1")
            elif key == "files_involved":
                files_involved = [f.strip() for f in value.split(",") if f.strip()]
            elif key == "dependencies":
                # Handle [phase-1, phase-2] or plain list
                dep_text = value.strip("[]")
                dependencies = [d.strip() for d in dep_text.split(",") if d.strip()]
            i += 1
            continue

        # Subsection headers (### Description, etc.)
        sub_match = _SUBSECTION_RE.match(stripped)
        if sub_match:
            _flush_subsection()
            current_subsection = sub_match.group("title")
            i += 1
            continue

        # Accumulate subsection content
        if current_subsection is not None:
            current_subsection_lines.append(line)

        i += 1

    _flush_subsection()

    return Phase(
        phase_id=phase_id,
        title=title,
        status=status,
        locked=locked,
        files_involved=files_involved,
        dependencies=dependencies,
        description=description_lines[0] if description_lines else "",
        acceptance_criteria=acceptance_criteria,
        completion_criteria=completion_criteria,
        risks=risks,
        known=known,
        unknown=unknown,
    )


def _parse_metadata(text: str) -> PlanMetadata:
    """Parse metadata section from plan markdown."""

    plan_id = ""
    created: float | None = None
    last_updated: float | None = None

    for line in text.splitlines():
        stripped = line.strip()
        # Handle both "**key:** value" and "- **key:** value" (list items)
        kv_match = _KV_RE.search(stripped)
        if kv_match:
            key = kv_match.group("key").lower()
            value = kv_match.group("value").strip()
            if key == "plan_id":
                plan_id = value
            elif key == "created":
                created = _parse_date(value)
            elif key == "last_updated":
                last_updated = _parse_date(value)

    return PlanMetadata(plan_id=plan_id, created=created, last_updated=last_updated)


def parse_plan(text: str) -> Plan:
    """Parse a plan markdown document into a Plan model.

    Args:
        text: Full markdown content of the plan document.

    Returns:
        Parsed Plan model.

    Raises:
        PlanParseError: If the document is malformed.
    """
    if not text.strip():
        raise PlanParseError("Plan document is empty")

    # Find all phase blocks
    phases: list[Phase] = []
    # Phase and Plan are imported at module level
    seen: set[str] = set()

    for match in _PHASE_HEADER_RE.finditer(text):
        # Determine the block boundaries: from this header to the next ## header
        start = match.start()
        # Find next phase header or end of document
        next_match = _PHASE_HEADER_RE.search(text, match.end())
        end = next_match.start() if next_match else len(text)
        block = text[start:end]

        # Calculate line offset for error messages
        line_offset = text[:start].count("\n") + 1

        phase = _parse_phase_block(block, line_offset)
        if phase.phase_id in seen:
            raise PlanParseError(
                f"Duplicate phase ID: {phase.phase_id}",
                line_number=line_offset,
            )
        seen.add(phase.phase_id)
        phases.append(phase)

    # Extract metadata from before the first phase
    first_phase_match = _PHASE_HEADER_RE.search(text)
    metadata_text = text[:first_phase_match.start()] if first_phase_match else text
    metadata = _parse_metadata(metadata_text)

    return Plan(metadata=metadata, phases=phases)


def parse_plan_file(path: Path) -> Plan:
    """Read and parse a plan document from disk.

    Args:
        path: Path to the plan markdown file.

    Returns:
        Parsed Plan model.

    Raises:
        PlanParseError: If parsing fails.
        FileNotFoundError: If the file does not exist.
    """
    text = path.read_text(encoding="utf-8")
    return parse_plan(text)


# --- Phase 8: Directory-based plan parsing ---


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n?---\s*\n(.*)$",
    re.DOTALL,
)


def _parse_yaml_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and remaining body from markdown.

    Returns:
        Tuple of (frontmatter dict, markdown body).
        If no frontmatter, returns ({}, text).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match or not _HAS_YAML:
        return {}, text
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(frontmatter, dict):
        return {}, text
    body = match.group(2)
    return frontmatter, body


def _phase_from_frontmatter(frontmatter: dict, body: str, phase_id: str) -> Phase:
    """Build a Phase model from YAML frontmatter + markdown body."""
    status_str = str(frontmatter.get("status", "planning")).lower()
    try:
        status = PhaseStatus(status_str)
    except ValueError:
        status = PhaseStatus.PLANNING

    # Parse body for subsections if present
    lines = body.splitlines()
    description_lines: list[str] = []
    acceptance_criteria: list[str] = []
    completion_criteria: list[str] = []
    risks: list[str] = []
    known: list[str] = []
    unknown: list[str] = []

    current_subsection: str | None = None
    current_subsection_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_subsection, current_subsection_lines
        if current_subsection is None:
            return
        text = "\n".join(current_subsection_lines).strip()
        items = _parse_list_block(current_subsection_lines)
        if current_subsection.lower() == "description":
            nonlocal description_lines
            description_lines = [text]
        elif current_subsection.lower() == "acceptance criteria":
            nonlocal acceptance_criteria
            acceptance_criteria = items
        elif current_subsection.lower() == "completion criteria":
            nonlocal completion_criteria
            completion_criteria = items
        elif current_subsection.lower() == "risks":
            nonlocal risks
            risks = items
        elif current_subsection.lower() == "known":
            nonlocal known
            known = items
        elif current_subsection.lower() == "unknown":
            nonlocal unknown
            unknown = items
        current_subsection = None
        current_subsection_lines = []

    for line in lines:
        stripped = line.strip()
        sub_match = _SUBSECTION_RE.match(stripped)
        if sub_match:
            _flush()
            current_subsection = sub_match.group("title")
            continue
        if current_subsection is not None:
            current_subsection_lines.append(line)
    _flush()

    return Phase(
        phase_id=phase_id,
        title=frontmatter.get("title", ""),
        status=status,
        locked=bool(frontmatter.get("locked", False)),
        files_involved=frontmatter.get("files_involved", []) or [],
        dependencies=frontmatter.get("dependencies", []) or [],
        description=description_lines[0] if description_lines else body.strip(),
        acceptance_criteria=acceptance_criteria,
        completion_criteria=completion_criteria,
        risks=risks,
        known=known,
        unknown=unknown,
    )


def parse_plan_directory(text: str, *, phase_id: str, index_path: Path) -> PlanDirectory:
    """Parse a single phase markdown document with YAML frontmatter.

    Args:
        text: Full markdown content of the phase document.
        phase_id: The phase identifier (e.g., 'phase-01').
        index_path: Path to the plan index file.

    Returns:
        PlanDirectory with a single phase populated.
    """
    if not text.strip():
        raise PlanParseError("Phase document is empty")

    frontmatter, body = _parse_yaml_frontmatter(text)
    phase = _phase_from_frontmatter(frontmatter, body, phase_id)
    return PlanDirectory(index_path=index_path, phases=[phase])


def parse_plan_directory_from_path(path: Path) -> PlanDirectory:
    """Read and parse a directory-based plan.

    Expects a directory containing:
      - index.md: metadata + status table + dependency graph
      - phase-XX.md: per-phase documents with YAML frontmatter

    Args:
        path: Path to the plan directory or its index.md file.

    Returns:
        PlanDirectory with all phases parsed from the directory.

    Raises:
        PlanParseError: If parsing fails.
        FileNotFoundError: If the directory or index.md does not exist.
    """
    if path.exists() and path.is_file() and path.name == "index.md":
        index_path = path
        directory = path.parent
    elif path.exists() and path.is_dir():
        directory = path
        index_path = path / "index.md"
    else:
        raise FileNotFoundError(f"Plan directory or index not found: {path}")

    # Parse index.md for metadata
    index_text = index_path.read_text(encoding="utf-8")
    fm, body = _parse_yaml_frontmatter(index_text)
    if fm:
        # Build metadata from YAML frontmatter
        metadata = PlanMetadata(
            plan_id=str(fm.get("plan_id", "")),
            created=parse_timestamp(str(fm.get("created", ""))) if fm.get("created") else None,
            last_updated=parse_timestamp(str(fm.get("last_updated", "")))
            if fm.get("last_updated")
            else None,
        )
    else:
        metadata = _parse_metadata(body)

    phases: list[Phase] = []
    seen: set[str] = set()

    # Find all phase-XX.md files in the directory
    phase_files = sorted(
        directory.glob("phase-*.md"),
        key=lambda p: p.stem,
    )

    for phase_file in phase_files:
        phase_id = phase_file.stem
        text = phase_file.read_text(encoding="utf-8")
        frontmatter, body = _parse_yaml_frontmatter(text)
        phase = _phase_from_frontmatter(frontmatter, body, phase_id)
        if phase.phase_id in seen:
            raise PlanParseError(f"Duplicate phase ID: {phase.phase_id}")
        seen.add(phase.phase_id)
        phases.append(phase)

    return PlanDirectory(index_path=index_path, metadata=metadata, phases=phases)


def is_plan_directory(path: Path) -> bool:
    """Check whether the given path represents a directory-based plan.

    Returns True if:
      - path is a directory containing index.md
      - path is index.md itself
    """
    if path.is_file() and path.name == "index.md":
        return True
    if path.is_dir():
        return (path / "index.md").exists()
    return False
