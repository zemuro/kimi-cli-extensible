"""Tests for ContextView materialization."""

from __future__ import annotations

from consilium.plan.context_view import ContextView
from consilium.plan.log_entry import make_log_entry
from consilium.plan.persistent_log import PersistentLog


class TestContextViewMaterialize:
    def test_materializes_messages(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        e2 = make_log_entry("message", {"role": "assistant", "content": "hi"}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        view = ContextView(log)
        msgs = view.materialize()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["role"] == "assistant"

    def test_resolves_edits(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        e2 = make_log_entry("edit", {"target_id": e1.id, "new_content": "hello world"}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        view = ContextView(log)
        msgs = view.materialize()
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello world"

    def test_resolves_deletes(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        e2 = make_log_entry("delete", {"target_id": e1.id}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        view = ContextView(log)
        msgs = view.materialize()
        assert len(msgs) == 0

    def test_compact_inserts_summary(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "msg1"}, None, "think")
        e2 = make_log_entry("compact", {"summary": "old messages summarized", "preserved_ids": []}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        view = ContextView(log)
        msgs = view.materialize()
        # Compact replaces previous messages with summary
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert "Compacted" in msgs[0]["content"]

    def test_compact_preserves_kept_ids(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "keep me"}, None, "think")
        e2 = make_log_entry("compact", {"summary": "summary", "preserved_ids": [e1.id]}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        view = ContextView(log)
        msgs = view.materialize()
        # Compact replaces previous messages; preserved msg is kept
        assert len(msgs) == 2
        assert msgs[0]["content"] == "keep me"
        assert msgs[1]["role"] == "system"

    def test_caching(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        log.append(e1)

        view = ContextView(log)
        m1 = view.materialize()
        m2 = view.materialize()
        assert m1 == m2  # cached result returned

    def test_cache_invalidation_on_new_append(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        log.append(e1)

        view = ContextView(log)
        view.materialize()  # prime cache

        e2 = make_log_entry("message", {"role": "assistant", "content": "hi"}, e1.id, "think")
        log.append(e2)

        m2 = view.materialize()
        assert len(m2) == 2

    def test_fork_creates_sub_view(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "old"}, None, "think")
        e2 = make_log_entry("message", {"role": "user", "content": "new"}, e1.id, "think")
        e3 = make_log_entry("message", {"role": "user", "content": "newer"}, e2.id, "think")
        log.append(e1)
        log.append(e2)
        log.append(e3)

        view = ContextView(log)
        forked = view.fork_at(e2.id)
        msgs = forked.materialize()
        assert len(msgs) == 2  # e2 and e3

    def test_start_and_end_id_filtering(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"role": "user", "content": "a"}, None, "think")
        e2 = make_log_entry("message", {"role": "user", "content": "b"}, e1.id, "think")
        e3 = make_log_entry("message", {"role": "user", "content": "c"}, e2.id, "think")
        log.append(e1)
        log.append(e2)
        log.append(e3)

        view = ContextView(log, start_id=e2.id, end_id=e2.id)
        msgs = view.materialize()
        assert len(msgs) == 1
        assert msgs[0]["content"] == "b"

    def test_empty_log_returns_empty(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        view = ContextView(log)
        assert view.materialize() == []
