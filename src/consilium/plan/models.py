"""Pydantic models for plan-driven Think/Do orchestration."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class PhaseStatus(str, Enum):
    PLANNING = "planning"
    READY = "ready"
    IMPLEMENTED = "implemented"
    ABORTED = "aborted"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class Phase(BaseModel):
    """A single phase in a plan."""

    phase_id: str
    title: str
    status: PhaseStatus = PhaseStatus.PLANNING
    locked: bool = False
    files_involved: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    known: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


class PlanMetadata(BaseModel):
    """Metadata header for a plan document."""

    plan_id: str = ""
    created: float | None = None
    last_updated: float | None = None


class Plan(BaseModel):
    """A parsed plan document."""

    metadata: PlanMetadata = Field(default_factory=PlanMetadata)
    phases: list[Phase] = Field(default_factory=list)

    def get_phase(self, phase_id: str) -> Phase | None:
        """Look up a phase by its ID."""
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        return None

    @property
    def phase_ids(self) -> list[str]:
        """Return all phase IDs in order."""
        return [p.phase_id for p in self.phases]


class PlanDirectory(BaseModel):
    """A plan split into per-phase documents in a directory."""

    index_path: Path
    metadata: PlanMetadata = Field(default_factory=PlanMetadata)
    phases: list[Phase] = Field(default_factory=list)

    def get_phase(self, phase_id: str) -> Phase | None:
        """Look up a phase by its ID."""
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        return None

    def get_phase_file(self, phase_id: str) -> Path:
        """Return the expected path for a phase document."""
        return self.index_path.parent / f"{phase_id}.md"

    @property
    def phase_ids(self) -> list[str]:
        """Return all phase IDs in order."""
        return [p.phase_id for p in self.phases]


# ---------------------------------------------------------------------------
# Audit models
# ---------------------------------------------------------------------------


class L1Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class L1Flag(BaseModel):
    """A single finding from the L1 heuristic audit."""

    check: str
    severity: L1Severity
    message: str


class L1AuditResult(BaseModel):
    """Result of the L1 heuristic audit."""

    passed: bool = False
    hard_fail: bool = False
    flags: list[L1Flag] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    """Structured audit report for a phase."""

    phase_id: str
    timestamp: float = Field(default_factory=lambda: __import__("time").time())
    feasible: bool = False
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    discoveries: list[str] = Field(default_factory=list)
    l1_result: L1AuditResult | None = None
    l2_used: bool = False


# ---------------------------------------------------------------------------
# Docs index models
# ---------------------------------------------------------------------------


class DocStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    DRAFT = "draft"


class UpdatePolicy(str, Enum):
    THINK_ONLY = "think_only"
    THINK_AND_DO = "think_and_do"
    APPEND_ONLY = "append_only"
    FROZEN = "frozen"


class DocEntry(BaseModel):
    """A single document in the docs index."""

    path: str
    purpose: str = ""
    status: DocStatus = DocStatus.CURRENT
    last_updated: float | None = None
    update_policy: UpdatePolicy = UpdatePolicy.THINK_AND_DO
    owner: Literal["think", "do"] = "think"
    related_phases: list[str] = Field(default_factory=list)
    stale_reason: str | None = None
    superseded_by: str | None = None


class DocsIndex(BaseModel):
    """Machine-readable cache of project documentation."""

    version: float = Field(default_factory=lambda: __import__("time").time())
    documents: list[DocEntry] = Field(default_factory=list)

    def get_relevant_docs(self, phase_id: str) -> list[DocEntry]:
        """Return docs whose related_phases include the given phase."""
        return [d for d in self.documents if phase_id in d.related_phases]

    def get_current_docs(self) -> list[DocEntry]:
        """Return only current (non-stale) documents."""
        return [d for d in self.documents if d.status == DocStatus.CURRENT]


# ---------------------------------------------------------------------------
# Dispatch models
# ---------------------------------------------------------------------------


class DispatchAction(str, Enum):
    START_REVIEW = "start_review"
    START_IMPLEMENT = "start_implement"


class Dispatch(BaseModel):
    """Think → Do dispatch signal."""

    dispatch_id: str
    plan_id: str
    plan_file: str | None = None
    action: DispatchAction
    target_phase: str
    dispatched_at: float = Field(default_factory=lambda: __import__("time").time())
    dispatched_by: Literal["think", "user", "afk_auto"] = "think"
    require_user_approval: bool = True
    afk_mode: bool = False
    think_session_id: str | None = None


# ---------------------------------------------------------------------------
# Handover models
# ---------------------------------------------------------------------------


class CompletedPhaseEntry(BaseModel):
    """A phase completed since the last handover."""

    phase_id: str
    status: PhaseStatus
    key_output: str = ""


class Handover(BaseModel):
    """Session continuity document."""

    from_session: str = ""
    to_session: str = ""
    plan_version: str = ""
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    completed_phases: list[CompletedPhaseEntry] = Field(default_factory=list)
    knowledge_updates: list[str] = Field(default_factory=list)
    active_hypotheses: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recommended_first_action: str = ""
