"""Types and utilities for /investigate background subagent tasks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InvestigationResult:
    task_id: str
    angle: str
    status: str
    summary: str
    output: str


@dataclass(slots=True)
class InvestigateResult:
    question: str
    angles: list[str]
    results: list[InvestigationResult]
    report: str
