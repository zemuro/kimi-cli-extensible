"""L1 heuristic audit engine: fast, cheap pre-audit before LLM audit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from kimi_cli.utils.logging import logger

if TYPE_CHECKING:
    from kimi_cli.plan.models import L1AuditResult, Phase, Plan


# Heuristic patterns for testable completion criteria
_TESTABLE_PATTERNS = re.compile(
    r"\b(test|verify|check|pass|regression|coverage|lint|type.?check|benchmark)\b",
    re.IGNORECASE,
)


class AuditRules:
    """Project-local audit rules loaded from .kimi/audit_rules.yaml."""

    def __init__(self, rules_path: Path | None = None) -> None:
        self.anti_patterns: list[dict] = []
        if rules_path is not None and rules_path.exists():
            self._load(rules_path)

    def _load(self, path: Path) -> None:
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.anti_patterns = data.get("anti_patterns", [])
        except ImportError:
            logger.warning("PyYAML not installed; skipping audit_rules.yaml load")
        except Exception as exc:
            logger.warning("Failed to load audit_rules.yaml: {exc}", exc=exc)

    def scan_file(self, file_path: Path) -> list[tuple[str, str, str]]:
        """Scan a file for anti-patterns. Returns list of (name, severity, message)."""
        findings: list[tuple[str, str, str]] = []
        if not file_path.exists():
            return findings
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return findings

        for rule in self.anti_patterns:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            try:
                if re.search(pattern, text):
                    findings.append(
                        (
                            rule.get("name", "unknown"),
                            rule.get("severity", "warning"),
                            rule.get("message", f"Matched pattern: {pattern}"),
                        )
                    )
            except re.error:
                logger.warning("Invalid anti-pattern regex: {pattern}", pattern=pattern)

        return findings


def audit_l1(
    plan: Plan,
    target_phase: Phase,
    work_dir: Path,
    rules_path: Path | None = None,
) -> L1AuditResult:
    """Run L1 heuristic audit on a phase.

    Checks (in order):
    1. File existence (for non-pending phases)
    2. Dependency satisfaction
    3. Completion criteria testability
    4. Anti-patterns in referenced files

    Returns:
        L1AuditResult with passed, hard_fail, flags, and messages.
    """
    from kimi_cli.plan.models import L1AuditResult, L1Flag, L1Severity, PhaseStatus

    flags: list[L1Flag] = []
    messages: list[str] = []
    hard_fail = False

    # 1. File existence check
    if target_phase.status != PhaseStatus.PENDING:
        for file_path in target_phase.files_involved:
            full_path = work_dir / file_path
            if not full_path.exists():
                flag = L1Flag(
                    check="file_existence",
                    severity=L1Severity.ERROR,
                    message=f"Referenced file does not exist: {file_path}",
                )
                flags.append(flag)
                messages.append(flag.message)
                hard_fail = True

    # 2. Dependency satisfaction
    for dep_id in target_phase.dependencies:
        dep_phase = plan.get_phase(dep_id)
        if dep_phase is None:
            flag = L1Flag(
                check="dependency_exists",
                severity=L1Severity.ERROR,
                message=f"Dependency references non-existent phase: {dep_id}",
            )
            flags.append(flag)
            messages.append(flag.message)
            hard_fail = True
            continue
        if dep_phase.status not in (PhaseStatus.IMPLEMENTED, PhaseStatus.APPROVED):
            flag = L1Flag(
                check="dependency_status",
                severity=L1Severity.ERROR,
                message=(
                    f"Dependency {dep_id} has status {dep_phase.status.value}, "
                    "must be implemented or approved"
                ),
            )
            flags.append(flag)
            messages.append(flag.message)
            hard_fail = True

    # 3. Completion criteria testability
    if target_phase.completion_criteria:
        untestable = []
        for criterion in target_phase.completion_criteria:
            if not _TESTABLE_PATTERNS.search(criterion):
                untestable.append(criterion)
        if untestable:
            flag = L1Flag(
                check="completion_criteria_testability",
                severity=L1Severity.WARNING,
                message=(
                    f"{len(untestable)} completion criterion(s) may not be testable: "
                    + "; ".join(untestable)
                ),
            )
            flags.append(flag)
            messages.append(flag.message)
    else:
        # Empty completion criteria is a warning, not a hard fail
        flag = L1Flag(
            check="completion_criteria_empty",
            severity=L1Severity.WARNING,
            message="No completion criteria specified for this phase",
        )
        flags.append(flag)
        messages.append(flag.message)

    # 4. Anti-patterns in referenced files
    rules = AuditRules(rules_path)
    for file_path in target_phase.files_involved:
        full_path = work_dir / file_path
        findings = rules.scan_file(full_path)
        for name, severity, message in findings:
            flag = L1Flag(
                check=f"anti_pattern:{name}",
                severity=L1Severity(severity),
                message=f"{file_path}: {message}",
            )
            flags.append(flag)
            messages.append(flag.message)

    passed = not flags or all(f.severity != L1Severity.ERROR for f in flags)

    return L1AuditResult(
        passed=passed,
        hard_fail=hard_fail,
        flags=flags,
        messages=messages,
    )
