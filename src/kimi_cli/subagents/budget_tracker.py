"""Subagent budget tracking: token and tool-call limits."""

from __future__ import annotations

from enum import Enum

from kimi_cli.config import SubagentBudgetConfig


class BudgetStatus(str, Enum):
    """Budget check result."""

    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


class SubagentBudgetTracker:
    """Tracks token and tool-call usage against configured limits.

    Created per subagent task. Thread-safe for single-threaded async use.
    """

    def __init__(self, config: SubagentBudgetConfig, task_name: str = "") -> None:
        self._config = config
        self._task_name = task_name
        self._tokens_burned = 0
        self._tool_calls_made = 0
        self._warned_tokens = False
        self._warned_tools = False
        self._exceeded = False

    def record_turn(self, token_count: int) -> BudgetStatus:
        """Record tokens burned in a single LLM step."""
        self._tokens_burned += token_count
        return self._check()

    def record_tool_call(self) -> BudgetStatus:
        """Record a single tool call execution."""
        self._tool_calls_made += 1
        return self._check()

    def _check(self) -> BudgetStatus:
        """Evaluate current usage against limits."""
        if self._exceeded:
            return BudgetStatus.EXCEEDED

        max_tokens = self._config.max_tokens_per_task
        max_tools = self._config.max_tool_calls_per_task

        if self._tokens_burned >= max_tokens or self._tool_calls_made >= max_tools:
            self._exceeded = True
            return BudgetStatus.EXCEEDED

        warn_tokens = int(max_tokens * self._config.warn_tokens_ratio)
        warn_tools = int(max_tools * self._config.warn_tool_calls_ratio)

        token_warn = self._tokens_burned >= warn_tokens and not self._warned_tokens
        tool_warn = self._tool_calls_made >= warn_tools and not self._warned_tools

        if token_warn or tool_warn:
            if token_warn:
                self._warned_tokens = True
            if tool_warn:
                self._warned_tools = True
            return BudgetStatus.WARNING

        return BudgetStatus.OK

    @property
    def exceeded(self) -> bool:
        """Whether the budget has been exceeded."""
        return self._exceeded

    @property
    def tokens_burned(self) -> int:
        """Total tokens burned so far."""
        return self._tokens_burned

    @property
    def tool_calls_made(self) -> int:
        """Total tool calls made so far."""
        return self._tool_calls_made

    def warning_message(self) -> str:
        """Return a human-readable warning message."""
        return (
            f"[Budget warning] Subagent {self._task_name!r} has used "
            f"{self._tokens_burned:,} / {self._config.max_tokens_per_task:,} tokens "
            f"({self._tokens_burned / self._config.max_tokens_per_task:.0%}) and "
            f"{self._tool_calls_made} / {self._config.max_tool_calls_per_task} tool calls "
            f"({self._tool_calls_made / self._config.max_tool_calls_per_task:.0%})."
        )

    def exceeded_message(self) -> str:
        """Return a human-readable exceeded message."""
        parts = [f"[Budget exceeded] Subagent {self._task_name!r} stopped:"]
        if self._tokens_burned >= self._config.max_tokens_per_task:
            parts.append(
                f"- Tokens: {self._tokens_burned:,} / {self._config.max_tokens_per_task:,} limit"
            )
        if self._tool_calls_made >= self._config.max_tool_calls_per_task:
            parts.append(
                f"- Tool calls: {self._tool_calls_made} / "
                f"{self._config.max_tool_calls_per_task} limit"
            )
        parts.append(
            "\nPartial results available. Use a narrower query, "
            "or increase limits in config: [subagents.budget]"
        )
        return "\n".join(parts)
