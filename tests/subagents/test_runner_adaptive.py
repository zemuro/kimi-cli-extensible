"""Tests for the adaptive timeout integration in ForegroundSubagentRunner."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

import pytest

from consilium.subagents.adaptive_timer import AdaptiveTimer
from consilium.subagents.budget_tracker import SubagentBudgetConfig, SubagentBudgetTracker
from consilium.subagents.output import SubagentOutputWriter
from consilium.subagents.runner import ForegroundSubagentRunner, _ProgressState


@pytest.fixture
def dummy_runner() -> ForegroundSubagentRunner:
    """A runner instance whose methods that need no self state can be exercised."""
    return object.__new__(ForegroundSubagentRunner)


@pytest.mark.asyncio
async def test_checkpoint_loop_stops_on_no_progress(
    dummy_runner: ForegroundSubagentRunner, tmp_path: Path
) -> None:
    tracker = SubagentBudgetTracker(
        SubagentBudgetConfig(
            max_tokens_per_task=100_000,
            max_tool_calls_per_task=100,
            warn_tokens_ratio=0.8,
            warn_tool_calls_ratio=0.8,
        )
    )
    state = _ProgressState(tracker)
    output_writer = SubagentOutputWriter(tmp_path / "out.log")
    timer = AdaptiveTimer(
        checkpoint_interval=0.05,
        increments=(1.0,),
        max_wait=10.0,
        no_progress_strikes=2,
    )

    async def slow_task() -> tuple[str | None, None]:
        await asyncio.sleep(100)
        return None, None

    main_task = asyncio.create_task(slow_task())
    checkpoint_task = asyncio.create_task(
        dummy_runner._checkpoint_loop(
            main_task, timer, state, output_writer, "a1"
        )
    )
    done, _pending = await asyncio.wait(
        {main_task, checkpoint_task}, return_when=asyncio.FIRST_COMPLETED
    )

    assert checkpoint_task in done
    stop = checkpoint_task.result()
    assert stop.brief == "Adaptive timeout (no progress)"

    main_task.cancel()
    with suppress(asyncio.CancelledError):
        await main_task


@pytest.mark.asyncio
async def test_checkpoint_loop_extends_while_progressing(
    dummy_runner: ForegroundSubagentRunner, tmp_path: Path
) -> None:
    tracker = SubagentBudgetTracker(
        SubagentBudgetConfig(
            max_tokens_per_task=100_000,
            max_tool_calls_per_task=100,
            warn_tokens_ratio=0.8,
            warn_tool_calls_ratio=0.8,
        )
    )
    state = _ProgressState(tracker)
    output_writer = SubagentOutputWriter(tmp_path / "out.log")
    timer = AdaptiveTimer(
        checkpoint_interval=0.05,
        increments=(1.0,),
        max_wait=0.5,
        no_progress_strikes=2,
    )

    async def task_with_progress() -> tuple[str | None, None]:
        # Produce progress every checkpoint to avoid no-progress stop.
        for _ in range(10):
            state.tracker.record_turn(10)
            await asyncio.sleep(0.03)
        return "done", None

    main_task = asyncio.create_task(task_with_progress())
    checkpoint_task = asyncio.create_task(
        dummy_runner._checkpoint_loop(
            main_task, timer, state, output_writer, "a1"
        )
    )
    done, _pending = await asyncio.wait(
        {main_task, checkpoint_task}, return_when=asyncio.FIRST_COMPLETED
    )

    # Main task should finish before the checkpoint loop stops it.
    assert main_task in done
    checkpoint_task.cancel()
    with suppress(asyncio.CancelledError):
        await checkpoint_task

    result, _failure = main_task.result()
    assert result == "done"


@pytest.mark.asyncio
async def test_checkpoint_loop_stops_at_max_wait(
    dummy_runner: ForegroundSubagentRunner, tmp_path: Path
) -> None:
    tracker = SubagentBudgetTracker(
        SubagentBudgetConfig(
            max_tokens_per_task=100_000,
            max_tool_calls_per_task=100,
            warn_tokens_ratio=0.8,
            warn_tool_calls_ratio=0.8,
        )
    )
    state = _ProgressState(tracker)
    output_writer = SubagentOutputWriter(tmp_path / "out.log")
    timer = AdaptiveTimer(
        checkpoint_interval=0.05,
        increments=(1.0,),
        max_wait=0.12,
        no_progress_strikes=2,
    )

    async def slow_task() -> tuple[str | None, None]:
        await asyncio.sleep(100)
        return None, None

    main_task = asyncio.create_task(slow_task())
    checkpoint_task = asyncio.create_task(
        dummy_runner._checkpoint_loop(
            main_task, timer, state, output_writer, "a1"
        )
    )
    done, _pending = await asyncio.wait(
        {main_task, checkpoint_task}, return_when=asyncio.FIRST_COMPLETED
    )

    assert checkpoint_task in done
    stop = checkpoint_task.result()
    assert stop.brief == "Adaptive timeout (max wait)"

    main_task.cancel()
    with suppress(asyncio.CancelledError):
        await main_task
