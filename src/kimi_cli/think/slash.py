"""Slash commands for Think mode."""

from __future__ import annotations

from typing import Any

from kimi_cli.think.history import HistoryManager
from kimi_cli.think.models import ThinkSession
from kimi_cli.think.push import export_to_outbox
from kimi_cli.think.storage import list_checkpoints, load_checkpoint, save_checkpoint
from kimi_cli.utils.editor import edit_text_in_editor
from kimi_cli.utils.logging import logger
from kimi_cli.utils.slashcmd import SlashCommand, SlashCommandRegistry

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


@think_registry.command(name="push-to-do", aliases=["push"])
def slash_push_to_do(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Export Think history to the Do-mode outbox: /push-to-do"""
    out_path = export_to_outbox(session)
    return (
        f"Exported {len(session.messages)} message(s) to Do-mode outbox.\n"
        f"File: {out_path}\n"
        f"Start Do mode with: kimi --do --seed-from-think {session.id}"
    )


@think_registry.command(name="explore")
async def slash_explore(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Spawn a foreground explore subagent: /explore <question>"""
    if not args.strip():
        return "Usage: /explore <question>"

    from kimi_cli.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."
    if soul._spawner is None:
        return "Subagent spawner not configured (subagents may be disabled)."

    try:
        summary = await soul.run_explore(args.strip())
        history.add_message("assistant", f"[Explore result]\n{summary}")
        return summary
    except Exception as exc:
        logger.exception("Think /explore failed")
        return f"[Error] /explore: {exc}"


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
        from kimi_cli.plan.parser import parse_plan

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
        from kimi_cli.utils.timestamp import format_date
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

        (output_dir / "index.md").write_text(
            "\n".join(index_lines), encoding="utf-8"
        )

        # Write per-phase files
        for phase in plan.phases:
            phase_lines: list[str] = []
            phase_lines.append("---")
            phase_lines.append(f"title: \"{phase.title}\"")
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
            f"  index.md\n"
            + "\n".join(f"  {p.phase_id}.md" for p in plan.phases)
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
    from kimi_cli.think import get_think_soul

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


def get_think_slash_commands() -> list[SlashCommand[Any]]:
    return list(think_registry.list_commands())
