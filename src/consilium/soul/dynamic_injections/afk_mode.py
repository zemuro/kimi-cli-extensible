from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from kosong.message import Message

import consilium.prompts as prompts
from consilium.soul.dynamic_injection import DynamicInjection, DynamicInjectionProvider

if TYPE_CHECKING:
    from consilium.soul.consiliumsoul import ConsiliumSoul

_AFK_INJECTION_TYPE = "afk_mode"

_AFK_PROMPT_ROOT = prompts.AFK_MODE

AFK_DISABLED_REMINDER = prompts.AFK_DISABLED


class AfkModeInjectionProvider(DynamicInjectionProvider):
    """Injects afk (away-from-keyboard) guidance when no user is present."""

    def __init__(self) -> None:
        self._injected: bool = False

    async def get_injections(
        self,
        history: Sequence[Message],
        soul: ConsiliumSoul,
    ) -> list[DynamicInjection]:
        _ = history
        if not soul.is_afk:
            return []
        if not soul.is_afk_flag:
            return []

        if soul.is_subagent:
            return []

        if self._injected:
            return []
        self._injected = True
        return [DynamicInjection(type=_AFK_INJECTION_TYPE, content=_AFK_PROMPT_ROOT)]

    async def on_context_compacted(self) -> None:
        # Compaction rewrites history; the prior afk reminder may have been
        # summarized away, so let the next afk step restate the constraint.
        self._injected = False

    async def on_afk_changed(self, enabled: bool) -> None:
        # A runtime toggle changes the latest truth about user presence.
        # Re-arm so the next LLM step can inject the current afk guidance.
        _ = enabled
        self._injected = False
