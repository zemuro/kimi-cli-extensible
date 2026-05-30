"""Plan validation: dependency graphs, lock rules, and constraints."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.plan.models import Plan, PlanDirectory


class PlanValidationError(Exception):
    """Raised when a plan violates structural constraints."""

    def __init__(self, message: str, phase_id: str | None = None) -> None:
        self.phase_id = phase_id
        if phase_id:
            message = f"Phase {phase_id}: {message}"
        super().__init__(message)


def validate_plan(
    plan: Plan | PlanDirectory,
    work_dir: Path | None = None,
) -> list[PlanValidationError]:
    """Validate a plan and return all errors found.

    Args:
        plan: The parsed plan to validate.
        work_dir: Optional working directory for checking file existence.

    Returns:
        List of validation errors (empty if plan is valid).
    """
    from kimi_cli.plan.models import PhaseStatus

    errors: list[PlanValidationError] = []
    phase_ids = set(plan.phase_ids)

    # Build dependency graph
    deps: dict[str, list[str]] = {}
    for phase in plan.phases:
        deps[phase.phase_id] = phase.dependencies

    # Check 1: Circular dependencies
    cycles = _find_cycles(deps)
    for cycle in cycles:
        errors.append(
            PlanValidationError(
                f"Circular dependency detected: {' → '.join(cycle)}",
                phase_id=cycle[0],
            )
        )

    # Check 2: All dependencies reference existing phases
    for phase in plan.phases:
        for dep in phase.dependencies:
            if dep not in phase_ids:
                errors.append(
                    PlanValidationError(
                        f"Dependency references non-existent phase: {dep}",
                        phase_id=phase.phase_id,
                    )
                )

    # Check 3: Lock rules
    for phase in plan.phases:
        if phase.status == PhaseStatus.IMPLEMENTED and not phase.locked:
            errors.append(
                PlanValidationError(
                    "Implemented phases must be locked",
                    phase_id=phase.phase_id,
                )
            )
        if phase.locked and phase.status not in (
            PhaseStatus.IMPLEMENTED,
            PhaseStatus.ABORTED,
        ):
            errors.append(
                PlanValidationError(
                    f"Locked phases must be implemented or aborted, not {phase.status.value}",
                    phase_id=phase.phase_id,
                )
            )

    # Check 4: File existence (if work_dir provided)
    if work_dir is not None:
        for phase in plan.phases:
            # Only check files for non-pending phases
            if phase.status == PhaseStatus.PENDING:
                continue
            for file_path in phase.files_involved:
                full_path = work_dir / file_path
                if not full_path.exists():
                    errors.append(
                        PlanValidationError(
                            f"Referenced file does not exist: {file_path}",
                            phase_id=phase.phase_id,
                        )
                    )

    # Check 5: Dependency status ordering
    for phase in plan.phases:
        for dep_id in phase.dependencies:
            dep_phase = plan.get_phase(dep_id)
            if dep_phase is None:
                continue
            # Dependencies must be implemented or approved
            if dep_phase.status not in (PhaseStatus.IMPLEMENTED, PhaseStatus.APPROVED):
                errors.append(
                    PlanValidationError(
                        f"Dependency {dep_id} has status {dep_phase.status.value}, "
                        "must be implemented or approved",
                        phase_id=phase.phase_id,
                    )
                )

    return errors


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Find all cycles in a directed graph using DFS.

    Returns list of cycles, where each cycle is a list of node IDs.
    """
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def _dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                _dfs(neighbor)
            elif neighbor in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)

        path.pop()
        rec_stack.remove(node)

    for node in graph:
        if node not in visited:
            _dfs(node)

    return cycles
