"""Tests for LogEntry dataclass and helpers."""

from __future__ import annotations

import pytest

from consilium.plan.log_entry import (
    VALID_ENTRY_TYPES,
    LogEntry,
    make_log_entry,
    new_entry_id,
)


class TestLogEntry:
    def test_creates_valid_entry(self) -> None:
        entry = LogEntry(
            id="le_123",
            type="message",
            payload={"content": "hello"},
            prev_id=None,
            timestamp=1716854400.0,
            log_owner="think",
        )
        assert entry.id == "le_123"
        assert entry.type == "message"

    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Invalid entry type"):
            LogEntry(
                id="le_123",
                type="invalid_type",
                payload={},
                prev_id=None,
                timestamp=1716854400.0,
                log_owner="think",
            )

    def test_to_dict_roundtrip(self) -> None:
        entry = make_log_entry(
            type="diff",
            payload={"path": "src/foo.py"},
            prev_id="le_prev",
            log_owner="do",
        )
        data = entry.to_dict()
        restored = LogEntry.from_dict(data)
        assert restored.id == entry.id
        assert restored.type == entry.type
        assert restored.payload == entry.payload
        assert restored.prev_id == entry.prev_id
        assert restored.timestamp == entry.timestamp
        assert restored.log_owner == entry.log_owner

    def test_from_dict_missing_optional_fields(self) -> None:
        data = {
            "id": "le_abc",
            "type": "checkpoint",
            "timestamp": 1716854400.0,
        }
        entry = LogEntry.from_dict(data)
        assert entry.payload == {}
        assert entry.prev_id is None
        assert entry.log_owner == "unknown"

    def test_new_entry_id_format(self) -> None:
        eid = new_entry_id()
        assert eid.startswith("le_")
        assert len(eid) > 3

    def test_new_entry_id_with_prefix(self) -> None:
        eid = new_entry_id("bridge")
        assert eid.startswith("bridge_")

    def test_make_log_entry_auto_generates_id_and_timestamp(self) -> None:
        entry = make_log_entry(
            type="message",
            payload={},
            prev_id=None,
            log_owner="think",
        )
        assert entry.id.startswith("le_")
        assert entry.timestamp > 0

    def test_all_valid_types_are_strings(self) -> None:
        for t in VALID_ENTRY_TYPES:
            assert isinstance(t, str)
            assert len(t) > 0
