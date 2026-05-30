"""Tests for Think → Do bridge (push.py, slash commands, seeding)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kimi_cli.think.models import ThinkMessage, ThinkSession
from kimi_cli.think.push import OUTBOX_DIR, clear_outbox, export_to_outbox, load_outbox
from kimi_cli.think.slash import slash_push_to_do


class TestExportToOutbox:
    def test_export_creates_json_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", tmp_path)

        session = ThinkSession(id="sess-123")
        session.messages = [
            ThinkMessage(role="user", content="hello"),
            ThinkMessage(role="assistant", content="hi there"),
            ThinkMessage(role="system", content="ignored"),
            ThinkMessage(role="user", content="deleted msg", deleted=True),
        ]

        out_path = export_to_outbox(session)

        assert out_path.exists()
        assert out_path.name == "sess-123.json"

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["source_session_id"] == "sess-123"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "hello"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "hi there"

    def test_load_outbox_returns_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", tmp_path)

        payload = {
            "source_session_id": "sess-456",
            "messages": [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ],
        }
        out_path = tmp_path / "sess-456.json"
        out_path.write_text(json.dumps(payload), encoding="utf-8")

        msgs = load_outbox("sess-456")
        assert msgs is not None
        assert len(msgs) == 2
        assert msgs[0]["content"] == "q"

    def test_load_outbox_missing_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", tmp_path)
        assert load_outbox("nonexistent") is None

    def test_clear_outbox_removes_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", tmp_path)

        out_path = tmp_path / "sess-789.json"
        out_path.write_text("{}", encoding="utf-8")
        clear_outbox("sess-789")
        assert not out_path.exists()


class TestSlashPushToDo:
    def test_slash_push_to_do_exports(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", tmp_path)

        session = ThinkSession(id="sess-abc")
        session.messages = [ThinkMessage(role="user", content="hello")]
        history = MagicMock()
        history.session = session

        result = slash_push_to_do(history, session, "")
        assert "Exported 1 message(s)" in result
        assert "sess-abc" in result
        assert (tmp_path / "sess-abc.json").exists()


class TestSeedFromThink:
    @pytest.mark.asyncio
    async def test_seed_from_think_injects_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kimi_cli.soul.context import Context
        from kosong.message import Message, TextPart

        outbox = tmp_path / "outbox"
        monkeypatch.setattr("kimi_cli.think.push.OUTBOX_DIR", outbox)
        outbox.mkdir(parents=True, exist_ok=True)

        payload = {
            "source_session_id": "seed-sess",
            "messages": [
                {"role": "user", "content": "hello from think"},
                {"role": "assistant", "content": "hello from do"},
            ],
        }
        (outbox / "seed-sess.json").write_text(json.dumps(payload), encoding="utf-8")

        # Context needs a file backend, use an empty temp file
        ctx_file = tmp_path / "context.jsonl"
        ctx_file.write_text("", encoding="utf-8")
        context = Context(ctx_file)
        await context.restore()
        await context.write_system_prompt("You are a helpful assistant.")

        # Simulate what app.py does
        from kimi_cli.think.push import load_outbox
        seed_messages = load_outbox("seed-sess")
        assert seed_messages is not None
        for msg in seed_messages:
            await context.append_message(
                Message(role=msg["role"], content=[TextPart(text=msg["content"])])
            )

        # System prompt + 2 seeded messages
        assert len(context._history) == 2
        assert context._history[0].role == "user"
        assert context._history[0].content[0].text == "hello from think"
        assert context._history[1].role == "assistant"
        assert context._history[1].content[0].text == "hello from do"
