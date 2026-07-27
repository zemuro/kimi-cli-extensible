"""ThinkSoul — a lightweight Soul implementation for Think mode.

Think mode is a mutable-history REPL for speculative reasoning.
It implements the Soul protocol so it works with all UIs (shell, ACP, wire).
LLM calls go through kosong.generate() directly. When a Runtime is available,
the `spawn_subagent` tool is registered so Think mode can dispatch subagents.
"""

from __future__ import annotations

import asyncio
import re
import uuid
import weakref
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from kosong import generate
from kosong.chat_provider import StreamedMessagePart, TokenUsage
from kosong.message import ContentPart, Message, TextPart, ThinkPart, ToolCall
from kosong.message import Message as KosongMessage
from kosong.tooling import Tool, ToolError, ToolOk, ToolResult

from consilium.config import Config
from consilium.hooks.engine import HookEngine
from consilium.llm import LLM
from consilium.session import Session
from consilium.soul import LLMNotSet, Soul, StatusSnapshot, wire_send
from consilium.soul.message import tool_result_to_message
import sys
from consilium.utils.logging import logger

def _debug(msg: str) -> None:
    print(f"[THINKSOUL] {msg}", file=sys.stderr, flush=True)
    # Also write to a temp file for debugging since stderr might be swallowed on Windows
    try:
        with open(r"C:\Users\zemuro\think_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[THINKSOUL] {msg}\n")
    except Exception:
        pass
from consilium.think.context import assemble_context, estimate_context_tokens
from consilium.think.history import HistoryManager
from consilium.think.models import ThinkMessage
from consilium.think.slash import get_think_slash_commands, think_registry
from consilium.token_tracker import BudgetExceededError, TokenLogEntry, TokenTracker
from consilium.utils.logging import logger
from consilium.utils.slashcmd import SlashCommand, parse_slash_command_call
from consilium.wire.types import (
    StatusUpdate,
    StepBegin,
    StepInterrupted,
    TurnBegin,
    TurnEnd,
)
from consilium.wire.types import (
    ToolCall as WireToolCall,
    ToolCallPart,
)

_THINK_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "think_system.md"


def _load_system_prompt() -> str:
    if _THINK_SYSTEM_PROMPT_PATH.exists():
        return _THINK_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are a helpful assistant."


# Tool definition for spawning subagents from Think mode
_SPAWN_SUBAGENT_TOOL = Tool(
    name="spawn_subagent",
    description="Spawn a subagent to read files, explore code, or edit plan documents.",
    parameters={
        "type": "object",
        "properties": {
            "subagent_type": {
                "type": "string",
                "enum": ["explore", "plan_editor", "investigate"],
                "description": "Type of subagent to spawn: explore (read-only research), plan_editor (edit plan/), or investigate (parallel research).",
            },
            "prompt": {
                "type": "string",
                "description": "Specific task description for the subagent.",
            },
            "angles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional investigation angles; use only with subagent_type='investigate'.",
            },
        },
        "required": ["subagent_type", "prompt"],
    },
)


# The model is currently conditioned to emit subagent calls as plain-text
# <function=spawn_subagent>{...}</function> blocks instead of using the native
# tool-calling channel. Detect that shape and normalize it to a real ToolCall.
_PLAINTEXT_SPAWN_SUBAGENT_RE = re.compile(
    r"<function=spawn_subagent>\s*(\{.*?\})\s*</function>",
    re.DOTALL | re.IGNORECASE,
)

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
        system_prompt: str | None = None,
    ) -> None:
        self._session = session
        self._llm = llm
        self._config = config
        self._think_config = config.think
        self._think_session = think_session
        self._history = HistoryManager(think_session, work_dir=Path(session.work_dir.unsafe_to_local_path()) if session.work_dir else None)
        self._hook_engine = HookEngine()
        self._system_prompt = system_prompt if system_prompt is not None else _load_system_prompt()
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
            from consilium.think.subagent_spawner import ThinkSubagentSpawner

            self._spawner = ThinkSubagentSpawner(self._runtime)
        return await self._spawner.explore(prompt)

    async def run_plan_edit(self, prompt: str) -> str:
        """Spawn a foreground plan_editor subagent and return its summary."""
        if self._spawner is None:
            if self._runtime is None:
                raise RuntimeError("Runtime not configured — subagents require a Runtime")
            from consilium.think.subagent_spawner import ThinkSubagentSpawner

            self._spawner = ThinkSubagentSpawner(self._runtime)
        return await self._spawner.plan_edit(prompt)

    async def run_investigate(self, question: str, angles: list[str]) -> str:
        """Spawn parallel background investigations and return a unified report."""
        if self._spawner is None:
            if self._runtime is None:
                raise RuntimeError("Runtime not configured — subagents require a Runtime")
            from consilium.think.subagent_spawner import ThinkSubagentSpawner

            self._spawner = ThinkSubagentSpawner(self._runtime)
        result = await self._spawner.investigate(question, angles)
        return result.report

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
            text_input = " ".join(p.text for p in user_input if isinstance(p, TextPart))
            # If the input contains only non-text parts (e.g. images), avoid
            # creating an empty user message that the API will reject.
            if not text_input.strip() and any(not isinstance(p, TextPart) for p in user_input):
                text_input = "[attached media]"
        else:
            text_input = user_input

        wire_send(TurnBegin(user_input=text_input))

        try:
            # Handle slash commands
            if text_input.startswith("/"):
                self._history.add_message("user", text_input)
                result_text = await self._handle_slash_and_get_result(text_input)
                if result_text:
                    self._history.add_message("assistant", result_text)
                wire_send(TurnEnd())
                return

            # Budget check
            self._check_budget()

            # Add user message
            self._history.add_message("user", text_input)

            # Refresh OAuth tokens on each turn to avoid idle-time expirations.
            if self._runtime and hasattr(self._runtime, "oauth") and self._runtime.oauth:
                await self._runtime.oauth.ensure_fresh(self._runtime)

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
        """Call kosong.generate with streaming and tool support, return assistant text."""
        if self._llm is None:
            raise LLMNotSet()
        wire_send(StepBegin(n=1))

        parts: list[str] = []

        def _on_part(part: StreamedMessagePart) -> None:
            _debug(f"_on_part: type={type(part).__name__}")
            if isinstance(part, TextPart):
                wire_send(part)
                parts.append(part.text)
            elif isinstance(part, ThinkPart):
                # Emit actual ThinkPart to wire so UI renders it as thinking
                wire_send(part)
                parts.append(f"<thinking>\n{part.think}\n</thinking>\n")
            elif isinstance(part, ToolCall):
                # Buffer tool call during streaming, emit complete version in _on_tool_call
                _debug(f"_on_part: ToolCall id={part.id} name={part.function.name}")
                parts.append(f"<tool_call>\n{part.function.name}\n</tool_call>\n")
            elif isinstance(part, ToolCallPart):
                # Don't emit ToolCallPart over wire — wait for complete ToolCall in _on_tool_call
                pass

        def _on_tool_call(tool_call: ToolCall) -> None:
            # Emit tool call to wire so UI renders it as a tool call card
            _debug(f"_on_tool_call: id={tool_call.id} name={tool_call.function.name}")
            wire_send(WireToolCall(id=tool_call.id, function=tool_call.function))

        # Use subagent tool only when runtime is available
        tools: list[Tool] = [_SPAWN_SUBAGENT_TOOL] if self._runtime is not None else []

        _debug(f"_call_llm: tools_count={len(tools)}")

        result = await generate(
            self._llm.chat_provider,
            system_prompt=self._system_prompt,
            tools=tools,
            history=context[1:],  # exclude system
            on_message_part=_on_part,
            on_tool_call=_on_tool_call,
        )

        self._last_usage = result.usage

        _debug(f"_call_llm: has_tool_calls={bool(result.message.tool_calls)} tool_count={len(result.message.tool_calls) if result.message.tool_calls else 0}")

        # Handle native tool calls
        if result.message.tool_calls:
            assistant_text = result.message.extract_text()
            self._history.add_message("assistant", assistant_text)

            # Execute tools
            tool_results = await self._execute_tool_calls(result.message.tool_calls)

            # Emit tool results to wire so UI updates tool card status
            for tr in tool_results:
                wire_send(tr)

            # Build tool result messages and extend context
            tool_messages = [tool_result_to_message(tr) for tr in tool_results]
            new_context = context + [result.message] + tool_messages

            # Re-call LLM with tool results
            return await self._call_llm(new_context)

        # Normalize plain-text pseudo-tool calls to real ToolCalls. The model is
        # currently emitting these instead of using the native tool channel.
        response_text = result.message.extract_text()
        fallback_tool_call = self._maybe_extract_plaintext_tool_call(response_text)
        if fallback_tool_call is not None:
            _debug(f"_call_llm: normalized plaintext tool_call id={fallback_tool_call.id}")
            cleaned_text = self._strip_plaintext_tool_call(response_text)
            self._history.add_message("assistant", cleaned_text or "[spawned subagent]")
            wire_send(WireToolCall(id=fallback_tool_call.id, function=fallback_tool_call.function))
            tool_results = await self._execute_tool_calls([fallback_tool_call])
            for tr in tool_results:
                wire_send(tr)
            synthetic_msg = Message(
                role="assistant",
                content=cleaned_text or "",
                tool_calls=[fallback_tool_call],
            )
            tool_messages = [tool_result_to_message(tr) for tr in tool_results]
            new_context = context + [synthetic_msg] + tool_messages
            return await self._call_llm(new_context)

        return response_text

    def _maybe_extract_plaintext_tool_call(self, text: str) -> ToolCall | None:
        """Detect plain-text <function=spawn_subagent> tags and convert to a ToolCall."""
        import json

        match = _PLAINTEXT_SPAWN_SUBAGENT_RE.search(text)
        if not match:
            return None
        raw_json = match.group(1)
        try:
            args = json.loads(raw_json)
        except json.JSONDecodeError:
            _debug(f"plaintext tool_call JSON decode failed: {raw_json[:200]!r}")
            return None
        return ToolCall(
            id=str(uuid.uuid4()),
            function=ToolCall.FunctionBody(
                name="spawn_subagent",
                arguments=json.dumps(args),
            ),
        )

    def _strip_plaintext_tool_call(self, text: str) -> str:
        """Remove the plain-text <function=spawn_subagent> block from the response."""
        cleaned = _PLAINTEXT_SPAWN_SUBAGENT_RE.sub("", text)
        return "\n".join(line for line in cleaned.splitlines() if line.strip()).strip()

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute a list of tool calls in parallel and return their results."""
        async def _run_one(tc: ToolCall) -> ToolResult:
            try:
                return await self._execute_single_tool(tc)
            except Exception as exc:
                logger.exception("Think tool execution failed")
                return ToolResult(
                    tool_call_id=tc.id,
                    return_value=ToolError(
                        message=f"Tool execution failed: {exc}",
                        brief="Execution error",
                    ),
                )

        results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
        return list(results)

    async def _execute_single_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call."""
        import json

        # Set current_tool_call context so subagent runner can forward events
        from consilium.soul.toolset import current_tool_call

        token = current_tool_call.set(tool_call)
        try:
            name = tool_call.function.name
            raw_args = tool_call.function.arguments or "{}"
            args = json.loads(raw_args)

            if name == "spawn_subagent":
                subagent_type = args.get("subagent_type", "explore")
                prompt = args.get("prompt", "")
                angles = args.get("angles", [])

                if subagent_type == "explore":
                    output = await self.run_explore(prompt)
                elif subagent_type == "plan_editor":
                    output = await self.run_plan_edit(prompt)
                elif subagent_type == "investigate":
                    result = await self.run_investigate(prompt, angles)
                    output = result
                else:
                    raise ValueError(f"Unknown subagent type: {subagent_type}")

                return ToolResult(
                    tool_call_id=tool_call.id,
                    return_value=ToolOk(output=output),
                )

            raise ValueError(f"Unknown tool: {name}")
        finally:
            current_tool_call.reset(token)

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
                        f'Use /compact "focus instruction" to customize the summary.'
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
            raise BudgetExceededError(f"Token budget exceeded: {burned:,} / {budget:,} tokens")
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
                active_context=estimate_context_tokens(self._think_session, self._system_prompt),
            )
        )

    async def _handle_slash_and_get_result(self, text: str) -> str | None:
        """Dispatch a think-mode slash command and return the result text."""
        call = parse_slash_command_call(text)
        if call is None:
            msg = f"Unknown slash command: {text}"
            wire_send(TextPart(text=msg))
            return msg

        command = think_registry.find_command(call.name)
        if command is None:
            msg = f"Unknown slash command: /{call.name}"
            wire_send(TextPart(text=msg))
            return msg

        try:
            import inspect
            sig = inspect.signature(command.func)
            kwargs = {}
            if 'work_dir' in sig.parameters:
                kwargs['work_dir'] = self._history.work_dir
            result = command.func(self._history, self._think_session, call.args, **kwargs)
            if isinstance(result, Awaitable):
                result = await result
            if result:
                wire_send(TextPart(text=result))
                return result
        except Exception as exc:
            logger.exception("Think slash command error")
            msg = f"[Error] /{call.name}: {exc}"
            wire_send(TextPart(text=msg))
            return msg
        return None

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
