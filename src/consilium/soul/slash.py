from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from kaos.path import KaosPath
from kosong.message import Message

import consilium.prompts as prompts
from consilium import logger
from consilium.soul import wire_send
from consilium.soul.agent import load_agents_md
from consilium.soul.context import Context
from consilium.soul.dynamic_injections.afk_mode import AFK_DISABLED_REMINDER
from consilium.soul.message import system, system_reminder
from consilium.utils.export import is_sensitive_file
from consilium.utils.path import sanitize_cli_path, shorten_home
from consilium.utils.slashcmd import SlashCommandRegistry
from consilium.wire.types import StatusUpdate, TextPart

if TYPE_CHECKING:
    from consilium.soul.consiliumsoul import ConsiliumSoul

type SoulSlashCmdFunc = Callable[[ConsiliumSoul, str], None | Awaitable[None]]
"""
A function that runs as a ConsiliumSoul-level slash command.

Raises:
    Any exception that can be raised by `Soul.run`.
"""

registry = SlashCommandRegistry[SoulSlashCmdFunc]()


@registry.command
async def init(soul: ConsiliumSoul, args: str):
    """Analyze the codebase and generate an `AGENTS.md` file"""
    from consilium.soul.consiliumsoul import ConsiliumSoul

    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_context = Context(file_backend=Path(temp_dir) / "context.jsonl")
        tmp_soul = ConsiliumSoul(soul.agent, context=tmp_context)
        await tmp_soul.run(prompts.INIT)

    agents_md = await load_agents_md(soul.runtime.builtin_args.CONSILIUM_WORK_DIR)
    system_message = system(Template(prompts.INIT_COMPLETE).substitute(agents_md=agents_md or ""))
    await soul.context.append_message(Message(role="user", content=[system_message]))
    from consilium.telemetry import track

    track("init_complete")


@registry.command
async def compact(soul: ConsiliumSoul, args: str):
    """Compact the context (optionally with a custom focus, e.g. /compact keep db discussions)"""
    if soul.context.n_checkpoints == 0:
        wire_send(TextPart(text="The context is empty."))
        return

    logger.info("Running `/compact`")
    instruction = args.strip()
    await soul.compact_context(manual=True, custom_instruction=instruction)
    wire_send(TextPart(text="The context has been compacted."))
    snap = soul.status
    wire_send(
        StatusUpdate(
            context_usage=snap.context_usage,
            context_tokens=snap.context_tokens,
            max_context_tokens=snap.max_context_tokens,
        )
    )


@registry.command(aliases=["reset"])
async def clear(soul: ConsiliumSoul, args: str):
    """Clear the context"""
    logger.info("Running `/clear`")
    await soul.context.clear()
    await soul.context.write_system_prompt(soul.agent.system_prompt)
    wire_send(TextPart(text="The context has been cleared."))
    snap = soul.status
    wire_send(
        StatusUpdate(
            context_usage=snap.context_usage,
            context_tokens=snap.context_tokens,
            max_context_tokens=snap.max_context_tokens,
        )
    )


@registry.command
async def yolo(soul: ConsiliumSoul, args: str):
    """Toggle YOLO mode (auto-approve all actions)"""
    from consilium.telemetry import track

    # Inspect only the yolo flag: afk is independent and is toggled by /afk.
    if soul.runtime.approval.is_yolo_flag():
        soul.runtime.approval.set_yolo(False)
        track("yolo_toggle", enabled=False)
        if soul.runtime.approval.is_afk():
            # Yolo off but afk still on -> tool calls remain auto-approved.
            # Don't mislead the user into thinking approvals just came back.
            wire_send(
                TextPart(
                    text=(
                        "Yolo disabled, but afk is still on — tool calls remain "
                        "auto-approved. Use /afk to turn off afk."
                    )
                )
            )
        else:
            wire_send(TextPart(text="You only die once! Actions will require approval."))
    else:
        soul.runtime.approval.set_yolo(True)
        track("yolo_toggle", enabled=True)
        wire_send(TextPart(text="You only live once! All actions will be auto-approved."))


@registry.command
async def afk(soul: ConsiliumSoul, args: str):
    """Toggle afk mode (auto-dismiss AskUserQuestion, auto-approve tool calls)"""
    from consilium.telemetry import track

    if soul.runtime.approval.is_afk():
        soul.runtime.approval.set_afk(False)
        await soul.notify_afk_changed(False)
        await soul.context.append_message(
            Message(role="user", content=[system_reminder(AFK_DISABLED_REMINDER)])
        )
        track("afk_toggle", enabled=False)
        if soul.runtime.approval.is_yolo_flag():
            wire_send(
                TextPart(
                    text=("afk mode disabled. You are back at the terminal. Yolo is still on.")
                )
            )
        else:
            wire_send(TextPart(text="afk mode disabled. You are back at the terminal."))
    else:
        soul.runtime.approval.set_afk(True)
        await soul.notify_afk_changed(True)
        track("afk_toggle", enabled=True)
        wire_send(
            TextPart(
                text=(
                    "afk mode enabled. AskUserQuestion will be auto-dismissed "
                    "and tool calls auto-approved."
                )
            )
        )


@registry.command
async def plan(soul: ConsiliumSoul, args: str):
    """Toggle plan mode. Usage: /plan [on|off|view|clear]"""
    subcmd = args.strip().lower()

    if subcmd == "on":
        if not soul.plan_mode:
            await soul.toggle_plan_mode_from_manual()
        plan_path = soul.get_plan_file_path()
        wire_send(TextPart(text=f"Plan mode ON. Plan file: {plan_path}"))
        wire_send(StatusUpdate(plan_mode=soul.plan_mode))
    elif subcmd == "off":
        if soul.plan_mode:
            await soul.toggle_plan_mode_from_manual()
        wire_send(TextPart(text="Plan mode OFF. All tools are now available."))
        wire_send(StatusUpdate(plan_mode=soul.plan_mode))
    elif subcmd == "view":
        content = soul.read_current_plan()
        if content:
            wire_send(TextPart(text=content))
        else:
            wire_send(TextPart(text="No plan file found for this session."))
    elif subcmd == "clear":
        soul.clear_current_plan()
        wire_send(TextPart(text="Plan cleared."))
    else:
        # Default: toggle
        new_state = await soul.toggle_plan_mode_from_manual()
        if new_state:
            plan_path = soul.get_plan_file_path()
            wire_send(
                TextPart(
                    text=f"Plan mode ON. Write your plan to: {plan_path}\n"
                    "Use ExitPlanMode when done, or /plan off to exit manually."
                )
            )
        else:
            wire_send(TextPart(text="Plan mode OFF. All tools are now available."))
        wire_send(StatusUpdate(plan_mode=soul.plan_mode))


@registry.command(name="add-dir")
async def add_dir(soul: ConsiliumSoul, args: str):
    """Add a directory to the workspace. Usage: /add-dir <path>. Run without args to list added dirs"""  # noqa: E501


    args = sanitize_cli_path(args)
    if not args:
        if not soul.runtime.additional_dirs:
            wire_send(TextPart(text="No additional directories. Usage: /add-dir <path>"))
        else:
            lines = ["Additional directories:"]
            for d in soul.runtime.additional_dirs:
                lines.append(f"  - {d}")
            wire_send(TextPart(text="\n".join(lines)))




    path = KaosPath(args).expanduser().canonical()

    if not await path.exists():
        wire_send(TextPart(text=f"Directory does not exist: {path}"))
        return
    if not await path.is_dir():
        wire_send(TextPart(text=f"Not a directory: {path}"))
        return

    # Check if already added (exact match)
    if path in soul.runtime.additional_dirs:
        wire_send(TextPart(text=f"Directory already in workspace: {path}"))
        return

    # Check if it's within the work_dir (already accessible)
    work_dir = soul.runtime.builtin_args.CONSILIUM_WORK_DIR
    if is_within_directory(path, work_dir):
        wire_send(TextPart(text=f"Directory is already within the working directory: {path}"))
        return

    # Check if it's within an already-added additional directory (redundant)
    for existing in soul.runtime.additional_dirs:
        if is_within_directory(path, existing):
            wire_send(
                TextPart(
                    text=f"Directory is already within an added directory `{existing}`: {path}"
                )
            )
            return

    # Validate readability before committing any state changes
    try:
        ls_output = await list_directory(path)
    except OSError as e:
        wire_send(TextPart(text=f"Cannot read directory: {path} ({e})"))
        return

    # Add the directory (only after readability is confirmed)
    soul.runtime.additional_dirs.append(path)

    # Persist to session state
    soul.runtime.session.state.additional_dirs.append(str(path))
    soul.runtime.session.save_state()

    # Inject a system message to inform the LLM about the new directory
    system_message = system(
        Template(prompts.ADD_DIR).substitute(path=str(path), ls_output=ls_output)
    )
    await soul.context.append_message(Message(role="user", content=[system_message]))

    wire_send(TextPart(text=f"Added directory to workspace: {path}"))
    logger.info("Added additional directory: {path}", path=path)


@registry.command
async def export(soul: ConsiliumSoul, args: str):
    """Export current session context to a markdown file"""
    from consilium.utils.export import perform_export

    session = soul.runtime.session
    result = await perform_export(
        history=list(soul.context.history),
        session_id=session.id,
        work_dir=str(session.work_dir),
        token_count=soul.context.token_count,
        args=args,
        default_dir=Path(str(session.work_dir)),
    )
    if isinstance(result, str):
        wire_send(TextPart(text=result))
        return
    output, count = result
    display = shorten_home(KaosPath(str(output)))
    wire_send(TextPart(text=f"Exported {count} messages to {display}"))
    wire_send(
        TextPart(
            text="  Note: The exported file may contain sensitive information. "
            "Please be cautious when sharing it externally."
        )
    )


@registry.command(name="import")
async def import_context(soul: ConsiliumSoul, args: str):
    """Import context from a file or session ID"""
    from consilium.utils.export import perform_import

    target = sanitize_cli_path(args)
    if not target:
        wire_send(TextPart(text="Usage: /import <file_path or session_id>"))
        return

    session = soul.runtime.session
    raw_max_context_size = (
        soul.runtime.llm.max_context_size if soul.runtime.llm is not None else None
    )
    max_context_size = (
        raw_max_context_size
        if isinstance(raw_max_context_size, int) and raw_max_context_size > 0
        else None
    )
    result = await perform_import(
        target=target,
        current_session_id=session.id,
        work_dir=session.work_dir,
        context=soul.context,
        max_context_size=max_context_size,
    )
    if isinstance(result, str):
        wire_send(TextPart(text=result))
        return

    source_desc, content_len = result
    wire_send(TextPart(text=f"Imported context from {source_desc} ({content_len} chars)."))
    if source_desc.startswith("file") and is_sensitive_file(Path(target).name):
        wire_send(
            TextPart(
                text="Warning: This file may contain secrets (API keys, tokens, credentials). "
                "The content is now part of your session context."
            )
        )


class SessionAborted(Exception):
    """Raised when user aborts a Do session."""


@registry.command
async def commit(soul: ConsiliumSoul, args: str) -> None:
    """Create an intermediate git commit with the current changes."""
    from consilium.do.registry import get_do_session

    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    message = args.strip() or f"kimi-do checkpoint at turn {soul._current_turn_index}"
    commit_hash = await do_session.commit(message)
    if commit_hash:
        wire_send(TextPart(text=f"Committed: {commit_hash} — {message}"))
    else:
        wire_send(TextPart(text="Nothing to commit."))


@registry.command
async def abort(soul: ConsiliumSoul, args: str) -> None:
    """Abort the session and revert to the initial git state."""
    from consilium.do.registry import get_do_session, unregister_do_session

    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    wire_send(TextPart(text="Aborting session and reverting changes..."))
    ok = await do_session.abort()
    if ok:
        wire_send(TextPart(text="Reverted to initial state. Session ended."))
    else:
        wire_send(TextPart(text="Abort failed. Check git status manually."))

    unregister_do_session(soul._runtime.session.id)
    raise SessionAborted()


@registry.command
async def status(soul: ConsiliumSoul, args: str) -> None:
    """Show current git status and session versioning info."""
    from consilium.do.registry import get_do_session

    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="Not in Do mode."))
        return

    git_status = do_session.git.status()
    lines = ["[Do Mode Status]"]
    for key, value in git_status.items():
        lines.append(f"  {key}: {value}")

    if do_session.journal:
        diffs = do_session.journal.get_entries("diff")
        lines.append(f"  changes_recorded: {len(diffs)}")

    wire_send(TextPart(text="\n".join(lines)))


@registry.command
async def complete(soul: ConsiliumSoul, args: str) -> None:
    """Mark the current phase as complete.

    Writes a completion report and updates the plan index.
    Usage: /complete [notes]
    """

    from consilium.do.registry import get_do_session
    from consilium.think.plan_synthesis import (
        _update_plan_index_status,
        _write_completion_report,
    )

    do_session = get_do_session(soul._runtime.session.id)
    if not do_session:
        wire_send(TextPart(text="/complete only works in Do mode."))
        return

    if do_session._phase is None:
        wire_send(TextPart(text="No target phase set. Run with --phase."))
        return

    phase_id = do_session._phase
    plan_file = do_session._plan_file
    notes = args.strip()
    work_dir = do_session.work_dir

    # 1. Write completion report
    report_path = _write_completion_report(plan_file, phase_id, work_dir, notes)

    # 2. Update plan index
    _update_plan_index_status(plan_file, phase_id, status="implemented", locked=True)

    # 3. Store signal in journal
    if do_session.journal is not None:
        do_session.journal.record_phase_complete(
            phase_id=phase_id,
            report_path=str(report_path),
        )

    # 4. Emit completion report to Think inbox (Phase 13)
    do_config = getattr(soul._runtime.config, "do", None)
    if do_config and do_config.enable_reverse_bridge:
        think_session_id = soul._runtime.session.state.paired_session_id
        if think_session_id:
            from consilium.think.inbox import write_report
            report_content = (
                f"# Phase Completion Report: {phase_id}\n\n"
                f"**Status:** Implemented\n"
                f"**Completed at:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Summary:**\n{notes or '(no notes provided)'}\n"
            )
            write_report(
                think_session_id=think_session_id,
                source_session_id=soul._runtime.session.id,
                phase_id=phase_id,
                report_type="completion",
                content=report_content,
            )

    wire_send(TextPart(
        text=f"Phase {phase_id} marked complete.\n"
             f"Report: {report_path}\n"
             f"Plan index updated."
    ))


@registry.command
async def inject(soul: ConsiliumSoul, args: str) -> None:
    """Inject a message into the Do-mode context. Usage: /inject <text> or /inject {"role":"user","content":"..."}"""
    if not args.strip():
        wire_send(TextPart(text="Usage: /inject <text> or /inject {\"role\":\"user\",\"content\":\"...\"}"))
        return

    text = args.strip()
    role = "user"
    content = text

    # Try parsing as JSON
    if text.startswith("{"):
        import json
        try:
            data = json.loads(text)
            role = data.get("role", "user")
            content = data.get("content", "")
        except json.JSONDecodeError:
            pass

    from kosong.message import Message, TextPart
    await soul.context.append_message(Message(role=role, content=[TextPart(text=content)]))
    wire_send(TextPart(text=f"Injected {role} message into context."))
