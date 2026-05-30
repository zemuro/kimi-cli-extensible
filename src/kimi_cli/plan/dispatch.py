"""Think → Do dispatch mechanism via .kimi/dispatch.json."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.plan.models import Dispatch, DispatchAction


DISPATCH_PATH = Path.home() / ".kimi" / "dispatch.json"


def write_dispatch(
    plan_id: str,
    target_phase: str,
    action: DispatchAction = None,
    require_user_approval: bool = True,
    afk_mode: bool = False,
    dispatched_by: str = "think",
) -> Dispatch:
    """Write a dispatch signal to .kimi/dispatch.json.

    Args:
        plan_id: The plan identifier.
        target_phase: Phase ID to dispatch (e.g., "phase-3").
        action: START_REVIEW or START_IMPLEMENT.
        require_user_approval: If True, user must approve before Do proceeds.
        afk_mode: If True, auto-approve in AFK mode.
        dispatched_by: Who triggered the dispatch.

    Returns:
        The written Dispatch object.
    """
    from kimi_cli.plan.models import Dispatch, DispatchAction

    if action is None:
        action = DispatchAction.START_REVIEW

    dispatch = Dispatch(
        dispatch_id=f"disp_{time.time():.0f}_{uuid.uuid4().hex[:6]}",
        plan_id=plan_id,
        action=action,
        target_phase=target_phase,
        dispatched_at=time.time(),
        dispatched_by=dispatched_by,  # type: ignore[arg-type]
        require_user_approval=require_user_approval,
        afk_mode=afk_mode,
    )

    DISPATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISPATCH_PATH.write_text(
        dispatch.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return dispatch


def read_dispatch(path: Path | None = None) -> Dispatch | None:
    """Read the dispatch signal from disk.

    Args:
        path: Optional override path. Defaults to ~/.kimi/dispatch.json.

    Returns:
        Dispatch object if file exists and is valid, else None.
    """
    from kimi_cli.plan.models import Dispatch

    path = path or DISPATCH_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Dispatch.model_validate(data)
    except (json.JSONDecodeError, Exception):
        return None


def clear_dispatch(path: Path | None = None) -> None:
    """Remove the dispatch file."""
    path = path or DISPATCH_PATH
    if path.exists():
        path.unlink()
