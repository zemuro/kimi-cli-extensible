"""Tests for session handover documents."""

from __future__ import annotations

from pathlib import Path

import pytest

from kimi_cli.plan.handover import (
    find_latest_handover,
    read_handover,
    write_handover,
)
from kimi_cli.plan.models import CompletedPhaseEntry, PhaseStatus
from kimi_cli.plan.parser import parse_plan


PLAN_TEXT = """\
## Phase 1: Foundation
**status:** implemented
**locked:** true
"""


class TestHandover:
    def test_write_and_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        plan = parse_plan(PLAN_TEXT)

        path = write_handover(
            plan=plan,
            from_session="sess_abc",
            to_session="sess_def",
            completed_phases=[
                CompletedPhaseEntry(
                    phase_id="phase-1",
                    status=PhaseStatus.IMPLEMENTED,
                    key_output="src/auth/token.py",
                ),
            ],
            knowledge_updates=["Updated architecture.md §3.2"],
            open_questions=["Verify interrupt vector layout"],
            recommended_first_action="Run tests",
        )

        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "Session Handover" in text
        assert "src/auth/token.py" in text

        handover = read_handover(path)
        assert len(handover.completed_phases) == 1
        assert handover.completed_phases[0].phase_id == "phase-1"
        assert handover.knowledge_updates == ["Updated architecture.md §3.2"]
        assert handover.open_questions == ["Verify interrupt vector layout"]
        assert handover.recommended_first_action == "Run tests"

    def test_find_latest_handover(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        plan = parse_plan(PLAN_TEXT)

        write_handover(plan=plan, from_session="old")
        latest = find_latest_handover()
        assert latest is not None
        assert "session_handover_" in latest.name

    def test_no_handover_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert find_latest_handover() is None
