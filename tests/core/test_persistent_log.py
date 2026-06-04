"""Tests for PersistentLog."""

from __future__ import annotations

import pytest

from consilium.plan.log_entry import LogEntry, make_log_entry
from consilium.plan.persistent_log import PersistentLog


class TestPersistentLog:
    def test_append_builds_indices(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {"content": "hello"}, None, "think")
        e2 = make_log_entry("message", {"content": "world"}, e1.id, "think")
        log.append(e1)
        log.append(e2)
        assert log.entry_count() == 2
        assert log.tail_id() == e2.id

    def test_get_entry_by_id(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="do")
        e = make_log_entry("diff", {"path": "foo.py"}, None, "do")
        log.append(e)
        found = log.get_entry(e.id)
        assert found is not None
        assert found.payload["path"] == "foo.py"

    def test_find_by_type(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {}, None, "think")
        e2 = make_log_entry("checkpoint", {"label": "c1"}, e1.id, "think")
        e3 = make_log_entry("message", {}, e2.id, "think")
        log.append(e1)
        log.append(e2)
        log.append(e3)
        msgs = log.find_entries_by_type("message")
        assert len(msgs) == 2
        checkpoints = log.find_entries_by_type("checkpoint")
        assert len(checkpoints) == 1

    def test_find_by_type_after_id(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {}, None, "think")
        e2 = make_log_entry("message", {}, e1.id, "think")
        e3 = make_log_entry("message", {}, e2.id, "think")
        log.append(e1)
        log.append(e2)
        log.append(e3)
        after = log.find_entries_by_type("message", after_id=e1.id)
        assert len(after) == 2

    def test_checkpoint_index(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="do")
        e = make_log_entry("checkpoint", {"label": "start"}, None, "do")
        log.append(e)
        found = log.find_checkpoint("start")
        assert found is not None
        assert found.id == e.id

    def test_load_from_disk(self, tmp_path) -> None:
        path = tmp_path / "test.jsonl"
        log1 = PersistentLog(path, log_owner="think")
        e = make_log_entry("message", {"content": "persisted"}, None, "think")
        log1.append(e)

        log2 = PersistentLog(path, log_owner="think")
        assert log2.entry_count() == 1
        assert log2.get_entry(e.id) is not None

    def test_prev_id_mismatch_raises(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e1 = make_log_entry("message", {}, None, "think")
        log.append(e1)
        e2 = make_log_entry("message", {}, "wrong_prev", "think")
        with pytest.raises(ValueError, match="prev_id mismatch"):
            log.append(e2)

    def test_duplicate_id_raises(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e = make_log_entry("message", {}, None, "think")
        log.append(e)
        # Manually create a second entry with the same id but correct prev_id
        duplicate = LogEntry(
            id=e.id, type="message", payload={}, prev_id=e.id,
            timestamp=999.0, log_owner="think",
        )
        with pytest.raises(ValueError, match="Duplicate entry id"):
            log.append(duplicate)

    def test_log_owner_mismatch_raises(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        e = make_log_entry("message", {}, None, "do")
        with pytest.raises(ValueError, match="log_owner mismatch"):
            log.append(e)

    def test_empty_log_tail_is_none(self, tmp_path) -> None:
        log = PersistentLog(tmp_path / "test.jsonl", log_owner="think")
        assert log.tail_id() is None
        assert log.entry_count() == 0
