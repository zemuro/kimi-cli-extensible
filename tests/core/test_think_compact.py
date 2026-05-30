"""Tests for Think mode manual compaction (§2.5)."""

from __future__ import annotations

import asyncio

from kimi_cli.think.context import assemble_context, estimate_context_tokens
from kimi_cli.think.history import HistoryManager
from kimi_cli.think.models import ThinkMessage, ThinkSession


def _make_session(messages: list[tuple[str, str]]) -> ThinkSession:
    """Helper: build a ThinkSession from (role, content) pairs."""
    session = ThinkSession()
    for role, content in messages:
        session.messages.append(ThinkMessage(role=role, content=content))
    return session


async def _fake_summary(messages: list[ThinkMessage], instruction: str | None) -> str:
    """Fake summary generator for tests (no LLM needed)."""
    topics = [f"{m.role}:{m.content[:20]}" for m in messages]
    focus = f" (focus: {instruction})" if instruction else ""
    return f"Summary of {len(messages)} messages{focus}: " + ", ".join(topics)


class TestCompactPreservesRecent:
    def test_compact_keeps_last_n_messages(self):
        session = _make_session([
            ("user", "msg1"),
            ("assistant", "msg2"),
            ("user", "msg3"),
            ("assistant", "msg4"),
            ("user", "msg5"),
            ("assistant", "msg6"),
        ])
        history = HistoryManager(session)

        result = asyncio.run(
            history.compact(max_preserved_messages=3, generate_summary=_fake_summary)
        )

        assert result.removed == 3
        active = history.get_active_messages()
        assert len(active) == 4  # 1 summary + 3 preserved
        assert active[0].role == "system"
        assert active[0].id.startswith("compact_")
        assert active[1].content == "msg4"
        assert active[2].content == "msg5"
        assert active[3].content == "msg6"

    def test_compact_noop_when_few_messages(self):
        session = _make_session([("user", "hi"), ("assistant", "hello")])
        history = HistoryManager(session)

        result = asyncio.run(
            history.compact(max_preserved_messages=6, generate_summary=_fake_summary)
        )

        assert result.removed == 0
        assert len(history.get_active_messages()) == 2


class TestCompactCustomInstruction:
    def test_custom_instruction_in_summary(self):
        session = _make_session([
            ("user", "discuss JWT"),
            ("assistant", "JWT is good"),
            ("user", "discuss sessions"),
            ("assistant", "sessions are stateful"),
            ("user", "which to choose?"),
            ("assistant", "use JWT"),
        ])
        history = HistoryManager(session)

        result = asyncio.run(
            history.compact(
                max_preserved_messages=2,
                custom_instruction="keep JWT details",
                generate_summary=_fake_summary,
            )
        )

        assert result.removed == 4
        assert "focus: keep JWT details" in result.summary


class TestCompactReducesContext:
    def test_context_usage_drops_after_compact(self):
        # Long messages to make usage measurable
        session = _make_session([
            ("user", "x " * 500),
            ("assistant", "y " * 500),
            ("user", "x " * 500),
            ("assistant", "y " * 500),
            ("user", "x " * 500),
            ("assistant", "y " * 500),
            ("user", "x " * 500),
            ("assistant", "y " * 500),
        ])
        history = HistoryManager(session)

        before = estimate_context_tokens(session, "")
        result = asyncio.run(
            history.compact(max_preserved_messages=2, generate_summary=_fake_summary)
        )
        after = estimate_context_tokens(session, "")

        assert result.removed == 6
        assert after < before
        assert result.new_usage_pct < result.old_usage_pct


class TestCompactMessagesNotDeleted:
    def test_original_messages_marked_not_deleted(self):
        session = _make_session([
            ("user", "old1"),
            ("assistant", "old2"),
            ("user", "new1"),
            ("assistant", "new2"),
        ])
        history = HistoryManager(session)

        result = asyncio.run(
            history.compact(max_preserved_messages=2, generate_summary=_fake_summary)
        )

        # Original messages still in session.messages
        assert len(session.messages) == 5  # 4 original + 1 summary
        # But not in active
        assert len(history.get_active_messages()) == 3

        # Check compacted_into markers
        compacted = [m for m in session.messages if m.compacted_into == result.summary_msg_id]
        assert len(compacted) == 2
        assert compacted[0].content == "old1"
        assert compacted[1].content == "old2"


class TestCompactHistoryShowsIndicator:
    def test_format_history_shows_compacted(self):
        session = _make_session([
            ("user", "first"),
            ("assistant", "second"),
            ("user", "third"),
        ])
        history = HistoryManager(session)
        asyncio.run(
            history.compact(max_preserved_messages=1, generate_summary=_fake_summary)
        )

        # Check that compacted messages are not in active
        active = history.get_active_messages()
        assert all(m.compacted_into is None for m in active)

        # But exist in full session
        compacted = [m for m in session.messages if m.compacted_into is not None]
        assert len(compacted) == 2


class TestCompactEditRejected:
    def test_edit_on_compacted_message_fails(self):
        session = _make_session([
            ("user", "old"),
            ("assistant", "reply"),
            ("user", "new"),
        ])
        history = HistoryManager(session)
        asyncio.run(
            history.compact(max_preserved_messages=1, generate_summary=_fake_summary)
        )

        compacted_msg = [m for m in session.messages if m.compacted_into is not None][0]

        # Edit should still work at HistoryManager level (we don't block it)
        # But the edited message remains compacted and won't enter context
        history.edit_message(compacted_msg.id, "edited")
        assert compacted_msg.content == "edited"
        assert compacted_msg.compacted_into is not None  # Still compacted


class TestCompactPruneCrossBoundary:
    def test_prune_works_across_summary_and_preserved(self):
        session = _make_session([
            ("user", "m1"),
            ("assistant", "m2"),
            ("user", "m3"),
            ("assistant", "m4"),
            ("user", "m5"),
        ])
        history = HistoryManager(session)
        asyncio.run(
            history.compact(max_preserved_messages=2, generate_summary=_fake_summary)
        )

        # Prune at summary message — removes everything after it.
        # Summary was inserted at index 0 (before all original messages),
        # so prune_after removes ALL original messages.
        summary_msg = [m for m in session.messages if m.id.startswith("compact_")][0]
        removed = history.prune_after(summary_msg.id)

        assert len(removed) == 5  # m1, m2, m3, m4, m5
        assert len(session.messages) == 1  # only summary remains


class TestThresholdWarning:
    def test_assemble_context_skips_compacted(self):
        session = _make_session([
            ("user", "old1"),
            ("assistant", "old2"),
            ("user", "new1"),
            ("assistant", "new2"),
        ])
        history = HistoryManager(session)
        asyncio.run(
            history.compact(max_preserved_messages=2, generate_summary=_fake_summary)
        )

        context = assemble_context(session, "system prompt")
        roles = [m.role for m in context]

        # system prompt + summary + 2 preserved
        assert roles == ["system", "system", "user", "assistant"]
        # Extract text from ContentPart lists
        texts = []
        for msg in context:
            for part in msg.content:
                texts.append(part.text)

        # The compacted old1/old2 messages themselves are not in context
        # (though the summary may mention them)
        assert any("new1" in t for t in texts)
        assert any("new2" in t for t in texts)
        # Verify exactly 4 context messages
        assert len(context) == 4

    def test_estimate_tokens_skips_compacted(self):
        session = _make_session([
            ("user", "x " * 100),
            ("assistant", "y " * 100),
            ("user", "z " * 100),
            ("assistant", "w " * 100),
        ])
        history = HistoryManager(session)
        before = estimate_context_tokens(session, "")

        asyncio.run(
            history.compact(max_preserved_messages=2, generate_summary=_fake_summary)
        )

        after = estimate_context_tokens(session, "")
        assert after < before
