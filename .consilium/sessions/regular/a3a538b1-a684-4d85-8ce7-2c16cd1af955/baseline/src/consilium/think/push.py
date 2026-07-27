"""Think → Do bridge: export Think history to the outbox.

Phase 11: plan-centric handoff. /push-to-do now writes dispatch.json
pointing to the plan document. The outbox export is deprecated.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from consilium.utils.logging import logger

if TYPE_CHECKING:
    from consilium.plan.models import Dispatch
    from consilium.think.models import ThinkSession

OUTBOX_DIR = Path.home() / ".consilium" / "think_outbox"


def export_to_outbox(session: ThinkSession) -> Path:
    """Export active Think messages to the outbox for Do-mode seeding.

    DEPRECATED: Use push_plan_to_do() instead.
    Returns the path to the exported file.
    """
    logger.warning("export_to_outbox is deprecated. Use push_plan_to_do instead.")
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

    active_messages = [
        msg for msg in session.messages if not msg.deleted and msg.role in ("user", "assistant")
    ]

    payload = {
        "source_session_id": session.id,
        "exported_at": time.time(),
        "messages": [{"role": msg.role, "content": msg.content} for msg in active_messages],
    }

    out_path = OUTBOX_DIR / f"{session.id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_outbox(session_id: str) -> list[dict[str, str]] | None:
    """Load messages from the outbox for a given session ID.

    DEPRECATED: Do mode now loads plan documents directly.
    Returns the message list or None if no outbox file exists.
    """
    path = OUTBOX_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("messages")


def clear_outbox(session_id: str) -> None:
    """Remove the outbox file for a given session ID."""
    path = OUTBOX_DIR / f"{session_id}.json"
    path.unlink(missing_ok=True)


def _infer_next_phase(plan_file: Path) -> str:
    """Infer the next phase to implement from the plan index."""
    from consilium.plan.parser import parse_plan_directory_from_path

    try:
        plan_dir = parse_plan_directory_from_path(plan_file)
        for phase in plan_dir.phases:
            if phase.status.value == "pending":
                return phase.phase_id
        # Fallback: return first phase if none pending
        if plan_dir.phases:
            return plan_dir.phases[0].phase_id
    except Exception:
        pass
    return "phase-01"


def push_plan_to_do(
    plan_file: Path, target_phase: str, think_session_id: str | None = None
) -> Dispatch:
    """Write a dispatch signal pointing to the plan document."""
    from consilium.plan.dispatch import write_dispatch
    from consilium.plan.models import DispatchAction
    from consilium.plan.parser import parse_plan_directory_from_path

    if not plan_file.exists():
        raise RuntimeError(f"No plan found at {plan_file}. Use /plan init first.")

    plan_dir = parse_plan_directory_from_path(plan_file)
    return write_dispatch(
        plan_id=plan_dir.metadata.plan_id or "untitled",
        target_phase=target_phase,
        plan_file=str(plan_file),
        action=DispatchAction.START_IMPLEMENT,
        think_session_id=think_session_id,
    )
