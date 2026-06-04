"""Tests for /push-to-do rework and Dispatch plan_file field."""

from __future__ import annotations

import json

from consilium.plan.dispatch import read_dispatch, write_dispatch
from consilium.plan.models import DispatchAction


class TestWriteDispatch:
    def test_includes_plan_file(self, tmp_path) -> None:
        dispatch = write_dispatch(
            plan_id="test-plan",
            target_phase="phase-01",
            plan_file="plan/index.md",
            action=DispatchAction.START_IMPLEMENT,
        )
        assert dispatch.plan_file == "plan/index.md"
        assert dispatch.plan_id == "test-plan"
        assert dispatch.target_phase == "phase-01"
        assert dispatch.action == DispatchAction.START_IMPLEMENT

    def test_plan_file_none_when_not_provided(self, tmp_path) -> None:
        dispatch = write_dispatch(
            plan_id="test-plan",
            target_phase="phase-01",
            action=DispatchAction.START_REVIEW,
        )
        assert dispatch.plan_file is None


class TestReadDispatch:
    def test_reads_plan_file(self, tmp_path) -> None:
        # Create a temporary dispatch file
        dispatch_path = tmp_path / "dispatch.json"
        data = {
            "dispatch_id": "disp_test",
            "plan_id": "test",
            "plan_file": str(tmp_path / "plan" / "index.md"),
            "action": "start_implement",
            "target_phase": "phase-01",
            "dispatched_at": 1716854400.0,
            "dispatched_by": "think",
            "require_user_approval": True,
            "afk_mode": False,
        }
        dispatch_path.write_text(json.dumps(data), encoding="utf-8")

        # The plan_file in data points to a non-existent path, so it should raise
        result = read_dispatch(dispatch_path)
        # read_dispatch catches exceptions and returns None
        assert result is None

    def test_reads_valid_plan_file(self, tmp_path) -> None:
        plan_file = tmp_path / "plan" / "index.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("# Plan\n", encoding="utf-8")

        dispatch_path = tmp_path / "dispatch.json"
        data = {
            "dispatch_id": "disp_test",
            "plan_id": "test",
            "plan_file": str(plan_file),
            "action": "start_implement",
            "target_phase": "phase-01",
            "dispatched_at": 1716854400.0,
            "dispatched_by": "think",
            "require_user_approval": True,
            "afk_mode": False,
        }
        dispatch_path.write_text(json.dumps(data), encoding="utf-8")

        result = read_dispatch(dispatch_path)
        assert result is not None
        assert result.plan_file == str(plan_file)


class TestDispatchModel:
    def test_plan_file_field_exists(self) -> None:
        from consilium.plan.models import Dispatch

        dispatch = Dispatch(
            dispatch_id="d1",
            plan_id="p1",
            plan_file="plan/index.md",
            action=DispatchAction.START_IMPLEMENT,
            target_phase="phase-01",
        )
        assert dispatch.plan_file == "plan/index.md"

    def test_plan_file_defaults_to_none(self) -> None:
        from consilium.plan.models import Dispatch

        dispatch = Dispatch(
            dispatch_id="d1",
            plan_id="p1",
            action=DispatchAction.START_REVIEW,
            target_phase="phase-01",
        )
        assert dispatch.plan_file is None
