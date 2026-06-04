"""Thin wrapper for spawning subagents from Think mode."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from consilium.subagents.runner import ForegroundRunRequest, ForegroundSubagentRunner
from consilium.think.investigate import InvestigationResult, InvestigateResult
from consilium.utils.logging import logger

if TYPE_CHECKING:
    from consilium.soul.agent import Runtime


class ThinkSubagentSpawner:
    """Spawns explore subagents from Think mode.

    Foreground (/explore) blocks until completion.
    Background (/investigate) fires parallel tasks and aggregates results.
    """

    def __init__(self, root_runtime: Runtime) -> None:
        self._runtime = root_runtime

    async def explore(self, prompt: str, timeout: int = 300) -> str:
        """Foreground deep-dive. Blocks until completion. Returns summary."""
        runner = ForegroundSubagentRunner(self._runtime)
        req = ForegroundRunRequest(
            description="Think explore",
            prompt=prompt,
            requested_type="explore",
            model=None,
            resume=None,
        )
        result = await asyncio.wait_for(runner.run(req), timeout=timeout)
        if result.is_error:
            return f"[Explore Failed] {result.message}"

        if isinstance(result.output, str):
            return result.output
        elif isinstance(result.output, list):
            return " ".join(getattr(p, "text", "") for p in result.output)
        return str(result.output)

    async def investigate(self, question: str, angles: list[str]) -> InvestigateResult:
        """Spawn parallel background subagents, one per angle, and collect results."""
        if not angles:
            angles = await self._generate_angles(question)

        # Cap angles to prevent runaway token usage
        max_tasks = getattr(self._runtime.config.background, "max_running_tasks", 4)
        angles = angles[: min(3, max_tasks)]

        # Map task_id -> angle
        task_angles: dict[str, str] = {}
        task_ids: list[str] = []

        for angle in angles:
            view = self._runtime.background_tasks.create_agent_task(
                agent_id=f"think-investigate-{uuid.uuid4().hex[:8]}",
                subagent_type="explore",
                prompt=f"{question}\n\nFocus on this angle: {angle}",
                description=f"Investigate: {angle[:40]}",
                tool_call_id="",
                model_override=None,
            )
            task_ids.append(view.spec.id)
            task_angles[view.spec.id] = angle

        # Collect results from all tasks
        results: list[InvestigationResult] = []
        for task_id in task_ids:
            angle = task_angles[task_id]
            try:
                final_view = await self._runtime.background_tasks.wait(
                    task_id,
                    timeout_s=self._runtime.config.background.agent_task_timeout_s,
                )
                output = self._runtime.background_tasks.tail_output(task_id)

                try:
                    from consilium.background.summary import format_task

                    summary = format_task(final_view)
                except ImportError:
                    summary = f"Task {task_id}: {final_view.runtime.status}"

                results.append(
                    InvestigationResult(
                        task_id=task_id,
                        angle=angle,
                        status=final_view.runtime.status,
                        summary=summary,
                        output=output,
                    )
                )
            except (TimeoutError, asyncio.TimeoutError):
                results.append(
                    InvestigationResult(
                        task_id=task_id,
                        angle=angle,
                        status="timeout",
                        summary="Investigation timed out",
                        output="",
                    )
                )
                await self._runtime.background_tasks.kill(task_id, reason="timeout")
            except Exception as e:
                results.append(
                    InvestigationResult(
                        task_id=task_id,
                        angle=angle,
                        status="error",
                        summary=f"Investigation failed: {e}",
                        output="",
                    )
                )

        report = self._aggregate_results(question, results)
        return InvestigateResult(
            question=question,
            angles=angles,
            results=results,
            report=report,
        )

    async def _generate_angles(self, question: str) -> list[str]:
        """Use the Think runtime's LLM to generate investigation angles."""
        soul = getattr(self._runtime, "soul", None)
        if not soul or not hasattr(soul, "llm"):
            return ["Root cause", "Impact assessment", "Resolution options"]

        prompt = (
            f"Given the question: '{question}',\n"
            "Generate 3-5 specific investigation angles. "
            "Each angle should be a concise phrase (2-6 words). "
            "Return as a JSON array of strings."
        )

        response = ""
        try:
            response = await soul.llm.complete(prompt)
            angles = json.loads(response)
            if isinstance(angles, list) and all(isinstance(a, str) for a in angles):
                return angles
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback: split by lines
        return [line.strip("- ").strip() for line in response.splitlines() if line.strip()][:5]

    def _aggregate_results(self, question: str, results: list[InvestigationResult]) -> str:
        """Aggregate individual investigation results into a unified report."""
        lines = [f"# Investigation: {question}\n"]
        for r in results:
            lines.append(f"\n## {r.angle}\n")
            lines.append(f"**Status:** {r.status}\n")
            if r.summary:
                lines.append(r.summary)
            lines.append("\n")
        return "\n".join(lines)
