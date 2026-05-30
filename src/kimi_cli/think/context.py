"""Assemble kosong Message list from a ThinkSession."""

from __future__ import annotations

from kosong.message import Message, TextPart

from kimi_cli.think.models import ThinkSession


def assemble_context(session: ThinkSession, system_prompt: str) -> list[Message]:
    """Build OpenAI-compatible message list from ThinkSession.

    1. Prepend system prompt
    2. Add active messages in chronological order
    """
    messages: list[Message] = [
        Message(role="system", content=[TextPart(text=system_prompt)])
    ]
    # Include non-system active messages + compact summary messages (role=system)
    active = [
        m for m in session.messages
        if not m.deleted and m.compacted_into is None
        and (m.role != "system" or m.id.startswith("compact_"))
    ]
    for msg in active:
        messages.append(Message(role=msg.role, content=msg.content))
    return messages


def estimate_context_tokens(session: ThinkSession, system_prompt: str) -> int:
    """Rough token count estimate for status display."""
    total = len(system_prompt.split()) * 1.3  # rough heuristic
    for msg in session.messages:
        if not msg.deleted and msg.compacted_into is None:
            total += len(msg.content.split()) * 1.3
    return int(total)
