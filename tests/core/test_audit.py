"""Tests for L1/L2 audit engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from consilium.plan.audit_l1 import audit_l1
from consilium.plan.models import L1Severity, PhaseStatus
from consilium.plan.parser import parse_plan


PLAN_TEXT = """\
## Phase 1: Foundation
**status:** implemented
**locked:** true
**files_involved:** src/auth/token.py
**dependencies:** []

### Description
Create token validation.

### Completion Criteria
- All tests pass
- No regressions

## Phase 2: Middleware
**status:** ready
**locked:** false
**files_involved:** src/middleware/auth.py
**dependencies:** [phase-1]

### Description
Update middleware.

## Phase 3: Rotation
**status:** planning
**locked:** false
**files_involved:** src/auth/refresh.py
**dependencies:** [phase-1, phase-2]

### Description
Add rotation.
"""


@pytest.fixture
def plan():
    return parse_plan(PLAN_TEXT)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    # Create some files
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "src" / "middleware").mkdir(parents=True)
    (tmp_path / "src" / "auth" / "token.py").write_text("# token")
    (tmp_path / "src" / "middleware" / "auth.py").write_text("# middleware")
    return tmp_path


class TestL1Audit:
    def test_all_pass(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-1")
        result = audit_l1(plan, phase, work_dir)
        assert result.passed is True
        assert result.hard_fail is False

    def test_missing_file_hard_fail(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-3")
        # Make it non-pending so file check runs
        phase.status = PhaseStatus.READY
        # src/auth/refresh.py does not exist
        result = audit_l1(plan, phase, work_dir)
        assert result.hard_fail is True
        assert any(f.check == "file_existence" for f in result.flags)

    def test_pending_skips_file_check(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-3")
        # planning phase should not hard-fail on missing files
        # But it will still fail on dependency status since phase-2 is ready
        result = audit_l1(plan, phase, work_dir)
        # hard_fail should be False because planning skips file existence
        # But dependency check will still flag phase-2 is ready (not implemented)
        # Actually phase-2 is ready, which is acceptable for dependencies
        assert result.hard_fail is False

    def test_dependency_not_satisfied(self, plan, work_dir: Path) -> None:
        # Change phase-1 to planning so phase-2's dependency is unsatisfied
        plan.phases[0].status = PhaseStatus.PLANNING
        phase = plan.get_phase("phase-2")
        result = audit_l1(plan, phase, work_dir)
        assert result.hard_fail is True
        assert any(f.check == "dependency_status" for f in result.flags)

    def test_empty_completion_criteria_warning(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-2")
        # phase-2 has no completion criteria
        result = audit_l1(plan, phase, work_dir)
        assert any(f.check == "completion_criteria_empty" for f in result.flags)
        assert any(f.severity == L1Severity.WARNING for f in result.flags)

    def test_untestable_completion_criteria(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-1")
        # Modify to have an untestable criterion
        phase.completion_criteria = ["Make it good", "All tests pass"]
        result = audit_l1(plan, phase, work_dir)
        assert any(f.check == "completion_criteria_testability" for f in result.flags)

    def test_missing_dependency_phase(self, plan, work_dir: Path) -> None:
        phase = plan.get_phase("phase-2")
        phase.dependencies = ["phase-99"]
        result = audit_l1(plan, phase, work_dir)
        assert result.hard_fail is True
        assert any(f.check == "dependency_exists" for f in result.flags)
