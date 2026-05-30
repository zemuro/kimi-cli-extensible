"""ThinkSoul — a lightweight Soul implementation for Think mode.

Think mode is a mutable-history REPL for speculative reasoning.
It implements the Soul protocol so it works with all UIs (shell, ACP, wire).
No tools are used; LLM calls go through kosong.generate() directly.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from kosong import generate
from kosong.chat_provider import StreamedMessagePart, TokenUsage
from kosong.message import ContentPart, Message, TextPart, ThinkPart
from kosong.message import Message as KosongMessage

from kimi_cli.config import Config
from kimi_cli.hooks.engine import HookEngine
from kimi_cli.llm import LLM
from kimi_cli.session import Session
from kimi_cli.soul import LLMNotSet, Soul, StatusSnapshot, wire_send
from kimi_cli.think.context import assemble_context, estimate_context_tokens
from kimi_cli.think.history import HistoryManager
from kimi_cli.think.models import ThinkMessage
from kimi_cli.think.slash import get_think_slash_commands, think_registry
from kimi_cli.token_tracker import BudgetExceededError, TokenLogEntry, TokenTracker
from kimi_cli.utils.logging import logger
from kimi_cli.utils.slashcmd import SlashCommand, parse_slash_command_call
from kimi_cli.wire.types import (
    StatusUpdate,
    StepBegin,
    StepInterrupted,
    TurnBegin,
    TurnEnd,
)

_THINK_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "think_system.md"


def _load_system_prompt() -> str:
    if _THINK_SYSTEM_PROMPT_PATH.exists():
        return _THINK_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are a helpful assistant."


# Module-level weak registry for ThinkSoul instances (keyed by session ID)
_think_soul_registry: weakref.WeakValueDictionary[str, ThinkSoul] = weakref.WeakValueDictionary()


def register_think_soul(soul: ThinkSoul) -> None:
    _think_soul_registry[soul._session.id] = soul


def get_think_soul(session_id: str) -> ThinkSoul | None:
    return _think_soul_registry.get(session_id)


class ThinkSoul(Soul):
    """Lightweight Soul for Think mode — mutable history, no tools, wire-compatible."""

    def __init__(
        self,
        session: Session,
        llm: LLM | None,
        config: Config,
        think_session: Any,
        runtime: Any | None = None,
    ) -> None:
        self._session = session
        self._llm = llm
        self._config = config
        self._think_config = config.think
        self._think_session = think_session
        self._history = HistoryManager(think_session)
        self._hook_engine = HookEngine()
        self._system_prompt = _load_system_prompt()
        self._last_usage: TokenUsage | None = None
        self._runtime = runtime
        # Lazy-init spawner when needed
        self._spawner: Any | None = None
        register_think_soul(self)

    # ── Soul Protocol Properties ─────────────────────────────────────────

    @property
    def name(self) -> str:
        return "think"

    @property
    def model_name(self) -> str:
        return self._llm.model_name if self._llm else ""

    @property
    def model_capabilities(self) -> set[Any] | None:
        return self._llm.capabilities if self._llm else None

    @property
    def thinking(self) -> bool | None:
        return None

    @property
    def status(self) -> StatusSnapshot:
        ctx_tokens = estimate_context_tokens(self._think_session, self._system_prompt)
        max_ctx = self._llm.max_context_size if self._llm else 0
        usage = ctx_tokens / max_ctx if max_ctx > 0 else 0.0
        return StatusSnapshot(
            context_usage=usage,
            context_tokens=ctx_tokens,
            max_context_tokens=max_ctx,
        )

    @property
    def hook_engine(self) -> HookEngine:
        return self._hook_engine

    @property
    def available_slash_commands(self) -> list[SlashCommand[Any]]:
        return get_think_slash_commands()

    async def _generate_summary(
        self,
        messages: list[ThinkMessage],
        custom_instruction: str | None = None,
    ) -> str:
        """Generate a summary of messages via the LLM."""
        if self._llm is None:
            raise LLMNotSet()

        # Build a simple user prompt from the messages
        lines = []
        for msg in messages:
            preview = msg.content.replace("\n", " ")[:500]
            lines.append(f"[{msg.role}]: {preview}")
        messages_text = "\n".join(lines)

        prompt = (
            "Summarize the following conversation messages. Preserve all key "
            "decisions, findings, and open questions. Discard conversational filler.\n"
        )
        if custom_instruction:
            prompt += f"\nSpecial focus: {custom_instruction}\n"
        prompt += f"\nMessages to summarize:\n{messages_text}\n\n"
        prompt += "Output a concise paragraph summary (max 400 tokens)."

        result = await generate(
            self._llm.chat_provider,
            system_prompt="",
            tools=[],
            history=[KosongMessage(role="user", content=[TextPart(text=prompt)])],
        )
        return result.message.extract_text()

    async def run_explore(self, prompt: str) -> str:
        """Spawn a foreground explore subagent and return its summary."""
        if self._spawner is None:
            if self._runtime is None:
                raise RuntimeError("Runtime not configured — subagents require a Runtime")
            from kimi_cli.think.subagent_spawner import ThinkSubagentSpawner
            self._spawner = ThinkSubagentSpawner(self._runtime)
        return await self._spawner.explore(prompt)

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def think_session(self) -> Any:
        return self._think_session

    async def run(
        self,
        user_input: str | list[ContentPart],
        *,
        skip_user_prompt_hook: bool = False,
    ) -> None:
        """Process one user turn in Think mode."""
        if self._llm is None:
            raise LLMNotSet()

        # Normalize input
        if isinstance(user_input, list):
            text_input = " ".join(
                p.text for p in user_input if isinstance(p, TextPart)
            )
        else:
            text_input = user_input

        wire_send(TurnBegin(user_input=text_input))

        try:
            # Handle slash commands
            if text_input.startswith("/"):
                await self._handle_slash(text_input)
                wire_send(TurnEnd())
                return

            # Budget check
            self._check_budget()

            # Add user message
            self._history.add_message("user", text_input)

            # Build context and call LLM
            context = assemble_context(self._think_session, self._system_prompt)
            response_text = await self._call_llm(context)

            # Add assistant message
            assistant_msg = self._history.add_message("assistant", response_text)
            if self._last_usage:
                assistant_msg.tokens_in = self._last_usage.input
                assistant_msg.tokens_out = self._last_usage.output

            # Log tokens
            self._log_tokens(assistant_msg)

            # Compaction threshold warning
            self._check_compaction_threshold()

        except asyncio.CancelledError:
            wire_send(StepInterrupted())
            raise
        except BudgetExceededError as exc:
            wire_send(TextPart(text=f"[Budget Exceeded] {exc}"))
        except Exception as exc:
            logger.exception("Think mode error")
            wire_send(TextPart(text=f"[Error] {exc}"))
        finally:
            wire_send(TurnEnd())
            self._send_status()

    # ── Internal ─────────────────────────────────────────────────────────

    async def _call_llm(self, context: list[Message]) -> str:
        """Call kosong.generate with streaming, return assistant text."""
        if self._llm is None:
            raise LLMNotSet()
        wire_send(StepBegin(n=1))

        parts: list[str] = []

        def _on_part(part: StreamedMessagePart) -> None:
            if isinstance(part, TextPart):
                wire_send(part)
                parts.append(part.text)
            elif isinstance(part, ThinkPart):
                # Stream thinking content as text for now
                wire_send(TextPart(text=part.think))
                parts.append(part.think)

        result = await generate(
            self._llm.chat_provider,
            system_prompt="",  # already in context[0]
            tools=[],
            history=context[1:],  # exclude system
            on_message_part=_on_part,
        )

        self._last_usage = result.usage
        return result.message.extract_text()

    def _check_compaction_threshold(self) -> None:
        """Warn user if context usage exceeds compaction threshold."""
        if not getattr(self._think_config, "compaction_enabled", True):
            return
        snap = self.status
        threshold = getattr(self._think_config, "compaction_threshold", 0.75)
        if snap.context_usage >= threshold:
            wire_send(
                TextPart(
                    text=(
                        f"[Context Warning] Usage at {snap.context_usage:.0%} "
                        f"({snap.context_tokens:,} / {snap.max_context_tokens:,} tokens).\n"
                        f"Consider using /compact to summarize older messages.\n"
                        f"Use /compact \"focus instruction\" to customize the summary."
                    )
                )
            )

    def _check_budget(self) -> None:
        """Check token budget before LLM call."""
        budget = self._config.budget_tokens
        if not budget:
            return
        tracker = TokenTracker()
        summary = tracker.get_session_summary(self._session.id)
        burned = cast(int, summary["burned_tokens"])
        if burned >= budget:
            raise BudgetExceededError(
                f"Token budget exceeded: {burned:,} / {budget:,} tokens"
            )
        elif burned >= int(budget * 0.8):
            wire_send(
                TextPart(
                    text=(
                        f"[Budget Warning] {burned:,} / {budget:,} "
                        f"tokens used ({burned / budget:.0%})."
                    )
                )
            )

    def _log_tokens(self, msg: ThinkMessage) -> None:
        """Log token usage to the global tracker."""
        if not self._last_usage:
            return
        tracker = TokenTracker()
        tracker.log(
            TokenLogEntry(
                timestamp=datetime.now(UTC),
                session_id=self._session.id,
                turn_id=msg.id,
                model=self.model_name,
                tokens_in=self._last_usage.input,
                tokens_out=self._last_usage.output,
                active_context=estimate_context_tokens(
                    self._think_session, self._system_prompt
                ),
            )
        )

    async def _handle_slash(self, text: str) -> None:
        """Dispatch a think-mode slash command."""
        call = parse_slash_command_call(text)
        if call is None:
            wire_send(TextPart(text=f"Unknown slash command: {text}"))
            return

        command = think_registry.find_command(call.name)
        if command is None:
            wire_send(TextPart(text=f"Unknown slash command: /{call.name}"))
            return

        try:
            result = command.func(self._history, self._think_session, call.args)
            if isinstance(result, Awaitable):
                result = await result
            if result:
                wire_send(TextPart(text=result))
        except Exception as exc:
            logger.exception("Think slash command error")
            wire_send(TextPart(text=f"[Error] /{call.name}: {exc}"))

    def _send_status(self) -> None:
        """Emit current status to wire."""
        snap = self.status
        wire_send(
            StatusUpdate(
                context_usage=snap.context_usage,
                context_tokens=snap.context_tokens,
                max_context_tokens=snap.max_context_tokens,
                token_usage=self._last_usage,
            )
        )
