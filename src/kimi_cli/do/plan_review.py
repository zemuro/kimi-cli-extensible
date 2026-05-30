"""Plan review gate for Do mode.

Spawns a plan-reviewer subagent to validate plans before execution.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kimi_cli.subagents.runner import ForegroundRunRequest, ForegroundSubagentRunner

if TYPE_CHECKING:
    from kimi_cli.config import DoConfig
    from kimi_cli.soul.agent import Runtime


@dataclass
class PlanReviewReport:
    feasible: bool
    risks: list[str]
    recommendations: list[str]
    questions: list[str]
    summary: str


def _get_git_branch(work_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_git_status(work_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


class PlanReviewer:
    """Spawns a plan-reviewer subagent to validate plans before execution."""

    def __init__(self, root_runtime: Runtime, config: DoConfig) -> None:
        self._runtime = root_runtime
        self._config = config

    def _load_system_prompt(self) -> str:
        custom_path = self._config.plan_review.system_prompt_path
        if custom_path is not None and custom_path.is_file():
            return custom_path.read_text(encoding="utf-8")
        builtin = Path(__file__).parent.parent / "prompts" / "plan_review_system.md"
        if builtin.is_file():
            return builtin.read_text(encoding="utf-8")
        # Fallback inline prompt if file is missing
        return _FALLBACK_SYSTEM_PROMPT

    def _render_user_prompt(self, plan_text: str) -> str:
        template_path = Path(__file__).parent.parent / "prompts" / "plan_review_user.md"
        if template_path.is_file():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = _FALLBACK_USER_TEMPLATE
        work_dir = getattr(self._runtime, "work_dir", None) or Path.cwd()
        return (
            template
            .replace("{{plan_text}}", plan_text)
            .replace("{{work_dir}}", str(work_dir))
            .replace("{{git_branch}}", _get_git_branch(Path(work_dir)))
            .replace("{{git_status}}", _get_git_status(Path(work_dir)))
        )

    async def review(self, plan_text: str) -> PlanReviewReport:
        """Spawn a foreground plan-reviewer subagent and return parsed report."""
        runner = ForegroundSubagentRunner(self._runtime)
        req = ForegroundRunRequest(
            description="Plan review",
            prompt=self._render_user_prompt(plan_text),
            requested_type="plan-reviewer",
            model=self._config.plan_review.model,
            resume=None,
        )
        result = await runner.run(req)
        return self._parse_report(result.output)

    def _parse_report(self, text: str) -> PlanReviewReport:
        """Defensive parsing of structured review text."""
        feasible_match = re.search(r"Feasible:\s*(yes|no)", text, re.IGNORECASE)
        feasible = feasible_match.group(1).lower() == "yes" if feasible_match else False

        risks = self._extract_list(text, "Risks:")
        recommendations = self._extract_list(text, "Recommendations:")
        questions = self._extract_list(text, "Questions:")

        summary_match = re.search(r"Summary:\s*(.+?)(?=\n\n|$)", text, re.DOTALL | re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else text[:500]

        return PlanReviewReport(
            feasible=feasible,
            risks=risks,
            recommendations=recommendations,
            questions=questions,
            summary=summary,
        )

    def _extract_list(self, text: str, header: str) -> list[str]:
        pattern = rf"{re.escape(header)}\s*\n((?:\s*[-*]\s*.+\n?)+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return []
        lines = match.group(1).strip().split("\n")
        return [line.strip().lstrip("-* ").strip() for line in lines if line.strip()]


_FALLBACK_SYSTEM_PROMPT = """\
You are a plan reviewer with full read-only tool access.
Your job is to investigate the codebase and validate a proposed plan
before execution.

## Rules
- Use ReadFile, Grep, Glob, Shell (non-destructive), FetchURL, and SearchWeb to investigate.
- Do NOT write files, patch files, or run destructive commands.
- After investigation, output your review in exactly this format:

Feasible: yes/no
Risks:
- ...
Recommendations:
- ...
Questions:
- ...
Summary: ...

## Investigation strategy
1. Grep for files/symbols mentioned in the plan
2. Read relevant files to verify interfaces and assumptions
3. Check for missing dependencies or prerequisites
4. Verify no conflicting changes exist
"""

_FALLBACK_USER_TEMPLATE = """\
Plan to review:

{{plan_text}}

Current working directory: {{work_dir}}
Git branch: {{git_branch}}
Git status: {{git_status}}
"""
