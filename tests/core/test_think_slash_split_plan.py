"""Tests for Think /split-plan slash command."""

from pathlib import Path

import pytest

from consilium.think.history import HistoryManager
from consilium.think.models import ThinkSession
from consilium.think.slash import slash_split_plan


@pytest.fixture
def think_session() -> ThinkSession:
    return ThinkSession(id="test-session")


@pytest.fixture
def history(think_session: ThinkSession) -> HistoryManager:
    return HistoryManager(think_session)


class TestSplitPlanSlashCommand:
    def test_no_args_returns_usage(self, history: HistoryManager, think_session: ThinkSession) -> None:
        result = slash_split_plan(history, think_session, "")
        assert "Usage:" in result

    def test_missing_file_returns_error(self, history: HistoryManager, think_session: ThinkSession, tmp_path: Path) -> None:
        result = slash_split_plan(history, think_session, str(tmp_path / "missing.md"))
        assert "not found" in result

    def test_splits_monolithic_plan(self, history: HistoryManager, think_session: ThinkSession, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("""# Plan

**plan_id:** my-plan
**created:** 2026-05-24

## Phase 1: Setup
**status:** implemented
**locked:** true
**files_involved:** src/main.py, tests/test_main.py
**dependencies:**

### Description
Set up the project.

### Acceptance Criteria
- Project created
- Tests passing

### Completion Criteria
- CI green

## Phase 2: Feature
**status:** pending
**dependencies:** phase-1

### Description
Add the feature.

### Risks
- Complexity
""", encoding="utf-8")

        result = slash_split_plan(history, think_session, str(plan_file))
        assert "Split plan into 2 phase document(s)" in result

        output_dir = tmp_path / "plan"
        assert output_dir.exists()
        assert (output_dir / "index.md").exists()
        assert (output_dir / "phase-1.md").exists()
        assert (output_dir / "phase-2.md").exists()

        # Check index.md content
        index_text = (output_dir / "index.md").read_text(encoding="utf-8")
        assert "plan_id: my-plan" in index_text
        assert "[phase-1](phase-1.md)" in index_text
        assert "phase-1 -> phase-2" not in index_text  # phase-1 has no deps
        assert "phase-2 -> phase-1" in index_text

        # Check phase-1.md content
        p1_text = (output_dir / "phase-1.md").read_text(encoding="utf-8")
        assert 'title: "Setup"' in p1_text
        assert "status: implemented" in p1_text
        assert "locked: true" in p1_text
        assert "- src/main.py" in p1_text
        assert "- tests/test_main.py" in p1_text
        assert "### Description" in p1_text
        assert "Set up the project." in p1_text
        assert "- Project created" in p1_text
        assert "- CI green" in p1_text

        # Check phase-2.md content
        p2_text = (output_dir / "phase-2.md").read_text(encoding="utf-8")
        assert 'title: "Feature"' in p2_text
        assert "status: pending" in p2_text
        assert "- phase-1" in p2_text
        assert "Add the feature." in p2_text
        assert "- Complexity" in p2_text

    def test_custom_output_dir(self, history: HistoryManager, think_session: ThinkSession, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("""## Phase 1: Only
### Description
Only phase.
""", encoding="utf-8")

        custom_dir = tmp_path / "custom_plan"
        result = slash_split_plan(history, think_session, f"{plan_file} {custom_dir}")
        assert "Split plan into 1 phase document(s)" in result
        assert custom_dir.exists()
        assert (custom_dir / "index.md").exists()

    def test_no_phases_returns_message(self, history: HistoryManager, think_session: ThinkSession, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad.md"
        plan_file.write_text("Not a valid plan at all.", encoding="utf-8")
        result = slash_split_plan(history, think_session, str(plan_file))
        assert "No phases found" in result
