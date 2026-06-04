"""Tests for the get_peer_status wire endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from consilium.peer_status import update_own_peer_status
from consilium.wire.jsonrpc import JSONRPCPeerStatusMessage
from consilium.wire.server import WireServer


class TestPeerStatusEndpoint:
    @pytest.fixture
    def mock_soul(self):
        soul = AsyncMock()
        soul.name = "test"
        soul.available_slash_commands = []
        soul.hook_engine = None
        return soul

    @pytest.fixture
    def mock_session(self, tmp_path):
        session = AsyncMock()
        session.id = "test-session"
        session.work_dir_meta.sessions_dir = tmp_path
        return session

    async def test_get_peer_status_returns_data(
        self, mock_soul, mock_session, tmp_path
    ):
        update_own_peer_status(tmp_path, "do-456", "do", "idle")
        server = WireServer(mock_soul, session=mock_session, mode="think")
        msg = JSONRPCPeerStatusMessage(id="req-1")
        resp = await server._handle_peer_status(msg)
        assert resp.result["do"]["session_id"] == "do-456"
        assert resp.result["think"] is None

    async def test_get_peer_status_no_session_returns_empty(self, mock_soul):
        server = WireServer(mock_soul)
        msg = JSONRPCPeerStatusMessage(id="req-1")
        resp = await server._handle_peer_status(msg)
        assert resp.result["think"] is None
        assert resp.result["do"] is None
