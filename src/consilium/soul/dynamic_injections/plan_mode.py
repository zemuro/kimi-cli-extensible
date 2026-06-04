from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from jinja2 import Template
from kosong.message import Message, TextPart

import consilium.prompts as prompts
from consilium.soul.dynamic_injection import DynamicInjection, DynamicInjectionProvider

if TYPE_CHECKING:
    from consilium.soul.kimisoul import KimiSoul

# Inject a reminder every N assistant turns.
_TURN_INTERVAL = 5
# Every N-th reminder is the full version; others are sparse.
_FULL_EVERY_N = 5


class PlanModeInjectionProvider(DynamicInjectionProvider):
    """Periodically injects read-only reminders while plan mode is active.

    Throttling is inferred from history: scan backwards to the last
    plan mode reminder and count assistant messages in between.
    Only inject when the count exceeds ``_TURN_INTERVAL``.
    """

    def __init__(self) -> None:
        self._inject_count: int = 0

    async def get_injections(
        self,
        history: Sequence[Message],
        soul: KimiSoul,
    ) -> list[DynamicInjection]:
        # Plan-mode workflow reminders are root-only. Subagents share the
        # session's plan_mode flag for persistence/resume, but their YAMLs
        # usually exclude EnterPlanMode/ExitPlanMode, so do not inject this
        # workflow guidance into subagent contexts.
        if soul.is_subagent:
            return []
        if not soul.plan_mode:
            self._inject_count = 0
            return []

        plan_path = soul.get_plan_file_path()
        plan_path_str = str(plan_path) if plan_path else None
        plan_exists = plan_path is not None and plan_path.exists()

        # Manual toggles schedule a one-shot activation reminder for the next LLM step.
        if soul.consume_pending_plan_activation_injection():
            self._inject_count = 1
            # When re-entering with an existing plan, use the reentry reminder.
            if plan_exists:
                return [
                    DynamicInjection(
                        type="plan_mode_reentry",
                        content=_reentry_reminder(plan_path_str),
                    )
                ]
            return [
                DynamicInjection(
                    type="plan_mode",
                    content=_full_reminder(plan_path_str, plan_exists),
                )
            ]

        # Scan history backwards to find the last plan mode reminder.
        turns_since_last = 0
        found_previous = False
        for msg in reversed(history):
            if msg.role == "user" and _has_plan_reminder(msg):
                found_previous = True
                break
            if msg.role == "assistant":
                turns_since_last += 1

        # First time (no reminder in history yet) -> inject full version.
        if not found_previous:
            self._inject_count = 1
            return [
                DynamicInjection(
                    type="plan_mode",
                    content=_full_reminder(plan_path_str, plan_exists),
                )
            ]

        # Not enough turns since last reminder -> skip.
        if turns_since_last < _TURN_INTERVAL:
            return []

        # Inject.
        self._inject_count += 1
        is_full = self._inject_count % _FULL_EVERY_N == 1
        if is_full:
            content = _full_reminder(plan_path_str, plan_exists)
        else:
            content = _sparse_reminder(plan_path_str)
        return [DynamicInjection(type="plan_mode", content=content)]


def _has_plan_reminder(msg: Message) -> bool:
    """Check whether a message contains a plan mode reminder.

    Detects by matching against stable prefixes of the actual reminder texts
    so changes to the reminder wording stay automatically in sync.
    """
    keys = (
        _sparse_reminder().split(".")[0],  # "Plan mode still active ..."
        _full_reminder().split("\n")[0],  # "Plan mode is active. ..."
    )
    for part in msg.content:
        if isinstance(part, TextPart) and any(key in part.text for key in keys):
            return True
    return False


_FULL_REMINDER_TEMPLATE = Template(prompts.PLAN_MODE_FULL)
_SPARSE_REMINDER_TEMPLATE = Template(prompts.PLAN_MODE_SPARSE)
_REENTRY_REMINDER_TEMPLATE = Template(prompts.PLAN_MODE_REENTRY)


def _full_reminder(
    plan_file_path: str | None = None,
    plan_exists: bool = False,
) -> str:
    return _FULL_REMINDER_TEMPLATE.render(
        plan_file_path=plan_file_path, plan_exists=plan_exists
    ).strip()


def _sparse_reminder(plan_file_path: str | None = None) -> str:
    rendered = _SPARSE_REMINDER_TEMPLATE.render(plan_file_path=plan_file_path).strip()
    # Original behavior: single line space-separated text
    return " ".join(rendered.split())


def _reentry_reminder(plan_file_path: str | None = None) -> str:
    return _REENTRY_REMINDER_TEMPLATE.render(plan_file_path=plan_file_path).strip()
