"""Thin wrapper for spawning subagents from Think mode."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from kimi_cli.subagents.runner import ForegroundRunRequest, ForegroundSubagentRunner
from kimi_cli.utils.logging import logger

if TYPE_CHECKING:
    from kimi_cli.soul.agent import Runtime


class ThinkSubagentSpawner:
    """Spawns explore subagents from Think mode.

    Foreground (/explore) blocks until completion.
    Background (/investigate) is fire-and-forget with notification delivery.
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
        return result.output

    async def investigate(self, question: str, angles: list[str]) -> list[str]:
        """Spawn parallel background subagents, one per angle.

        NOTE: Background tasks are fire-and-forget with notification delivery.
        Result collection requires polling the background task store or waiting
        for notifications. This is significantly more complex than foreground.
        Consider deferring /investigate until /explore is proven working.
        """
        views = []
        for angle in angles:
            view = self._runtime.background_tasks.create_agent_task(
                agent_id=f"think-investigate-{uuid.uuid4().hex[:8]}",
                subagent_type="explore",
                prompt=f"{question}\n\nFocus on this angle: {angle}",
                description=f"Investigate: {angle[:40]}",
                tool_call_id="",  # Not spawned from a tool call
                model_override=None,
            )
            views.append(view)

        # TODO: Concrete result collection strategy
        # For now, return empty list — caller must poll views manually
        logger.warning(
            "/investigate spawned {count} background tasks "
            "but result collection is not yet implemented",
            count=len(views),
        )
        return []
