"""Tests for the AdaptiveTimer used by foreground subagents and shell."""

from __future__ import annotations

import time

import pytest

from consilium.subagents.adaptive_timer import (
    AdaptiveTimer,
    CheckpointDecision,
    ProgressSnapshot,
)


def test_timer_extends_while_progress_detected() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=1.0, increments=(2.0, 4.0), max_wait=10.0
    )
    timer.start()
    assert timer.remaining_wait() == pytest.approx(2.0, abs=0.1)

    decision = timer.checkpoint(ProgressSnapshot(tokens_burned=10))
    assert decision == CheckpointDecision.EXTEND
    assert timer.remaining_wait() == pytest.approx(4.0, abs=0.1)

    decision = timer.checkpoint(ProgressSnapshot(tokens_burned=20))
    assert decision == CheckpointDecision.EXTEND
    assert timer.remaining_wait() == pytest.approx(8.0, abs=0.1)


def test_timer_caps_at_max_wait() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=1.0, increments=(100.0,), max_wait=10.0
    )
    timer.start()
    decision = timer.checkpoint(ProgressSnapshot(tokens_burned=1))
    assert decision == CheckpointDecision.EXTEND
    assert timer.remaining_wait() == pytest.approx(10.0, abs=0.1)


def test_timer_stops_after_no_progress_strikes() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=0.05,
        increments=(1.0,),
        max_wait=10.0,
        no_progress_strikes=2,
    )
    timer.start()
    # First checkpoint with progress extends.
    assert timer.checkpoint(ProgressSnapshot(tokens_burned=1)) == CheckpointDecision.EXTEND
    # Two no-progress checkpoints trigger stop.
    assert timer.checkpoint(ProgressSnapshot(tokens_burned=1)) == CheckpointDecision.EXTEND
    assert timer.checkpoint(ProgressSnapshot(tokens_burned=1)) == CheckpointDecision.NO_PROGRESS


def test_timer_stops_at_max_wait() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=0.05, increments=(1.0,), max_wait=0.1
    )
    timer.start()
    time.sleep(0.12)
    assert timer.checkpoint(ProgressSnapshot()) == CheckpointDecision.MAX_WAIT_REACHED


def test_timer_cancel_forces_stop() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=1.0, increments=(10.0,), max_wait=100.0
    )
    timer.start()
    timer.cancel()
    assert timer.checkpoint(ProgressSnapshot(tokens_burned=1)) == CheckpointDecision.NO_PROGRESS


def test_timer_detects_any_progress_dimension() -> None:
    timer = AdaptiveTimer(
        checkpoint_interval=1.0, increments=(2.0,), max_wait=10.0
    )
    timer.start()
    prev = ProgressSnapshot()
    for curr in [
        ProgressSnapshot(tokens_burned=1),
        ProgressSnapshot(tool_calls_made=1),
        ProgressSnapshot(wire_message_count=1),
        ProgressSnapshot(output_writes=1),
    ]:
        assert timer.checkpoint(curr) == CheckpointDecision.EXTEND
        # Reset so the next dimension also counts as progress.
        timer._last_snapshot = prev
        timer._strikes = 0
