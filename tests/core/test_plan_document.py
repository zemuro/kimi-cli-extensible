"""Tests for plan document parser and validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from kimi_cli.plan.models import PhaseStatus, PlanMetadata
from kimi_cli.plan.parser import PlanParseError, parse_plan, parse_plan_file
from kimi_cli.plan.validator import PlanValidationError, validate_plan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_plan_text() -> str:
    return """\
# Plan: Refactor Authentication Layer

## Metadata
- **plan_id:** plan_auth_refactor
- **created:** 2026-05-24
- **last_updated:** 2026-05-24

## Phase 1: Extract Token Validation
**status:** implemented
**locked:** true
**files_involved:** src/auth/token.py, src/auth/verify.py
**dependencies:** []

### Description
Move JWT validation logic from verify.py into a dedicated TokenValidator class.

### Acceptance Criteria
- [x] All existing tests pass
- [x] No regressions in token refresh flow

---

## Phase 2: Update Middleware
**status:** approved
**locked:** false
**files_involved:** src/middleware/auth.py
**dependencies:** [phase-1]

### Description
Replace session-cookie checks with TokenValidator calls.

### Completion Criteria
- Middleware tests updated
- Integration tests pass

---

## Phase 3: Add Refresh Token Rotation
**status:** pending
**locked:** false
**files_involved:** src/auth/refresh.py
**dependencies:** [phase-1, phase-2]

### Description
Implement refresh token rotation with secure cookie flags.

### Known
- Need to support secure cookie flags

### Unknown
- Migration strategy for existing sessions
"""


@pytest.fixture
def plan_with_cycle() -> str:
    return """\
# Plan: Broken

## Phase 1: A
**status:** pending
**dependencies:** [phase-2]

### Description
Depends on B.

## Phase 2: B
**status:** pending
**dependencies:** [phase-1]

### Description
Depends on A.
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParsePlan:
    def test_parses_metadata(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        assert plan.metadata.plan_id == "plan_auth_refactor"
        assert plan.metadata.created is not None
        from kimi_cli.utils.timestamp import format_date
        assert format_date(plan.metadata.created) == "2026-05-24"
        assert plan.metadata.last_updated is not None

    def test_parses_phases(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        assert len(plan.phases) == 3

    def test_phase_1_details(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        p1 = plan.phases[0]
        assert p1.phase_id == "phase-1"
        assert p1.title == "Extract Token Validation"
        assert p1.status == PhaseStatus.IMPLEMENTED
        assert p1.locked is True
        assert p1.files_involved == ["src/auth/token.py", "src/auth/verify.py"]
        assert p1.dependencies == []
        assert "JWT validation logic" in p1.description
        assert p1.acceptance_criteria == [
            "All existing tests pass",
            "No regressions in token refresh flow",
        ]

    def test_phase_2_details(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        p2 = plan.phases[1]
        assert p2.phase_id == "phase-2"
        assert p2.title == "Update Middleware"
        assert p2.status == PhaseStatus.APPROVED
        assert p2.locked is False
        assert p2.dependencies == ["phase-1"]
        assert p2.completion_criteria == [
            "Middleware tests updated",
            "Integration tests pass",
        ]

    def test_phase_3_details(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        p3 = plan.phases[2]
        assert p3.phase_id == "phase-3"
        assert p3.status == PhaseStatus.PENDING
        assert p3.dependencies == ["phase-1", "phase-2"]
        assert p3.known == ["Need to support secure cookie flags"]
        assert p3.unknown == ["Migration strategy for existing sessions"]

    def test_empty_plan_raises(self) -> None:
        with pytest.raises(PlanParseError, match="empty"):
            parse_plan("")

    def test_duplicate_phase_raises(self) -> None:
        text = "## Phase 1: A\n\n## Phase 1: B"
        with pytest.raises(PlanParseError, match="Duplicate"):
            parse_plan(text)

    def test_get_phase_by_id(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        assert plan.get_phase("phase-2") is not None
        assert plan.get_phase("phase-2").title == "Update Middleware"
        assert plan.get_phase("nonexistent") is None

    def test_parse_plan_file(self, tmp_path: Path, sample_plan_text: str) -> None:
        plan_path = tmp_path / "plan.md"
        plan_path.write_text(sample_plan_text, encoding="utf-8")
        plan = parse_plan_file(plan_path)
        assert len(plan.phases) == 3


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_valid_plan_no_errors(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        errors = validate_plan(plan)
        assert errors == []

    def test_circular_dependency_detected(self, plan_with_cycle: str) -> None:
        plan = parse_plan(plan_with_cycle)
        errors = validate_plan(plan)
        assert any("Circular" in str(e) for e in errors)

    def test_missing_dependency_detected(self) -> None:
        text = """\
## Phase 1: A
**status:** pending
**dependencies:** [phase-99]
"""
        plan = parse_plan(text)
        errors = validate_plan(plan)
        assert any("non-existent" in str(e) for e in errors)

    def test_implemented_must_be_locked(self) -> None:
        text = """\
## Phase 1: A
**status:** implemented
**locked:** false
"""
        plan = parse_plan(text)
        errors = validate_plan(plan)
        assert any("must be locked" in str(e) for e in errors)

    def test_locked_must_be_implemented_or_aborted(self) -> None:
        text = """\
## Phase 1: A
**status:** pending
**locked:** true
"""
        plan = parse_plan(text)
        errors = validate_plan(plan)
        assert any("Locked phases must be implemented or aborted" in str(e) for e in errors)

    def test_dependency_status_check(self) -> None:
        text = """\
## Phase 1: A
**status:** pending

## Phase 2: B
**status:** approved
**dependencies:** [phase-1]
"""
        plan = parse_plan(text)
        errors = validate_plan(plan)
        # phase-1 is pending, but phase-2 depends on it and is approved
        assert any("must be implemented or approved" in str(e) for e in errors)

    def test_file_existence_check(self, tmp_path: Path) -> None:
        text = """\
## Phase 1: A
**status:** approved
**files_involved:** missing_file.py
"""
        plan = parse_plan(text)
        errors = validate_plan(plan, work_dir=tmp_path)
        assert any("does not exist" in str(e) for e in errors)

    def test_file_existence_skipped_for_pending(self, tmp_path: Path) -> None:
        text = """\
## Phase 1: A
**status:** pending
**files_involved:** missing_file.py
"""
        plan = parse_plan(text)
        errors = validate_plan(plan, work_dir=tmp_path)
        # Pending phases don't require files to exist
        assert not any("does not exist" in str(e) for e in errors)

    def test_phase_ids_property(self, sample_plan_text: str) -> None:
        plan = parse_plan(sample_plan_text)
        assert plan.phase_ids == ["phase-1", "phase-2", "phase-3"]
