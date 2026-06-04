"""Tests for Think-mode /plan command suite."""

from __future__ import annotations

from consilium.think.history import HistoryManager
from consilium.think.models import ThinkSession
from consilium.think.plan_commands import (
    _extract_phase_ids,
    slash_plan,
    slash_plan_init,
    slash_plan_status,
)


class TestExtractPhaseIds:
    def test_extracts_from_table(self) -> None:
        text = "| phase-01 | Setup | pending | ❌ |\n| phase-02 | Core | pending | ❌ |"
        ids = _extract_phase_ids(text)
        assert ids == ["phase-01", "phase-02"]

    def test_deduplicates(self) -> None:
        text = "| phase-01 | A |\n| phase-01 | B |"
        ids = _extract_phase_ids(text)
        assert ids == ["phase-01"]

    def test_empty_when_no_matches(self) -> None:
        assert _extract_phase_ids("# No table\n") == []


class TestSlashPlanStatus:
    def test_shows_status_table(self, tmp_path) -> None:
        # Create a plan directory
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        index = plan_dir / "index.md"
        index.write_text(
            "---\nplan_id: test-plan\n---\n\n"
            "# Plan: test-plan\n\n"
            "## Phase Status Table\n\n"
            "| Phase | Title | Status | Locked |\n"
            "|-------|-------|--------|--------|\n"
            "| [phase-01](phase-01.md) | Setup | pending | ❌ |\n",
            encoding="utf-8",
        )
        (plan_dir / "phase-01.md").write_text(
            "---\nphase_id: phase-01\ntitle: Setup\nstatus: pending\n---\n",
            encoding="utf-8",
        )

        # Change to tmp_path so Path("plan/index.md") resolves
        import os

        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            session = ThinkSession()
            history = HistoryManager(session)
            result = slash_plan_status(history, session, "")
            assert "test-plan" in result
            assert "phase-01" in result
            assert "pending" in result
        finally:
            os.chdir(orig_cwd)

    def test_no_plan_error(self, tmp_path) -> None:
        import os

        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            session = ThinkSession()
            history = HistoryManager(session)
            result = slash_plan_status(history, session, "")
            assert "No plan found" in result
        finally:
            os.chdir(orig_cwd)


class TestSlashPlanInit:
    def test_no_think_soul_returns_error(self, tmp_path) -> None:
        import asyncio
        import os

        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            session = ThinkSession()
            history = HistoryManager(session)
            result = asyncio.run(slash_plan_init(history, session, ""))
            assert "ThinkSoul or LLM not available" in result
        finally:
            os.chdir(orig_cwd)


class TestSlashPlanDispatcher:
    def test_status_subcommand(self, tmp_path) -> None:
        import asyncio
        import os

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        index = plan_dir / "index.md"
        index.write_text(
            "---\nplan_id: test\n---\n# Plan: test\n\n"
            "## Phase Status Table\n| Phase | Title | Status | Locked |\n"
            "|-------|-------|--------|--------|\n"
            "| [phase-01](phase-01.md) | Setup | pending | ❌ |\n",
            encoding="utf-8",
        )
        (plan_dir / "phase-01.md").write_text(
            "---\nphase_id: phase-01\ntitle: Setup\nstatus: pending\n---\n",
            encoding="utf-8",
        )

        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            session = ThinkSession()
            history = HistoryManager(session)
            result = asyncio.run(slash_plan(history, session, "status"))
            assert "test" in result
            assert "phase-01" in result
        finally:
            os.chdir(orig_cwd)

    def test_empty_args_shows_usage(self, tmp_path) -> None:
        import asyncio
        import os

        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            session = ThinkSession()
            history = HistoryManager(session)
            result = asyncio.run(slash_plan(history, session, ""))
            assert "Usage:" in result
            assert "init" in result
            assert "status" in result
        finally:
            os.chdir(orig_cwd)
