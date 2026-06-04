"""Tests for plan synthesis utilities."""

from __future__ import annotations

import pytest

from consilium.think.plan_synthesis import (
    SynthesisError,
    _backup_plan_directory,
    _extract_file_block,
    _update_plan_index_status,
    _validate_file,
    _write_completion_report,
    parse_file_delimiters,
    scaffold_plan_directories,
)


class TestParseFileDelimiters:
    def test_parses_single_file(self) -> None:
        text = "=== FILE: plan/index.md ===\n# Hello\n\nworld\n"
        files = parse_file_delimiters(text)
        assert files == {"plan/index.md": "# Hello\n\nworld"}

    def test_parses_multiple_files(self) -> None:
        text = (
            "=== FILE: plan/index.md ===\n# Index\n"
            "=== FILE: plan/phase-01.md ===\n# Phase 1\n"
        )
        files = parse_file_delimiters(text)
        assert "plan/index.md" in files
        assert "plan/phase-01.md" in files

    def test_no_delimiters_returns_empty(self) -> None:
        files = parse_file_delimiters("# Just markdown\n")
        assert files == {}


class TestExtractFileBlock:
    def test_extracts_exact_path(self) -> None:
        text = "=== FILE: plan/index.md ===\n# Index\n=== FILE: plan/phase-01.md ===\n# Phase 1\n"
        result = _extract_file_block(text, "plan/index.md")
        assert result == "# Index"

    def test_fallback_no_delimiters(self) -> None:
        text = "# Just markdown\n"
        result = _extract_file_block(text, "plan/index.md")
        assert result == "# Just markdown"

    def test_raises_when_not_found(self) -> None:
        text = "=== FILE: plan/other.md ===\n# Other\n"
        with pytest.raises(SynthesisError):
            _extract_file_block(text, "plan/index.md")


class TestValidateFile:
    def test_accepts_valid_path(self) -> None:
        _validate_file("---\nplan_id: test\n---\n# Plan", "plan/phase-01.md")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(SynthesisError, match="Path traversal"):
            _validate_file("content", "../../../etc/passwd")

    def test_rejects_missing_index_table(self) -> None:
        with pytest.raises(SynthesisError, match="missing phase list"):
            _validate_file("---\n---\n# Plan", "plan/index.md")

    def test_index_with_table_passes(self) -> None:
        _validate_file("| Phase | Title |\n|-------|-------|\n", "plan/index.md")


class TestBackupPlanDirectory:
    def test_creates_backup(self, tmp_path) -> None:
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "index.md").write_text("# Plan", encoding="utf-8")
        backup = _backup_plan_directory(plan_dir)
        assert backup.exists()
        assert (backup / "index.md").read_text(encoding="utf-8") == "# Plan"
        # Original still exists
        assert (plan_dir / "index.md").exists()


class TestScaffoldPlanDirectories:
    def test_creates_directories_and_gitignore(self, tmp_path) -> None:
        plan_dir = scaffold_plan_directories(tmp_path)
        assert (plan_dir / "decisions").exists()
        assert (plan_dir / "findings").exists()
        assert (plan_dir / "reports").exists()
        assert (plan_dir / "reports" / ".gitignore").exists()
        gitignore = (plan_dir / "reports" / ".gitignore").read_text(encoding="utf-8")
        assert "*.md" in gitignore


class TestWriteCompletionReport:
    def test_writes_report(self, tmp_path) -> None:
        report_path = _write_completion_report(
            tmp_path / "plan" / "index.md",
            "phase-01",
            tmp_path,
            "Done!",
        )
        assert report_path.exists()
        text = report_path.read_text(encoding="utf-8")
        assert "Completion Report: phase-01" in text
        assert "Done!" in text
        assert "phase_id: phase-01" in text
        assert "completed_at:" in text


class TestUpdatePlanIndexStatus:
    def test_updates_phase_status(self, tmp_path) -> None:

        # Create a simple plan directory
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        index = plan_dir / "index.md"
        index.write_text(
            "---\nplan_id: test\n---\n\n"
            "# Plan: test\n\n"
            "## Phase Status Table\n\n"
            "| Phase | Title | Status | Locked |\n"
            "|-------|-------|--------|--------|\n"
            "| [phase-01](phase-01.md) | Setup | pending | ❌ |\n"
            "| [phase-02](phase-02.md) | Core | pending | ❌ |\n",
            encoding="utf-8",
        )
        (plan_dir / "phase-01.md").write_text(
            "---\nphase_id: phase-01\ntitle: Setup\nstatus: pending\n---\n",
            encoding="utf-8",
        )
        (plan_dir / "phase-02.md").write_text(
            "---\nphase_id: phase-02\ntitle: Core\nstatus: pending\n---\n",
            encoding="utf-8",
        )

        _update_plan_index_status(index, "phase-01", "implemented", True)

        updated = index.read_text(encoding="utf-8")
        assert "implemented" in updated
        assert "✅" in updated

    def test_noop_when_plan_file_none(self) -> None:
        _update_plan_index_status(None, "phase-01", "implemented", True)
