"""Tests for diff_computer."""

from __future__ import annotations

from consilium.do.diff_computer import compute_unified_diff


def test_diff_computer_unified_diff() -> None:
    baseline = "line1\nline2\nline3\n"
    current = "line1\nmodified\nline3\n"
    diff = compute_unified_diff(baseline, current, path="test.txt")

    assert diff.startswith("--- a/test.txt")
    assert "-line2" in diff
    assert "+modified" in diff


def test_diff_computer_no_change() -> None:
    content = "same\ncontent\n"
    diff = compute_unified_diff(content, content, path="test.txt")
    assert diff == ""


def test_diff_computer_new_file() -> None:
    baseline = ""
    current = "new line\n"
    diff = compute_unified_diff(baseline, current, path="new.txt")
    assert "+new line" in diff


def test_diff_computer_deleted_file() -> None:
    baseline = "old line\n"
    current = ""
    diff = compute_unified_diff(baseline, current, path="del.txt")
    assert "-old line" in diff
