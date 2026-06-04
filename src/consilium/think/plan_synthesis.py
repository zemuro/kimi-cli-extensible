"""Plan synthesis utilities: file delimiter parsing, validation, and writing."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from consilium.utils.timestamp import format_date

# YAML support
try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


class SynthesisError(Exception):
    """Raised when plan synthesis fails validation."""


# ---------------------------------------------------------------------------
# File delimiter parsing
# ---------------------------------------------------------------------------


def parse_file_delimiters(text: str) -> dict[str, str]:
    """Parse `=== FILE: path ===` blocks from LLM output.

    Returns a dict mapping relative file paths to their content.
    """
    files: dict[str, str] = {}
    pattern = r"=== FILE:\s*(.+?)\s*===\n(.*?)(?=\n=== FILE:|\n\Z)"
    for match in re.finditer(pattern, text, re.DOTALL):
        path = match.group(1).strip()
        content = match.group(2).strip()
        if path:
            files[path] = content
    return files


def _extract_file_block(text: str, expected_path: str) -> str:
    """Extract content for expected_path from === FILE: delimiters."""
    pattern = rf"=== FILE:\s*{re.escape(expected_path)}\s*===\n(.*?)(?:\n=== FILE:|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: if no delimiters at all, assume entire output is the file
    if "=== FILE:" not in text:
        return text.strip()

    # Fallback: search for any matching path
    alt_pattern = r"=== FILE:\s*(plan/[^\s]+)\s*===\n(.*?)\n(?=== FILE:|\Z)"
    for path, content in re.findall(alt_pattern, text, re.DOTALL):
        if path == expected_path or path.endswith(Path(expected_path).name):
            return content.strip()

    raise SynthesisError(f"Could not find file block for {expected_path}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split YAML frontmatter from body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return None, text


def _validate_file(content: str, expected_path: str) -> None:
    """Validate extracted file content before writing."""
    # CI-7: Path traversal check using Path.is_relative_to()
    allowed_root = Path("plan").resolve()
    resolved = (allowed_root.parent / expected_path).resolve()
    try:
        if not resolved.is_relative_to(allowed_root):
            raise SynthesisError(f"Path traversal detected: {expected_path}")
    except ValueError:  # is_relative_to raises ValueError on Windows for different drives
        raise SynthesisError(f"Invalid path: {expected_path}") from None

    # Rule 2: YAML frontmatter must parse
    if _HAS_YAML:
        frontmatter, _ = _split_frontmatter(content)
        if frontmatter:
            try:
                yaml.safe_load(frontmatter)
            except yaml.YAMLError as exc:
                raise SynthesisError(f"Invalid YAML frontmatter: {exc}") from exc

    # Rule 3: For index.md, must have a phase status table
    if expected_path.endswith("index.md"):
        has_table = "| Phase |" in content or "## Phase" in content
        if not has_table:
            raise SynthesisError("index.md missing phase list or status table")


# ---------------------------------------------------------------------------
# Prompt strengthening
# ---------------------------------------------------------------------------


def _strengthen_prompt(original: str, expected_path: str, error: str) -> str:
    """Add stronger instructions to the prompt after a failure."""
    return f"""{original}

IMPORTANT: Your previous attempt failed validation: {error}
Please strictly follow this format:

=== FILE: {expected_path} ===
---
frontmatter: here
---
content here

Do not add any other text outside the === FILE: block.
"""


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


def write_plan_files(files: dict[str, str], work_dir: Path) -> None:
    """Write synthesized plan files to disk.

    Args:
        files: Mapping of relative paths (e.g., 'plan/index.md') to content.
        work_dir: Project root directory.
    """
    for rel_path, content in files.items():
        target = work_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _backup_plan_directory(plan_dir: Path) -> Path:
    """Copy (not move) the entire plan/ directory for backup.

    Uses shutil.copytree to preserve decisions/, findings/, and all phase files.
    Does NOT use Path.rename() — that would move (not copy) and risk data loss
    if the subsequent write fails.
    """
    timestamp = int(time.time())
    backup_dir = plan_dir.parent / f"plan.backup.{timestamp}"
    shutil.copytree(plan_dir, backup_dir)
    return backup_dir


# ---------------------------------------------------------------------------
# Plan directory scaffolding
# ---------------------------------------------------------------------------


def scaffold_plan_directories(work_dir: Path) -> Path:
    """Create plan/ subdirectories and .gitignore for reports.

    Returns the path to the plan directory.
    """
    plan_dir = work_dir / "plan"
    (plan_dir / "decisions").mkdir(parents=True, exist_ok=True)
    (plan_dir / "findings").mkdir(parents=True, exist_ok=True)
    (plan_dir / "reports").mkdir(parents=True, exist_ok=True)

    # G1: Create .gitignore for reports
    reports_gitignore = plan_dir / "reports" / ".gitignore"
    if not reports_gitignore.exists():
        reports_gitignore.write_text("# Auto-generated reports\n*.md\n", encoding="utf-8")

    return plan_dir


# ---------------------------------------------------------------------------
# Index rendering
# ---------------------------------------------------------------------------


def _render_plan_index(plan_dir) -> str:
    """Render PlanDirectory back to index.md Markdown.

    Note: plan_dir is a PlanDirectory model instance.
    """

    lines = ["---"]
    lines.append(f"plan_id: {plan_dir.metadata.plan_id}")
    lines.append(f"last_updated: {format_date(time.time())}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Plan: {plan_dir.metadata.plan_id or 'Untitled'}")
    lines.append("")
    lines.append("## Phase Status Table")
    lines.append("")
    lines.append("| Phase | Title | Status | Locked |")
    lines.append("|-------|-------|--------|--------|")
    for phase in plan_dir.phases:
        lock_icon = "✅" if phase.locked else "❌"
        lines.append(
            f"| [{phase.phase_id}]({phase.phase_id}.md) | {phase.title} "
            f"| {phase.status.value} | {lock_icon} |"
        )
    lines.append("")
    lines.append("## Dependency Graph")
    lines.append("")
    for phase in plan_dir.phases:
        if phase.dependencies:
            deps = ", ".join(phase.dependencies)
            lines.append(f"- {phase.phase_id} -> {deps}")
        else:
            lines.append(f"- {phase.phase_id} (no dependencies)")
    lines.append("")
    return "\n".join(lines) + "\n"


def _write_completion_report(
    plan_file: Path | None,
    phase_id: str,
    work_dir: Path,
    notes: str,
) -> Path:
    """Write a completion report for a phase."""
    from consilium.utils.timestamp import format_iso

    reports_dir = work_dir / "plan" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / f"completion-{phase_id}.md"

    content = f"""---
phase_id: {phase_id}
completed_at: {format_iso(time.time())}
---

# Completion Report: {phase_id}

## Summary
{notes or "(no notes provided)"}

## Changes
(journal summary not available)

## Verification
- [ ] Acceptance criteria met
- [ ] Tests pass
- [ ] Code reviewed
"""
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _update_plan_index_status(
    plan_file: Path | None,
    phase_id: str,
    status: str,
    locked: bool,
) -> None:
    """Parse → mutate → re-render using PlanDirectory model.

    Do NOT use regex on Markdown tables. Load the index into a
    PlanDirectory, update the phase object, then re-render.
    """
    if plan_file is None:
        return
    index_file = plan_file if plan_file.name == "index.md" else plan_file.parent / "index.md"
    if not index_file.exists():
        return

    from consilium.plan.parser import parse_plan_directory_from_path

    plan_dir = parse_plan_directory_from_path(index_file)
    phase = plan_dir.get_phase(phase_id)
    if phase is None:
        return

    from consilium.plan.models import PhaseStatus

    phase.status = PhaseStatus(status)
    phase.locked = locked
    rendered = _render_plan_index(plan_dir)
    index_file.write_text(rendered, encoding="utf-8")
