"""Slash commands for Think mode."""

from __future__ import annotations

from typing import Any

from consilium.think.history import HistoryManager
from consilium.think.models import ThinkSession
from consilium.think.plan_commands import slash_plan
from consilium.think.push import push_plan_to_do
from consilium.think.storage import list_checkpoints, load_checkpoint, save_checkpoint
from consilium.utils.editor import edit_text_in_editor
from consilium.utils.logging import logger
from consilium.utils.slashcmd import SlashCommand, SlashCommandRegistry

ThinkSlashFunc = Any  # (history: HistoryManager, session: ThinkSession, args: str) -> str | None

think_registry = SlashCommandRegistry[ThinkSlashFunc]()


def _format_history(history: HistoryManager) -> str:
    lines: list[str] = []
    lines.append("# Think Mode History")
    lines.append("")
    for msg in history.session.messages:
        status = " (deleted)" if msg.deleted else ""
        edited = " (edited)" if msg.edited_at else ""
        lines.append(f"**[{msg.role}]** `{msg.id}`{status}{edited}")
        preview = msg.content.replace("\n", " ")[:120]
        lines.append(f"> {preview}")
        lines.append("")
    return "\n".join(lines)


@think_registry.command(name="history", aliases=["h"])
def slash_history(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Show message history with ids."""
    return _format_history(history)


@think_registry.command(name="edit", aliases=["e"])
def slash_edit(history: HistoryManager, session: ThinkSession, args: str) -> str | None:
    """Edit a message by id: /edit msg_abc123"""
    msg_id = args.strip()
    if not msg_id:
        return "Usage: /edit <msg_id>"
    try:
        msg = history.get_message(msg_id)
    except KeyError:
        return f"Message {msg_id} not found."
    edited = edit_text_in_editor(msg.content, configured="")
    if edited is None:
        return "Edit cancelled."
    history.edit_message(msg_id, edited)
    return f"Edited {msg_id}."


@think_registry.command(name="delete", aliases=["d"])
def slash_delete(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Soft-delete a message by id: /delete msg_abc123"""
    msg_id = args.strip()
    if not msg_id:
        return "Usage: /delete <msg_id>"
    try:
        history.delete_message(msg_id)
    except KeyError:
        return f"Message {msg_id} not found."
    return f"Deleted {msg_id}."


@think_registry.command(name="regenerate", aliases=["r"])
def slash_regenerate(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Remove the last assistant message so it can be regenerated."""
    active = history.get_active_messages()
    assistant_msgs = [m for m in active if m.role == "assistant"]
    if not assistant_msgs:
        return "No assistant message to regenerate."
    last = assistant_msgs[-1]
    history.prune_after(last.id)
    return f"Removed last assistant message ({last.id}). Type your follow-up to regenerate."


@think_registry.command(name="prune", aliases=["p"])
def slash_prune(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Remove all messages after a given id: /prune msg_abc123"""
    msg_id = args.strip()
    if not msg_id:
        return "Usage: /prune <msg_id>"
    try:
        removed = history.prune_after(msg_id)
    except KeyError:
        return f"Message {msg_id} not found."
    return f"Pruned {len(removed)} message(s) after {msg_id}."


@think_registry.command(name="checkpoint", aliases=["cp"])
def slash_checkpoint(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Save or load a checkpoint: /checkpoint save-name  or  /checkpoint --list"""
    arg = args.strip()
    if arg == "--list" or arg == "-l":
        names = list_checkpoints(session.id)
        if not names:
            return "No checkpoints."
        return "Checkpoints:\n" + "\n".join(f"  - {n}" for n in names)
    if not arg:
        return "Usage: /checkpoint <name> or /checkpoint --list"
    save_checkpoint(session, arg)
    return f"Checkpoint saved: {arg}"


@think_registry.command(name="load")
def slash_load(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Load a checkpoint: /load checkpoint-name"""
    name = args.strip()
    if not name:
        return "Usage: /load <checkpoint_name>"
    loaded = load_checkpoint(session.id, name)
    if loaded is None:
        return f"Checkpoint '{name}' not found."
    session.messages = loaded.messages
    session.checkpoint_name = name
    return f"Loaded checkpoint: {name}"


@think_registry.command(name="fork")
def slash_fork(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Fork session from a message: /fork msg_abc123"""
    msg_id = args.strip()
    if not msg_id:
        return "Usage: /fork <msg_id>"
    try:
        new_session = history.fork_from(msg_id)
    except KeyError:
        return f"Message {msg_id} not found."
    return f"Forked to new session: {new_session.id}"


@think_registry.command(name="plan")
async def slash_plan_cmd(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Project plan management: /plan <subcommand>"""
    return await slash_plan(history, session, args)


@think_registry.command(name="push-to-do", aliases=["push"])
def slash_push_to_do(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Dispatch plan to Do mode: /push-to-do [phase-id]"""
    from pathlib import Path

    plan_file = Path("plan/index.md")
    if not plan_file.exists():
        return "No plan found. Use /plan init first."

    from consilium.think.push import _infer_next_phase

    target_phase = args.strip() or _infer_next_phase(plan_file)
    try:
        push_plan_to_do(plan_file, target_phase, think_session_id=session.id)
        return (
            f"Dispatched plan to Do mode.\n"
            f"Target phase: {target_phase}\n"
            f"Run: kimi --do --plan-file {plan_file} --phase {target_phase}\n"
            f"(Deprecated: --seed-from-think will be removed in a future release)"
        )
    except Exception as exc:
        return f"Failed to dispatch plan: {exc}"


@think_registry.command(name="explore")
async def slash_explore(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Spawn a foreground explore subagent: /explore <question>"""
    if not args.strip():
        return "Usage: /explore <question>"

    from consilium.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."

    import json
    import uuid

    from kosong.message import ToolCall
    from kosong.tooling import ToolOk

    from consilium.soul import get_wire_or_none
    from consilium.soul.toolset import current_tool_call
    from consilium.wire.types import ToolResult

    tool_id = f"call_{uuid.uuid4().hex[:12]}"
    fake_tool_call = ToolCall(
        id=tool_id,
        function=ToolCall.FunctionBody(
            name="Agent", arguments=json.dumps({"type": "explore", "prompt": args.strip()})
        ),
    )

    wire = get_wire_or_none()
    if wire:
        wire.soul_side.send(fake_tool_call)

    token = current_tool_call.set(fake_tool_call)
    try:
        summary = await soul.run_explore(args.strip())
        history.add_message("assistant", f"[Explore result]\n{summary}")
        return summary
    except Exception as exc:
        logger.exception("Think /explore failed")
        return f"[Error] /explore: {exc}"
    finally:
        current_tool_call.reset(token)
        if wire:
            # We don't have the final summary in finally if there was an exception,
            # but we can just send an empty ok or error result to close the block.
            wire.soul_side.send(
                ToolResult(tool_call_id=tool_id, return_value=ToolOk(output="done"))
            )


@think_registry.command(name="plan-edit", aliases=["pe"])
async def slash_plan_edit(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Spawn a plan_editor subagent to create or edit plan documents: /plan-edit <task>"""
    if not args.strip():
        return "Usage: /plan-edit <task description>"

    from consilium.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."

    import json
    import uuid

    from kosong.message import ToolCall
    from kosong.tooling import ToolOk

    from consilium.soul import get_wire_or_none
    from consilium.soul.toolset import current_tool_call
    from consilium.wire.types import ToolResult

    tool_id = f"call_{uuid.uuid4().hex[:12]}"
    fake_tool_call = ToolCall(
        id=tool_id,
        function=ToolCall.FunctionBody(
            name="Agent", arguments=json.dumps({"type": "plan_editor", "prompt": args.strip()})
        ),
    )

    wire = get_wire_or_none()
    if wire:
        wire.soul_side.send(fake_tool_call)

    token = current_tool_call.set(fake_tool_call)
    try:
        summary = await soul.run_plan_edit(args.strip())
        history.add_message("assistant", f"[Plan Edit result]\n{summary}")
        return summary
    except Exception as exc:
        logger.exception("Think /plan-edit failed")
        return f"[Error] /plan-edit: {exc}"
    finally:
        current_tool_call.reset(token)
        if wire:
            wire.soul_side.send(
                ToolResult(tool_call_id=tool_id, return_value=ToolOk(output="done"))
            )


@think_registry.command(name="investigate", aliases=["inv"])
async def slash_investigate(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Spawn parallel background investigations: /investigate <question> [| angle1, angle2]"""
    if not args.strip():
        return "Usage: /investigate <question> [ | angle1, angle2, ... ]"

    # Parse question and optional angles
    if " | " in args:
        question, angles_str = args.split(" | ", 1)
        angles = [a.strip() for a in angles_str.split(",") if a.strip()]
    else:
        question = args.strip()
        angles = []

    from consilium.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."

    try:
        report = await soul.run_investigate(question, angles)
        history.add_message("assistant", f"[Investigation result]\n{report}")
        return report
    except Exception as exc:
        logger.exception("Think /investigate failed")
        return f"[Error] /investigate: {exc}"


@think_registry.command(name="split-plan")
def slash_split_plan(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Split a monolithic plan.md into a directory-based plan.

    Usage: /split-plan <path-to-plan.md> [output-dir]
    Example:
        /split-plan docs/plan.md
        /split-plan docs/plan.md docs/plan/
    """
    from pathlib import Path

    parts = args.strip().split()
    if not parts:
        return "Usage: /split-plan <path-to-plan.md> [output-dir]"

    plan_path = Path(parts[0])
    output_dir = Path(parts[1]) if len(parts) >= 2 else plan_path.parent / "plan"

    if not plan_path.exists():
        return f"Plan file not found: {plan_path}"

    try:
        from consilium.plan.parser import parse_plan

        text = plan_path.read_text(encoding="utf-8")
        plan = parse_plan(text)
    except Exception as exc:
        return f"Failed to parse plan file: {exc}"

    if not plan.phases:
        return "No phases found in plan file. Is this a valid plan document?"

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write index.md
        index_lines: list[str] = []
        index_lines.append("---")
        if plan.metadata.plan_id:
            index_lines.append(f"plan_id: {plan.metadata.plan_id}")
        from consilium.utils.timestamp import format_date

        if plan.metadata.created:
            index_lines.append(f"created: {format_date(plan.metadata.created)}")
        if plan.metadata.last_updated:
            index_lines.append(f"last_updated: {format_date(plan.metadata.last_updated)}")
        index_lines.append("---")
        index_lines.append("")
        index_lines.append("# Plan Overview")
        index_lines.append("")
        index_lines.append("## Phases")
        index_lines.append("")
        for phase in plan.phases:
            link = f"[{phase.phase_id}]({phase.phase_id}.md)"
            index_lines.append(f"- {link}: {phase.title} ({phase.status.value})")
        index_lines.append("")
        index_lines.append("## Dependency Graph")
        index_lines.append("")
        for phase in plan.phases:
            if phase.dependencies:
                deps = ", ".join(phase.dependencies)
                index_lines.append(f"- {phase.phase_id} -> {deps}")
            else:
                index_lines.append(f"- {phase.phase_id} (no dependencies)")
        index_lines.append("")

        (output_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

        # Write per-phase files
        for phase in plan.phases:
            phase_lines: list[str] = []
            phase_lines.append("---")
            phase_lines.append(f'title: "{phase.title}"')
            phase_lines.append(f"status: {phase.status.value}")
            phase_lines.append(f"locked: {str(phase.locked).lower()}")
            if phase.files_involved:
                phase_lines.append("files_involved:")
                for f in phase.files_involved:
                    phase_lines.append(f"  - {f}")
            if phase.dependencies:
                phase_lines.append("dependencies:")
                for d in phase.dependencies:
                    phase_lines.append(f"  - {d}")
            phase_lines.append("---")
            phase_lines.append("")
            if phase.description:
                phase_lines.append("### Description")
                phase_lines.append(phase.description)
                phase_lines.append("")
            if phase.acceptance_criteria:
                phase_lines.append("### Acceptance Criteria")
                for item in phase.acceptance_criteria:
                    phase_lines.append(f"- {item}")
                phase_lines.append("")
            if phase.completion_criteria:
                phase_lines.append("### Completion Criteria")
                for item in phase.completion_criteria:
                    phase_lines.append(f"- {item}")
                phase_lines.append("")
            if phase.risks:
                phase_lines.append("### Risks")
                for item in phase.risks:
                    phase_lines.append(f"- {item}")
                phase_lines.append("")
            if phase.known:
                phase_lines.append("### Known")
                for item in phase.known:
                    phase_lines.append(f"- {item}")
                phase_lines.append("")
            if phase.unknown:
                phase_lines.append("### Unknown")
                for item in phase.unknown:
                    phase_lines.append(f"- {item}")
                phase_lines.append("")

            (output_dir / f"{phase.phase_id}.md").write_text(
                "\n".join(phase_lines), encoding="utf-8"
            )

        return (
            f"Split plan into {len(plan.phases)} phase document(s) in {output_dir}\n"
            f"  index.md\n" + "\n".join(f"  {p.phase_id}.md" for p in plan.phases)
        )
    except Exception as exc:
        return f"Failed to write plan directory: {exc}"


@think_registry.command(name="compact")
async def slash_compact(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Compact context: preserve recent messages, summarize older ones.

    Usage: /compact [instruction]
    Examples:
        /compact
        /compact "keep PI32 encoding details"
    """
    from consilium.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."

    instruction = args.strip() or None
    result = await history.compact(
        max_preserved_messages=soul._think_config.compaction_preserve_messages,
        custom_instruction=instruction,
        generate_summary=soul._generate_summary,
    )
    if result.removed == 0:
        return (
            f"Nothing to compact. Context at {result.old_usage_pct}%.\n"
            f"Active messages: {len(history.get_active_messages())}"
        )
    return (
        f"Compacted {result.removed} messages into summary ({result.summary_msg_id}).\n"
        f"Context: {result.old_usage_pct}% → {result.new_usage_pct}%\n"
        f"Summary preview: {result.summary[:120]}..."
    )


@think_registry.command(name="inbox", aliases=["i"])
def slash_inbox(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Check the reverse bridge inbox for reports from Do mode.

    Usage: /inbox
    """
    from consilium.think.inbox import mark_report_read, read_unread_reports

    reports = read_unread_reports(session.id)
    if not reports:
        return "📥 Inbox is empty. No new reports from Do mode."

    lines = [f"📥 {len(reports)} new report(s) from Do mode:\n"]
    for r in reports:
        lines.append(f"--- {r.report_type.upper()}: {r.phase_id} ---")
        preview = r.content[:800] + "..." if len(r.content) > 800 else r.content
        lines.append(preview)
        lines.append("")
        mark_report_read(r.report_id, session.id)

    return "\n".join(lines)


def get_think_slash_commands() -> list[SlashCommand[Any]]:
    return list(think_registry.list_commands())
