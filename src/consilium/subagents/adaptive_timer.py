"""Adaptive timer for long-running foreground subagents and shell commands.

The timer samples progress at regular checkpoints and extends the remaining
wait time while the task is still making progress. If no progress is detected
for a configurable number of consecutive checkpoints, or if the absolute
maximum wait time is reached, the timer tells the caller to stop.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _parse_env(
    name: str,
    default: str,
    parser: Callable[[str], T],
    valid: Callable[[T], bool],
) -> tuple[T, bool]:
    """Parse an env var. Returns (value, used_default)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return parser(default), True
    try:
        value = parser(raw)
        if not valid(value):
            logger.warning(
                "Invalid %s=%r (out of range), using default %r", name, raw, default
            )
            return parser(default), True
        return value, False
    except Exception:
        logger.warning("Invalid %s=%r, using default %r", name, raw, default)
        return parser(default), True


class CheckpointDecision(Enum):
    """Decision returned by a progress checkpoint."""

    EXTEND = auto()
    """Progress detected; the caller should continue and wait for the next checkpoint."""

    NO_PROGRESS = auto()
    """No progress detected for too many consecutive checkpoints; stop."""

    MAX_WAIT_REACHED = auto()
    """The absolute maximum wait time has been reached; stop."""


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Progress metrics sampled at a checkpoint."""

    tokens_burned: int = 0
    tool_calls_made: int = 0
    wire_message_count: int = 0
    output_writes: int = 0


class AdaptiveTimer:
    """Extends wait time incrementally while progress is detected.

    The default timer parameters can be overridden via environment variables:
      CONSILIUM_ADAPTIVE_TIMER_CHECKPOINT_INTERVAL_SECONDS
      CONSILIUM_ADAPTIVE_TIMER_NO_PROGRESS_STRIKES
      CONSILIUM_ADAPTIVE_TIMER_MAX_WAIT_SECONDS
      CONSILIUM_ADAPTIVE_TIMER_INCREMENTS_SECONDS
    Invalid or out-of-range values fall back to defaults with a warning.

    Args:
        checkpoint_interval: Seconds between progress checkpoints.
        increments: Additional seconds granted per progress checkpoint. The list
            is consumed left-to-right and the last value is reused.
        max_wait: Absolute maximum seconds to wait, including extensions.
        no_progress_strikes: Consecutive no-progress checkpoints before stopping.
    """

    def __init__(
        self,
        *,
        checkpoint_interval: float = 30.0,
        increments: Sequence[float] = (60.0, 120.0, 300.0),
        max_wait: float = 900.0,
        no_progress_strikes: int = 40,
    ) -> None:
        # Parse environment variable overrides with validation
        _ci, _ = _parse_env(
            "CONSILIUM_ADAPTIVE_TIMER_CHECKPOINT_INTERVAL_SECONDS",
            str(checkpoint_interval),
            float,
            lambda v: 5 <= v <= 600,
        )
        _np, _ = _parse_env(
            "CONSILIUM_ADAPTIVE_TIMER_NO_PROGRESS_STRIKES",
            str(no_progress_strikes),
            int,
            lambda v: 2 <= v <= 100,
        )
        _mw, _ = _parse_env(
            "CONSILIUM_ADAPTIVE_TIMER_MAX_WAIT_SECONDS",
            str(max_wait),
            float,
            lambda v: 10 <= v <= 7200,
        )

        def _parse_increments(raw: str) -> tuple[float, ...]:
            tokens = [t.strip() for t in raw.split(",")]
            tokens = [t for t in tokens if t]
            return tuple(float(t) for t in tokens)

        def _valid_increments(vals: tuple[float, ...]) -> bool:
            return len(vals) > 0 and all(1 <= v <= 3600 for v in vals)

        _inc, _ = _parse_env(
            "CONSILIUM_ADAPTIVE_TIMER_INCREMENTS_SECONDS",
            ",".join(str(i) for i in increments),
            _parse_increments,
            _valid_increments,
        )

        checkpoint_interval = _ci
        no_progress_strikes = _np
        max_wait = _mw
        increments = _inc

        # If a caller only supplied max_wait (e.g., short shell timeout) and an
        # env var raised checkpoint_interval above it, clamp to avoid breaking
        # existing callers that rely on the default checkpoint_interval.
        if checkpoint_interval > max_wait:
            logger.warning(
                "checkpoint_interval %s exceeds max_wait %s; clamping to max_wait",
                checkpoint_interval,
                max_wait,
            )
            checkpoint_interval = max_wait

        if checkpoint_interval <= 0:
            raise ValueError("checkpoint_interval must be positive")
        if not increments:
            raise ValueError("increments must not be empty")
        if any(i <= 0 for i in increments):
            raise ValueError("increments must be positive")
        if max_wait < checkpoint_interval:
            raise ValueError("max_wait must be at least the checkpoint_interval")
        if no_progress_strikes < 1:
            raise ValueError("no_progress_strikes must be at least 1")

        self.checkpoint_interval = float(checkpoint_interval)
        self.increments = tuple(float(i) for i in increments)
        self.max_wait = float(max_wait)
        self.no_progress_strikes = no_progress_strikes

        self._start_time: float = 0.0
        self._deadline: float = 0.0
        self._last_snapshot: ProgressSnapshot | None = None
        self._strikes: int = 0
        self._increment_index: int = 0
        self._cancelled: bool = False

    def start(self) -> None:
        """Reset and start the timer."""
        self._start_time = time.monotonic()
        self._deadline = self._start_time + min(self.increments[0], self.max_wait)
        self._last_snapshot = None
        self._strikes = 0
        self._increment_index = 0
        self._cancelled = False

    def cancel(self) -> None:
        """Mark the timer as cancelled so the next checkpoint stops."""
        self._cancelled = True

    def checkpoint(self, snapshot: ProgressSnapshot) -> CheckpointDecision:
        """Evaluate progress and decide whether to continue.

        The caller is responsible for waiting the appropriate interval before
        calling this method. The method is synchronous and safe to call from
        an async loop.
        """
        now = time.monotonic()
        if self._cancelled:
            return CheckpointDecision.NO_PROGRESS
        if now >= self._start_time + self.max_wait:
            return CheckpointDecision.MAX_WAIT_REACHED

        has_progress = self._last_snapshot is None or self._detect_progress(
            self._last_snapshot, snapshot
        )
        if has_progress:
            self._strikes = 0
            increment = self.increments[
                min(self._increment_index, len(self.increments) - 1)
            ]
            self._increment_index = min(
                self._increment_index + 1, len(self.increments) - 1
            )
            self._deadline = min(
                self._deadline + increment, self._start_time + self.max_wait
            )
        else:
            self._strikes += 1
            if self._strikes >= self.no_progress_strikes:
                return CheckpointDecision.NO_PROGRESS

        self._last_snapshot = snapshot
        return CheckpointDecision.EXTEND

    def remaining_wait(self) -> float:
        """Seconds remaining until the current deadline.

        The caller should wait for at most ``min(remaining_wait(), checkpoint_interval)``
        before taking the next checkpoint.
        """
        return max(0.0, self._deadline - time.monotonic())

    def elapsed(self) -> float:
        """Seconds elapsed since ``start()`` was called."""
        if self._start_time == 0.0:
            return 0.0
        return time.monotonic() - self._start_time

    @staticmethod
    def _detect_progress(prev: ProgressSnapshot, curr: ProgressSnapshot) -> bool:
        return (
            curr.tokens_burned > prev.tokens_burned
            or curr.tool_calls_made > prev.tool_calls_made
            or curr.wire_message_count > prev.wire_message_count
            or curr.output_writes > prev.output_writes
        )
