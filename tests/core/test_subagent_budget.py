"""Tests for subagent budget gate (Phase 9)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kosong.chat_provider import TokenUsage

from kimi_cli.config import SubagentBudgetConfig, SubagentsConfig
from kimi_cli.subagents.budget_tracker import BudgetStatus, SubagentBudgetTracker
from kimi_cli.wire.types import SubagentBudgetWarningEvent


class TestBudgetTracker:
    def test_warns_at_80_percent(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=10_000,
            max_tool_calls_per_task=10,
            warn_tokens_ratio=0.8,
            warn_tool_calls_ratio=0.8,
        )
        tracker = SubagentBudgetTracker(config)
        assert tracker.record_turn(7_999) == BudgetStatus.OK
        assert tracker.record_turn(1) == BudgetStatus.WARNING

    def test_warns_once(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=10_000,
            max_tool_calls_per_task=10,
            warn_tokens_ratio=0.5,
            warn_tool_calls_ratio=0.5,
        )
        tracker = SubagentBudgetTracker(config)
        assert tracker.record_turn(5_000) == BudgetStatus.WARNING
        assert tracker.record_turn(1) == BudgetStatus.OK
        assert tracker.record_turn(1) == BudgetStatus.OK

    def test_stops_at_100_percent_tokens(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=1_000,
            max_tool_calls_per_task=10,
            warn_tokens_ratio=1.0,
            warn_tool_calls_ratio=1.0,
        )
        tracker = SubagentBudgetTracker(config)
        assert tracker.record_turn(999) == BudgetStatus.OK
        assert tracker.record_turn(1) == BudgetStatus.EXCEEDED

    def test_stops_at_100_percent_tools(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=10_000,
            max_tool_calls_per_task=10,
            warn_tokens_ratio=1.0,
            warn_tool_calls_ratio=1.0,
        )
        tracker = SubagentBudgetTracker(config)
        for _ in range(9):
            assert tracker.record_tool_call() == BudgetStatus.OK
        assert tracker.record_tool_call() == BudgetStatus.EXCEEDED

    def test_exceeded_sticky(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=1_000,
            max_tool_calls_per_task=10,
        )
        tracker = SubagentBudgetTracker(config)
        tracker.record_turn(1_000)
        assert tracker.exceeded
        assert tracker.record_turn(0) == BudgetStatus.EXCEEDED
        assert tracker.record_tool_call() == BudgetStatus.EXCEEDED

    def test_warning_message(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=10_000,
            max_tool_calls_per_task=10,
            warn_tokens_ratio=0.8,
            warn_tool_calls_ratio=0.8,
        )
        tracker = SubagentBudgetTracker(config, task_name="explore-auth")
        tracker.record_turn(8_000)
        tracker.record_tool_call()
        msg = tracker.warning_message()
        assert "explore-auth" in msg
        assert "8,000 / 10,000" in msg
        assert "1 / 10" in msg

    def test_exceeded_message_tokens(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=1_000,
            max_tool_calls_per_task=10,
        )
        tracker = SubagentBudgetTracker(config, task_name="test")
        tracker.record_turn(1_000)
        msg = tracker.exceeded_message()
        assert "test" in msg
        assert "Tokens: 1,000 / 1,000" in msg
        assert "Partial results available" in msg

    def test_exceeded_message_tools(self) -> None:
        config = SubagentBudgetConfig(
            max_tokens_per_task=10_000,
            max_tool_calls_per_task=5,
        )
        tracker = SubagentBudgetTracker(config, task_name="test")
        for _ in range(5):
            tracker.record_tool_call()
        msg = tracker.exceeded_message()
        assert "Tool calls: 5 / 5" in msg

    def test_properties(self) -> None:
        config = SubagentBudgetConfig()
        tracker = SubagentBudgetTracker(config)
        assert tracker.tokens_burned == 0
        assert tracker.tool_calls_made == 0
        tracker.record_turn(100)
        tracker.record_tool_call()
        assert tracker.tokens_burned == 100
        assert tracker.tool_calls_made == 1


class TestBudgetConfig:
    def test_default_values(self) -> None:
        config = SubagentBudgetConfig()
        assert config.max_tokens_per_task == 20_000
        assert config.max_tool_calls_per_task == 20
        assert config.warn_tokens_ratio == 0.8
        assert config.warn_tool_calls_ratio == 0.8

    def test_nested_in_subagents_config(self) -> None:
        config = SubagentsConfig()
        assert config.budget.max_tokens_per_task == 20_000

    def test_rejects_invalid_ratio_high(self) -> None:
        with pytest.raises(ValueError):
            SubagentBudgetConfig(warn_tokens_ratio=1.5)

    def test_rejects_invalid_ratio_low(self) -> None:
        with pytest.raises(ValueError):
            SubagentBudgetConfig(warn_tokens_ratio=0.05)

    def test_rejects_negative_tokens(self) -> None:
        with pytest.raises(ValueError):
            SubagentBudgetConfig(max_tokens_per_task=-1)

    def test_rejects_zero_tool_calls(self) -> None:
        with pytest.raises(ValueError):
            SubagentBudgetConfig(max_tool_calls_per_task=0)


class TestKimiSoulHooks:
    def test_register_usage_hook(self) -> None:
        from kimi_cli.soul.kimisoul import KimiSoul

        soul = MagicMock(spec=KimiSoul)
        soul._usage_hooks = []

        def hook(usage: TokenUsage) -> None:
            pass

        KimiSoul.register_usage_hook(soul, hook)
        assert hook in soul._usage_hooks

    def test_register_step_gate(self) -> None:
        from kimi_cli.soul.kimisoul import KimiSoul

        soul = MagicMock(spec=KimiSoul)
        soul._step_gates = []

        def gate():
            return None

        KimiSoul.register_step_gate(soul, gate)
        assert gate in soul._step_gates

    def test_usage_hook_called_with_total(self) -> None:
        """Usage hooks receive TokenUsage with .total property."""
        usage = TokenUsage(input_other=100, output=50, input_cache_read=10)
        assert usage.total == 160  # 100 + 50 + 10


class TestBudgetEvent:
    def test_event_fields(self) -> None:
        event = SubagentBudgetWarningEvent(
            task_name="explore-auth",
            tokens_burned=16_000,
            tokens_limit=20_000,
            tool_calls_made=16,
            tool_calls_limit=20,
        )
        assert event.type == "subagent_budget_warning"
        assert event.task_name == "explore-auth"
        assert event.tokens_burned == 16_000
