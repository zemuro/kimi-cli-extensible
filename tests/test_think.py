"""Tests for Think mode."""

from __future__ import annotations

from pathlib import Path

from consilium.think.context import assemble_context, estimate_context_tokens
from consilium.think.history import HistoryManager
from consilium.think.models import ThinkMessage, ThinkSession
from consilium.think.slash import think_registry
from consilium.think.storage import (
    list_checkpoints,
    list_sessions,
    load_checkpoint,
    load_session,
    save_checkpoint,
    save_session,
)


class TestThinkStorage:
    def test_storage_roundtrip(self, tmp_path: Path) -> None:
        """Save and load ThinkSession, verify all fields."""
        original = ThinkSession()
        original.messages.append(ThinkMessage(role="user", content="hello"))
        original.messages.append(
            ThinkMessage(
                role="assistant",
                content="hi there",
                tokens_in=10,
                tokens_out=5,
            )
        )

        save_session(original, work_dir=tmp_path)
        loaded = load_session(original.id, work_dir=tmp_path)
        assert loaded is not None
        assert loaded.id == original.id
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == "user"
        assert loaded.messages[0].content == "hello"
        assert loaded.messages[1].role == "assistant"
        assert loaded.messages[1].content == "hi there"
        assert loaded.messages[1].tokens_in == 10
        assert loaded.messages[1].tokens_out == 5

    def test_list_sessions(self, tmp_path: Path) -> None:
        """List sessions returns sorted (id, mtime) tuples."""
        s1 = ThinkSession()
        s2 = ThinkSession()
        save_session(s1, work_dir=tmp_path)
        save_session(s2, work_dir=tmp_path)
        sessions = list_sessions(work_dir=tmp_path)
        assert len(sessions) == 2
        assert {s[0] for s in sessions} == {s1.id, s2.id}


class TestThinkHistory:
    def test_add_message(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        msg = hm.add_message("user", "hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert len(hm.get_active_messages()) == 1

    def test_edit_message(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        msg = hm.add_message("user", "hello")
        edited = hm.edit_message(msg.id, "hello world")
        assert edited.content == "hello world"
        assert edited.edited_at is not None

    def test_delete_message(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        msg = hm.add_message("user", "hello")
        hm.delete_message(msg.id)
        active = hm.get_active_messages()
        assert len(active) == 0

    def test_prune_after(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        m1 = hm.add_message("user", "a")
        hm.add_message("assistant", "b")
        hm.add_message("user", "c")
        removed = hm.prune_after(m1.id)
        assert len(removed) == 2
        assert len(session.messages) == 1
        assert session.messages[0].content == "a"

    def test_fork_from(self, tmp_path: Path) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        m1 = hm.add_message("user", "a")
        hm.add_message("assistant", "b")
        new_session = hm.fork_from(m1.id)
        assert new_session.id != session.id
        assert len(new_session.messages) == 1
        assert new_session.messages[0].content == "a"


class TestThinkContext:
    def test_assemble_context_excludes_deleted(self) -> None:
        session = ThinkSession()
        session.messages.append(ThinkMessage(role="user", content="hello"))
        session.messages.append(ThinkMessage(role="assistant", content="hi"))
        session.messages.append(ThinkMessage(role="user", content="deleted", deleted=True))

        messages = assemble_context(session, "You are a test assistant.")
        assert len(messages) == 3  # system + 2 active
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert messages[2].role == "assistant"

    def test_estimate_context_tokens(self) -> None:
        session = ThinkSession()
        session.messages.append(ThinkMessage(role="user", content="hello world"))
        tokens = estimate_context_tokens(session, "system prompt")
        assert tokens > 0


class TestThinkSlashCommands:
    def test_history_command(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        hm.add_message("user", "hello")
        result = think_registry.find_command("history")
        assert result is not None
        out = result.func(hm, session, "")
        assert "hello" in out

    def test_edit_command_missing_id(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        result = think_registry.find_command("edit")
        assert result is not None
        out = result.func(hm, session, "")
        assert "Usage" in out

    def test_delete_command(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        msg = hm.add_message("user", "hello")
        result = think_registry.find_command("delete")
        assert result is not None
        out = result.func(hm, session, msg.id)
        assert "Deleted" in out
        assert len(hm.get_active_messages()) == 0

    def test_prune_command(self) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        m1 = hm.add_message("user", "a")
        hm.add_message("assistant", "b")
        result = think_registry.find_command("prune")
        assert result is not None
        out = result.func(hm, session, m1.id)
        assert "Pruned" in out
        assert len(session.messages) == 1

    def test_checkpoint_command(self, tmp_path: Path) -> None:
        session = ThinkSession()
        hm = HistoryManager(session)
        hm.add_message("user", "hello")
        result = think_registry.find_command("checkpoint")
        assert result is not None
        out = result.func(hm, session, "test-checkpoint")
        assert "saved" in out

    def test_load_command(self, tmp_path: Path) -> None:
        import consilium.think.storage as storage

        old_dir = storage.THINK_DIR
        storage.THINK_DIR = tmp_path
        try:
            session = ThinkSession()
            hm = HistoryManager(session)
            hm.add_message("user", "hello")
            save_checkpoint(session, "cp1")
            result = think_registry.find_command("load")
            assert result is not None
            out = result.func(hm, session, "cp1")
            assert "Loaded" in out
        finally:
            storage.THINK_DIR = old_dir


class TestThinkCheckpoint:
    def test_checkpoint_save_restore(self, tmp_path: Path) -> None:
        session = ThinkSession()
        session.messages.append(ThinkMessage(role="user", content="hello"))
        session.messages.append(ThinkMessage(role="assistant", content="hi"))

        save_checkpoint(session, "before-edit", work_dir=tmp_path)
        session.messages[0].content = "edited"

        restored = load_checkpoint(session.id, "before-edit", work_dir=tmp_path)
        assert restored is not None
        assert restored.messages[0].content == "hello"
        assert restored.messages[1].content == "hi"
