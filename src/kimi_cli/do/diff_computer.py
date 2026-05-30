"""Compute unified diffs between two text contents."""

from __future__ import annotations

import difflib
from pathlib import Path


def is_binary_file(path: Path | str, sample_size: int = 8192) -> bool:
    """Heuristic binary-file detection.

    Reads the first *sample_size* bytes and checks for null bytes.
    If the file cannot be read as raw bytes, it is treated as binary.
    """
    try:
        data = Path(path).read_bytes()[:sample_size]
    except (OSError, IOError):
        return False
    return b"\x00" in data


def compute_unified_diff(
    baseline: str,
    current: str,
    path: str = "file",
    context_lines: int = 3,
) -> str:
    """Compute a unified diff between baseline and current content.

    Args:
        baseline: Pre-edit content.
        current: Post-edit content.
        path: File path for diff headers.
        context_lines: Number of context lines around changes.

    Returns:
        Unified diff text, or empty string if no changes.
    """
    baseline_lines = baseline.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)

    # Ensure all lines end with newline for clean diff
    if baseline_lines and not baseline_lines[-1].endswith("\n"):
        baseline_lines[-1] += "\n"
    if current_lines and not current_lines[-1].endswith("\n"):
        current_lines[-1] += "\n"

    diff = difflib.unified_diff(
        baseline_lines,
        current_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )

    return "".join(diff)
