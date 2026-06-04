"""Think-mode /plan command suite."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from consilium.think.plan_synthesis import (
    SynthesisError,
    _backup_plan_directory,
    _extract_file_block,
    _strengthen_prompt,
    _validate_file,
    scaffold_plan_directories,
    write_plan_files,
)
from consilium.utils.logging import logger
from consilium.utils.timestamp import format_date

if TYPE_CHECKING:
    from consilium.llm import LLM
    from consilium.think.history import HistoryManager
    from consilium.think.models import ThinkMessage, ThinkSession

MAX_PHASES_PER_INIT = 10
MAX_RETRIES = 2


def _summarize_for_planning(messages: list[ThinkMessage]) -> str:
    """Compact conversation into planning-relevant context."""
    lines = []
    for msg in messages:
        if msg.deleted:
            continue
        preview = msg.content.replace("\n", " ")[:400]
        lines.append(f"[{msg.role}]: {preview}")
    return "\n".join(lines)


def _format_index_prompt(summary: str) -> str:
    return (
        "You are a project planner. Based on the conversation below, synthesize a "
        "phased implementation plan.\n\n"
        f"Conversation:\n{summary}\n\n"
        "Output ONLY the plan index file using this exact format:\n\n"
        "=== FILE: plan/index.md ===\n"
        "---\n"
        "plan_id: ...\n"
        f"created: {format_date(time.time())}\n"
        "---\n\n"
        "# Plan: ...\n\n"
        "## Phase Status Table\n"
        "| Phase | Title | Status | Locked |\n"
        "|-------|-------|--------|--------|\n"
        "| phase-01 | ... | pending | ❌ |\n"
        "...\n\n"
        "## Dependency Graph\n"
        "```\n"
        "- phase-01 (no dependencies)\n"
        "- phase-02 -> phase-01\n"
        "...\n"
        "```\n\n"
        f"Guidelines:\n"
        f"- Use at most {MAX_PHASES_PER_INIT} phases. "
        f"If more are needed, add a '## Deferred Phases' section.\n"
        '- Every phase must have a unique phase_id matching pattern "phase-NN"\n'
        '- Status is always "pending" for new plans\n'
        "- Dependencies must reference existing phase_ids in this plan\n"
    )


def _format_phase_prompt(summary: str, index_content: str, phase_id: str) -> str:
    return (
        "You are a project planner. Based on the conversation and the plan index below, "
        f"synthesize the detailed specification for one phase.\n\n"
        f"Plan index:\n{index_content}\n\n"
        f"Target phase: {phase_id}\n\n"
        "Output ONLY the phase file using this exact format:\n\n"
        f"=== FILE: plan/{phase_id}.md ===\n"
        "---\n"
        f"phase_id: {phase_id}\n"
        "title: ...\n"
        "status: pending\n"
        "dependencies:\n"
        "  - ...\n"
        "---\n\n"
        "# {title}\n\n"
        "## Description\n"
        "...\n\n"
        "## Acceptance Criteria\n"
        "- [ ] ...\n\n"
        "## Files Involved\n"
        "- src/...\n\n"
        "Guidelines:\n"
        "- Reference only phases that exist in the provided index\n"
        "- Files involved should be realistic paths relative to project root\n"
        "- Acceptance criteria must be verifiable\n"
    )


async def _generate_and_validate(
    llm: LLM,
    prompt: str,
    expected_path: str,
) -> str:
    """Generate, extract file block, validate, retry on failure."""
    from kosong import generate
    from kosong.message import Message as KosongMessage
    from kosong.message import TextPart

    for attempt in range(MAX_RETRIES + 1):
        response = await generate(
            llm.chat_provider,
            system_prompt=(
                "You are a project planner. Output only the requested file "
                "using === FILE: delimiters."
            ),
            tools=[],
            history=[KosongMessage(role="user", content=[TextPart(text=prompt)])],
        )
        raw = response.message.extract_text()

        try:
            content = _extract_file_block(raw, expected_path)
            _validate_file(content, expected_path)
            return content
        except SynthesisError as e:
            if attempt < MAX_RETRIES:
                prompt = _strengthen_prompt(prompt, expected_path, str(e))
            else:
                raise SynthesisError(
                    f"Failed to synthesize {expected_path} after {MAX_RETRIES} retries. "
                    f"Last error: {e}. "
                    "Try /plan init with a shorter conversation or clearer requirements."
                ) from e
    raise RuntimeError("Unreachable")


def _extract_phase_ids(index_content: str) -> list[str]:
    """Extract phase IDs from the index status table."""
    import re

    phase_ids = []
    # Look for table rows with phase-NN pattern
    for match in re.finditer(r"\|\s*(phase-\d+)\s*\|", index_content):
        phase_ids.append(match.group(1))
    # Deduplicate while preserving order
    seen = set()
    result = []
    for pid in phase_ids:
        if pid not in seen:
            seen.add(pid)
            result.append(pid)
    return result


def _append_deferred_section(index_content: str, phase_ids: list[str]) -> str:
    """Append a deferred phases notice to index content."""
    lines = index_content.rstrip().splitlines()
    lines.append("")
    lines.append("## Deferred Phases")
    lines.append("")
    lines.append(
        f"_The following phases were identified but deferred due to the "
        f"{MAX_PHASES_PER_INIT} phase cap:_"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


async def synthesize_plan_files(
    messages: list[ThinkMessage],
    llm: LLM,
) -> dict[str, str]:
    """Synthesize plan files from conversation history.

    Returns {filepath: content} for all plan files.
    """
    files: dict[str, str] = {}

    # DC-3: Compact conversation to summary before synthesis
    summary = _summarize_for_planning(messages)

    # Step 1: Synthesize index
    index_prompt = _format_index_prompt(summary)
    index_content = await _generate_and_validate(llm, index_prompt, "plan/index.md")
    files["plan/index.md"] = index_content

    # Step 2: Parse phase list from index
    phase_ids = _extract_phase_ids(index_content)

    if len(phase_ids) > MAX_PHASES_PER_INIT:
        logger.warning(
            f"Conversation suggests {len(phase_ids)} phases; "
            f"capping at {MAX_PHASES_PER_INIT}. Remainder goes to deferred section."
        )
        phase_ids = phase_ids[:MAX_PHASES_PER_INIT]
        files["plan/index.md"] = _append_deferred_section(index_content, phase_ids)

    # Step 3: Synthesize each phase sequentially
    for phase_id in phase_ids:
        phase_prompt = _format_phase_prompt(summary, index_content, phase_id)
        phase_content = await _generate_and_validate(llm, phase_prompt, f"plan/{phase_id}.md")
        files[f"plan/{phase_id}.md"] = phase_content

    return files


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


async def slash_plan_init(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Initialize a project plan from conversation history."""

    from consilium.plan.parser import parse_plan_directory_from_path
    from consilium.think import get_think_soul

    parts = args.strip().split()
    force = "--force" in parts

    work_dir = Path.cwd()
    plan_dir = work_dir / "plan"
    plan_file = plan_dir / "index.md"

    if plan_file.exists() and not force:
        backup_dir = _backup_plan_directory(plan_dir)
        msg = f"Existing plan backed up to {backup_dir}. Use --force to skip backup.\n"
    else:
        msg = ""

    # Scaffold directories
    scaffold_plan_directories(work_dir)

    # Get ThinkSoul to access LLM
    think_soul = get_think_soul(session.id)
    if think_soul is None or think_soul._llm is None:
        return msg + "ThinkSoul or LLM not available. Cannot synthesize plan."

    try:
        files = await synthesize_plan_files(session.messages, think_soul._llm)
        write_plan_files(files, work_dir)

        # Validate by re-parsing
        plan_dir_obj = parse_plan_directory_from_path(plan_dir)
        phase_count = len(plan_dir_obj.phases)

        return (
            msg
            + f"Created plan with {phase_count} phase(s).\n"
            + "\n".join(f"  {path}" for path in sorted(files.keys()))
        )
    except SynthesisError as exc:
        logger.exception("Plan synthesis failed")
        return msg + f"Plan synthesis failed: {exc}"
    except Exception as exc:
        logger.exception("Plan init failed")
        return msg + f"Plan init failed: {exc}"


def slash_plan_status(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Show plan status."""

    from consilium.plan.parser import parse_plan_directory_from_path

    plan_file = Path("plan/index.md")
    if not plan_file.exists():
        return "No plan found. Use /plan init first."

    try:
        plan_dir = parse_plan_directory_from_path(plan_file)
    except Exception as exc:
        return f"Failed to parse plan: {exc}"

    lines = [f"Plan: {plan_dir.metadata.plan_id or 'Untitled'}"]
    lines.append("")
    lines.append("| Phase | Title | Status | Locked |")
    lines.append("|-------|-------|--------|--------|")
    for phase in plan_dir.phases:
        lock_icon = "✅" if phase.locked else "❌"
        lines.append(f"| {phase.phase_id} | {phase.title} | {phase.status.value} | {lock_icon} |")
    lines.append("")
    return "\n".join(lines)


def slash_plan_add_phase(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Add a phase to the plan."""
    return "Not yet implemented. Use /plan init to create a new plan."


def slash_plan_update(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Update a phase in the plan."""
    return "Not yet implemented."


def slash_plan_add_decision(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Add a decision (ADR) to the plan."""
    return "Not yet implemented."


def slash_plan_add_finding(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Add a finding to the plan."""
    return "Not yet implemented."


# ---------------------------------------------------------------------------
# Main /plan dispatcher
# ---------------------------------------------------------------------------


async def slash_plan(
    history: HistoryManager,
    session: ThinkSession,
    args: str,
) -> str:
    """Project plan management.

    /plan init [name] [--force]    # LLM synthesizes plan from conversation
    /plan status                   # Show plan + phase status
    /plan add-phase <title>        # Add empty phase
    /plan update <phase-id>        # Re-synthesize phase
    /plan add-decision <title>     # Create ADR
    /plan add-finding <title>      # Create finding
    """
    parts = args.strip().split()
    subcommand = parts[0] if parts else ""
    rest = " ".join(parts[1:])

    if subcommand == "init":
        return await slash_plan_init(history, session, rest)
    if subcommand == "status":
        return slash_plan_status(history, session, rest)
    if subcommand == "add-phase":
        return slash_plan_add_phase(history, session, rest)
    if subcommand == "update":
        return slash_plan_update(history, session, rest)
    if subcommand == "add-decision":
        return slash_plan_add_decision(history, session, rest)
    if subcommand == "add-finding":
        return slash_plan_add_finding(history, session, rest)

    return (
        "Usage: /plan <subcommand>\n"
        "Subcommands: init, status, add-phase, update, add-decision, add-finding"
    )
