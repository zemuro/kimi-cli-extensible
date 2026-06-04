"""Tests for wire protocol events."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from consilium.do.session import DoSession
from consilium.soul import get_wire_or_none
from consilium.wire.types import ToolFileModifiedEvent


class MockToolCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments
        self.id = "tc_123"


class MockToolResult:
    def __init__(self) -> None:
        self.tool_call_id = "tc_123"


@pytest.fixture
def mock_soul() -> MagicMock:
    soul = MagicMock()
    soul._runtime.session.id = "test-session-id"
    soul._current_turn_index = 1
    return soul


@pytest.fixture
def do_session(mock_soul: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DoSession:
    from consilium.do import journal as journal_mod
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path / "do_sessions")
    return DoSession(mock_soul, work_dir=tmp_path)


@pytest.mark.asyncio
async def test_wire_tool_file_modified_event(do_session: DoSession, tmp_path: Path) -> None:
    await do_session.start()

    file_path = tmp_path / "test.py"
    file_path.write_text("original\n")

    tool_call = MockToolCall("write_file", json.dumps({"path": "test.py", "content": "modified\n"}))
    await do_session.capture_baseline(tool_call)

    file_path.write_text("modified\n")

    tool_result = MockToolResult()

    mock_wire = MagicMock()
    captured_events = []
    mock_wire.soul_side.send = captured_events.append

    with patch("consilium.soul.get_wire_or_none", return_value=mock_wire):
        await do_session.on_tool_result(tool_call, tool_result)

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, ToolFileModifiedEvent)
    assert event.type == "tool_file_modified"
    assert event.path == "test.py"
    assert event.tool_name == "write_file"
    assert event.turn_index == 1
    assert event.lines_added == 1
    assert event.lines_removed == 1
