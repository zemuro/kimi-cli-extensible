"""Mutable history manager for Think mode."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from consilium.think.models import CompactResult, ThinkMessage, ThinkSession
from consilium.think.storage import save_session

SummaryCallback = Callable[[list[ThinkMessage], str | None], Awaitable[str]]


class HistoryManager:
    """CRUD operations on a ThinkSession's message history."""

    def __init__(self, session: ThinkSession) -> None:
        self.session = session

    def add_message(self, role: str, content: str) -> ThinkMessage:
        """Append a new message to the session."""
        msg = ThinkMessage(role=role, content=content)  # type: ignore[arg-type]
        self.session.messages.append(msg)
        save_session(self.session)
        return msg

    def edit_message(self, msg_id: str, new_content: str) -> ThinkMessage:
        """Edit an existing message by id."""
        msg = self._get(msg_id)
        msg.content = new_content
        msg.edited_at = time.time()
        save_session(self.session)
        return msg

    def delete_message(self, msg_id: str) -> None:
        """Soft-delete a message by id."""
        msg = self._get(msg_id)
        msg.deleted = True
        save_session(self.session)

    def get_active_messages(self) -> list[ThinkMessage]:
        """Return non-deleted, non-compacted messages in chronological order."""
        return [m for m in self.session.messages if not m.deleted and m.compacted_into is None]

    async def compact(
        self,
        max_preserved_messages: int = 6,
        custom_instruction: str | None = None,
        generate_summary: SummaryCallback | None = None,
    ) -> CompactResult:
        """Preserve recent messages, summarize older ones into a system message.

        Original messages are marked ``compacted_into`` but remain in storage
        for history viewing. They are excluded from LLM context.
        """
        active = self.get_active_messages()
        if len(active) <= max_preserved_messages:
            # Count usage for the result
            old_usage = self._estimate_usage_pct(active)
            return CompactResult(
                removed=0,
                summary="",
                summary_msg_id="",
                old_usage_pct=old_usage,
                new_usage_pct=old_usage,
            )

        to_summarize = active[:-max_preserved_messages]

        old_usage = self._estimate_usage_pct(active)

        # Generate summary via callback (LLM call)
        if generate_summary is not None:
            summary_text = await generate_summary(to_summarize, custom_instruction)
        else:
            # Fallback: naive concatenation when no LLM available (tests)
            summary_text = self._naive_summary(to_summarize)

        summary_id = f"compact_{__import__('uuid').uuid4().hex[:8]}"

        # Mark original messages as compacted
        for msg in to_summarize:
            msg.compacted_into = summary_id

        # Insert summary message at the position of the first compacted msg
        summary_msg = ThinkMessage(
            id=summary_id,
            role="system",
            content=(f"[Context summary of {len(to_summarize)} earlier messages]\n{summary_text}"),
        )
        first_idx = self.session.messages.index(to_summarize[0])
        self.session.messages.insert(first_idx, summary_msg)

        save_session(self.session)

        new_active = self.get_active_messages()
        new_usage = self._estimate_usage_pct(new_active)

        return CompactResult(
            removed=len(to_summarize),
            summary=summary_text,
            summary_msg_id=summary_id,
            old_usage_pct=old_usage,
            new_usage_pct=new_usage,
        )

    @staticmethod
    def _naive_summary(messages: list[ThinkMessage]) -> str:
        """Fallback summary when no LLM is available."""
        lines = []
        for msg in messages:
            preview = msg.content.replace("\n", " ")[:80]
            lines.append(f"[{msg.role}]: {preview}")
        return "\n".join(lines)

    def _estimate_usage_pct(self, messages: list[ThinkMessage]) -> float:
        """Rough context usage percentage based on word count."""
        total_words = sum(len(m.content.split()) for m in messages)
        # Rough heuristic: 1 token ≈ 0.75 words, context window default ~200k
        estimated_tokens = total_words / 0.75
        # Use a reasonable default; ThinkSoul will check against actual max
        return round(min(estimated_tokens / 200_000 * 100, 99.9), 1)

    def get_message(self, msg_id: str) -> ThinkMessage:
        """Get a message by id (including deleted)."""
        return self._get(msg_id)

    def prune_after(self, msg_id: str) -> list[ThinkMessage]:
        """Remove all messages after the given message id."""
        for i, msg in enumerate(self.session.messages):
            if msg.id == msg_id:
                removed = self.session.messages[i + 1 :]
                self.session.messages = self.session.messages[: i + 1]
                save_session(self.session)
                return removed
        raise KeyError(f"Message {msg_id} not found")

    def fork_from(self, msg_id: str) -> ThinkSession:
        """Create a new session with messages up to and including msg_id."""
        for i, msg in enumerate(self.session.messages):
            if msg.id == msg_id:
                new_session = ThinkSession(
                    messages=[
                        ThinkMessage(
                            id=m.id,
                            role=m.role,
                            content=m.content,
                            timestamp=m.timestamp,
                            tokens_in=m.tokens_in,
                            tokens_out=m.tokens_out,
                            deleted=m.deleted,
                            edited_at=m.edited_at,
                        )
                        for m in self.session.messages[: i + 1]
                    ]
                )
                save_session(new_session)
                return new_session
        raise KeyError(f"Message {msg_id} not found")

    def _get(self, msg_id: str) -> ThinkMessage:
        for m in self.session.messages:
            if m.id == msg_id:
                return m
        raise KeyError(f"Message {msg_id} not found")
