"""L2 audit engine: wraps PlanReviewer for LLM-powered plan validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from consilium.plan.models import AuditReport

if TYPE_CHECKING:
    from consilium.config import DoConfig
    from consilium.do.plan_review import PlanReviewReport
    from consilium.plan.models import L1AuditResult, Phase, Plan
    from consilium.soul.agent import Runtime


class L2AuditEngine:
    """Runs L2 LLM audit by wrapping the existing PlanReviewer."""

    def __init__(self, root_runtime: Runtime, config: DoConfig) -> None:
        self._runtime = root_runtime
        self._config = config

    async def audit(
        self,
        plan: Plan,
        phase: Phase,
        l1_result: L1AuditResult | None = None,
    ) -> AuditReport:
        """Run an L2 audit on a phase.

        Builds a plan text from the phase description + criteria,
        then delegates to PlanReviewer for investigation.
        """
        from consilium.do.plan_review import PlanReviewer

        plan_text = self._build_plan_text(plan, phase)
        reviewer = PlanReviewer(self._runtime, self._config)
        review: PlanReviewReport = await reviewer.review(plan_text)

        return AuditReport(
            phase_id=phase.phase_id,
            feasible=review.feasible,
            risks=review.risks,
            recommendations=review.recommendations,
            questions=review.questions,
            discoveries=[review.summary],
            l1_result=l1_result,
            l2_used=True,
        )

    @staticmethod
    def _build_plan_text(plan: Plan, phase: Phase) -> str:
        """Construct a plan description text for the reviewer."""
        lines: list[str] = []
        lines.append(f"# Plan: {plan.metadata.plan_id or 'Untitled'}")
        lines.append("")
        lines.append(f"## Phase: {phase.phase_id} — {phase.title}")
        lines.append("")
        lines.append(f"**Status:** {phase.status.value}")
        lines.append(f"**Locked:** {phase.locked}")
        if phase.files_involved:
            lines.append(f"**Files involved:** {', '.join(phase.files_involved)}")
        if phase.dependencies:
            lines.append(f"**Dependencies:** {', '.join(phase.dependencies)}")
        lines.append("")
        if phase.description:
            lines.append("### Description")
            lines.append(phase.description)
            lines.append("")
        if phase.acceptance_criteria:
            lines.append("### Acceptance Criteria")
            for criterion in phase.acceptance_criteria:
                lines.append(f"- {criterion}")
            lines.append("")
        if phase.completion_criteria:
            lines.append("### Completion Criteria")
            for criterion in phase.completion_criteria:
                lines.append(f"- {criterion}")
            lines.append("")
        if phase.risks:
            lines.append("### Known Risks")
            for risk in phase.risks:
                lines.append(f"- {risk}")
            lines.append("")
        return "\n".join(lines)
