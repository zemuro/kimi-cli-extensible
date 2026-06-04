"""Tests for peer status file I/O."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from consilium.peer_status import (
    PeerStatus,
    PeerStatusFile,
    clear_own_peer_status,
    read_peer_status,
    update_own_peer_status,
    write_peer_status,
)


class TestPeerStatus:
    def test_read_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            result = read_peer_status(Path(td))
            assert result.think is None
            assert result.do is None

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            status = PeerStatusFile(
                think=PeerStatus(
                    session_id="think-123",
                    pid=os.getpid(),
                    mode="think",
                    status="idle",
                    updated_at=0.0,
                ),
            )
            write_peer_status(Path(td), status)
            result = read_peer_status(Path(td))
            assert result.think is not None
            assert result.think.session_id == "think-123"
            assert result.do is None

    def test_update_own_creates_entry(self):
        with tempfile.TemporaryDirectory() as td:
            update_own_peer_status(Path(td), "sess-1", "think", "working")
            result = read_peer_status(Path(td))
            assert result.think is not None
            assert result.think.session_id == "sess-1"
            assert result.think.mode == "think"
            assert result.think.status == "working"

    def test_clear_own_removes_entry(self):
        with tempfile.TemporaryDirectory() as td:
            update_own_peer_status(Path(td), "sess-1", "think", "working")
            clear_own_peer_status(Path(td), "think")
            result = read_peer_status(Path(td))
            assert result.think is None

    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".peer-status.json"
            path.write_text("not json")
            result = read_peer_status(Path(td))
            assert result.think is None
            assert result.do is None

    def test_both_peers_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            update_own_peer_status(Path(td), "think-1", "think", "idle")
            update_own_peer_status(Path(td), "do-1", "do", "working")
            result = read_peer_status(Path(td))
            assert result.think is not None
            assert result.think.session_id == "think-1"
            assert result.do is not None
            assert result.do.session_id == "do-1"

    def test_stale_entry_removed(self):
        with tempfile.TemporaryDirectory() as td:
            # Write a peer status with a non-existent PID
            status = PeerStatusFile(
                think=PeerStatus(
                    session_id="dead",
                    pid=999999,
                    mode="think",
                    status="idle",
                    updated_at=0.0,
                ),
            )
            write_peer_status(Path(td), status)
            result = read_peer_status(Path(td))
            assert result.think is None
