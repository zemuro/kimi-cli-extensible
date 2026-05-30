"""Tests for dispatch mechanism."""

from __future__ import annotations

from pathlib import Path

import pytest

from kimi_cli.plan.dispatch import clear_dispatch, read_dispatch, write_dispatch
from kimi_cli.plan.models import DispatchAction


class TestDispatch:
    def test_write_and_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "kimi_cli.plan.dispatch.DISPATCH_PATH",
            tmp_path / "dispatch.json",
        )
        dispatch = write_dispatch(
            plan_id="plan_auth",
            target_phase="phase-3",
            action=DispatchAction.START_REVIEW,
            require_user_approval=True,
        )
        assert dispatch.plan_id == "plan_auth"
        assert dispatch.target_phase == "phase-3"

        loaded = read_dispatch()
        assert loaded is not None
        assert loaded.plan_id == "plan_auth"
        assert loaded.target_phase == "phase-3"
        assert loaded.action == DispatchAction.START_REVIEW

    def test_clear_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "kimi_cli.plan.dispatch.DISPATCH_PATH",
            tmp_path / "dispatch.json",
        )
        write_dispatch(plan_id="plan_auth", target_phase="phase-1")
        assert (tmp_path / "dispatch.json").exists()

        clear_dispatch()
        assert not (tmp_path / "dispatch.json").exists()

    def test_read_missing_returns_none(self, tmp_path: Path) -> None:
        result = read_dispatch(tmp_path / "nonexistent.json")
        assert result is None

    def test_afk_mode_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "kimi_cli.plan.dispatch.DISPATCH_PATH",
            tmp_path / "dispatch.json",
        )
        dispatch = write_dispatch(
            plan_id="plan_auth",
            target_phase="phase-3",
            afk_mode=True,
            dispatched_by="afk_auto",
        )
        assert dispatch.afk_mode is True
        assert dispatch.dispatched_by == "afk_auto"
