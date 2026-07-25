# Phase 6A: CLI Dual-Process Support for Think + Do over Wire

## Summary

Remove the artificial restriction that prevents Do mode from running over the Wire (JSON-RPC) protocol. Add lightweight peer-status file coordination so two CLI processes (Think + Do) on the same workDir can discover each other's existence and state. This is the prerequisite for the extension's dual-tab MetaSession architecture.

**No daemon, no socket server, no rewrite.** Two independent `consilium --wire` processes. One happens to be Think (default), the other is Do (`--do`). They coordinate via a small JSON file in the shared sessions directory.

---

## Prerequisites

- Phase 5A complete (wire protocol query handlers: `query_logs`, `fetch_plan`, `trace_entry`)
- Phase 6a (PersistentLog parallel logging) complete
- `uv run pytest` passes in `main`

---

## Task 1: Remove the `--do` + `--wire` Guard

### File
`src/consilium/cli/__init__.py`

### Change
Lines 514-518:

```python
# BEFORE
    if do_mode and (acp_mode or wire_mode):
        raise typer.BadParameter(
            "Do mode cannot be combined with ACP or Wire UI (yet)",
            param_hint="--do",
        )
```

Replace with a **warning** instead of a hard error:

```python
# AFTER
    if do_mode and (acp_mode or wire_mode):
        logger.warning(
            "Do mode over Wire/ACP is experimental. "
            "Some interactive features may not work correctly."
        )
```

**Rationale:** The guard was conservative. Do mode + Wire works technically -- `KimiSoul` is a `Soul`, `WireServer` accepts any `Soul`. The only missing pieces are peer coordination (this phase) and extension-side tab UI (Phase 6B+).

### Verification
Run:
```bash
uv run python -m consilium --do --wire --plan-file plan/index.md --phase phase-01
```
Should start without `BadParameter` error. Process should initialize wire server and wait for JSON-RPC messages.

---

## Task 2: Peer Status File I/O

### New File
`src/consilium/peer_status.py`

### Purpose
A tiny module to read/write a shared status file in the workDir's sessions directory. Both Think and Do processes read/write this file. It is **not** a lock file -- it is advisory status sharing.

### Code

```python
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from consilium.utils.io import atomic_json_write
from consilium.utils.logging import logger


@dataclass(slots=True)
class PeerStatus:
    """Status of a single peer process."""

    session_id: str
    pid: int
    mode: str  # "think" | "do"
    status: str  # "idle" | "working" | "awaiting_review" | "stopped"
    updated_at: float


@dataclass(slots=True)
class PeerStatusFile:
    """Combined status for both peers on a workDir."""

    think: PeerStatus | None = None
    do: PeerStatus | None = None


def _status_file_path(sessions_dir: Path) -> Path:
    return sessions_dir / ".peer-status.json"


def read_peer_status(sessions_dir: Path) -> PeerStatusFile:
    """Read peer status from disk. Returns empty if file missing."""
    path = _status_file_path(sessions_dir)
    if not path.exists():
        return PeerStatusFile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PeerStatusFile(
            think=PeerStatus(**data["think"]) if data.get("think") else None,
            do=PeerStatus(**data["do"]) if data.get("do") else None,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Corrupt peer status file, resetting: {path}", path=path)
        return PeerStatusFile()


def write_peer_status(sessions_dir: Path, status: PeerStatusFile) -> None:
    """Atomically write peer status to disk."""
    path = _status_file_path(sessions_dir)
    payload: dict[str, dict[str, object] | None] = {}
    if status.think:
        payload["think"] = asdict(status.think)
    if status.do:
        payload["do"] = asdict(status.do)
    atomic_json_write(payload, path)


def update_own_peer_status(
    sessions_dir: Path,
    session_id: str,
    mode: str,
    status: str,
) -> None:
    """Update this process's entry in the peer status file."""
    peer = read_peer_status(sessions_dir)
    entry = PeerStatus(
        session_id=session_id,
        pid=os.getpid(),
        mode=mode,
        status=status,
        updated_at=__import__("time").time(),
    )
    if mode == "think":
        peer.think = entry
    else:
        peer.do = entry
    write_peer_status(sessions_dir, peer)


def clear_own_peer_status(sessions_dir: Path, mode: str) -> None:
    """Remove this process's entry on clean shutdown."""
    peer = read_peer_status(sessions_dir)
    if mode == "think":
        peer.think = None
    else:
        peer.do = None
    write_peer_status(sessions_dir, peer)
```

### Notes
- `atomic_json_write` already exists in `utils/io.py` (used by `save_metadata`).
- No file locking needed. Concurrent overwrites are acceptable -- last writer wins, and the file is tiny.
- Stale detection: consumers should check `pid` exists (`os.kill(pid, 0)` on Unix; `psutil.pid_exists(pid)` cross-platform).

---

## Task 3: WireServer Lifecycle Integration

### File
`src/consilium/wire/server.py`

### Changes

**3A. Add session and mode to `__init__`:**

```python
# BEFORE
class WireServer:
    def __init__(self, soul: Soul):
        self._reader: asyncio.StreamReader | None = None
        ...
        self._soul = soul
        self._cancel_event: asyncio.Event | None = None

# AFTER
class WireServer:
    def __init__(self, soul: Soul, session: Session | None = None, mode: str = "think"):
        self._reader: asyncio.StreamReader | None = None
        ...
        self._soul = soul
        self._session = session
        self._mode = mode
        self._cancel_event: asyncio.Event | None = None
```

**Import `Session` at the top of `server.py` if not already imported.**

**3B. Write peer status on start, clear on shutdown:**

In `serve()`, after stdio streams are set up but before the main loop:

```python
# In serve(), after self._write_task = asyncio.create_task(self._write_loop())
if self._session is not None:
    from consilium.peer_status import update_own_peer_status
    update_own_peer_status(
        self._session.work_dir_meta.sessions_dir,
        self._session.id,
        self._mode,
        "idle",
    )
```

In the `finally` block of `serve()`, before or after `await self._shutdown()`:

```python
# In finally block
if self._session is not None:
    from consilium.peer_status import clear_own_peer_status
    clear_own_peer_status(
        self._session.work_dir_meta.sessions_dir,
        self._mode,
    )
```

**3C. Update peer status around prompt handling:**

In `_handle_prompt()`, wrap the soul run to reflect working/idle:

```python
async def _handle_prompt(self, msg: JSONRPCPromptMessage) -> ...:
    # ... existing validation ...
    
    if self._session is not None:
        from consilium.peer_status import update_own_peer_status
        update_own_peer_status(
            self._session.work_dir_meta.sessions_dir,
            self._session.id,
            self._mode,
            "working",
        )
    
    try:
        # ... existing run logic ...
    finally:
        if self._session is not None:
            from consilium.peer_status import update_own_peer_status
            update_own_peer_status(
                self._session.work_dir_meta.sessions_dir,
                self._session.id,
                self._mode,
                "idle",
            )
```

---

## Task 4: Update WireServer Call Sites

### 4A. Think mode wire path

**File:** `src/consilium/cli/__init__.py` (around line 883)

```python
# BEFORE
                            server = WireServer(think_soul)
                            await server.serve()

# AFTER
                            server = WireServer(think_soul, session=session, mode="think")
                            await server.serve()
```

### 4B. Do mode wire path

**File:** `src/consilium/app.py` (around line 930-935)

```python
# BEFORE
    async def run_wire_stdio(self) -> None:
        from consilium.wire.server import WireServer

        async with self._env():
            server = WireServer(self._soul)
            await server.serve()

# AFTER
    async def run_wire_stdio(self) -> None:
        from consilium.wire.server import WireServer

        async with self._env():
            server = WireServer(self._soul, session=self.session, mode="do")
            await server.serve()
```

---

## Task 5: Add `get_peer_status` Wire Endpoint

### 5A. Add message type

**File:** `src/consilium/wire/jsonrpc.py`

Add after `JSONRPCTraceMessage`:

```python
class JSONRPCPeerStatusMessage(_MessageBase):
    method: Literal["get_peer_status"] = "get_peer_status"
    id: str
    params: JsonType | None = None
```

Update `JSONRPCInMessage` union:

```python
type JSONRPCInMessage = (
    JSONRPCSuccessResponse
    | JSONRPCErrorResponse
    | JSONRPCInitializeMessage
    | JSONRPCPromptMessage
    | JSONRPCSteerMessage
    | JSONRPCReplayMessage
    | JSONRPCSetPlanModeMessage
    | JSONRPCCancelMessage
    | JSONRPCLogQueryMessage
    | JSONRPCPlanFetchMessage
    | JSONRPCTraceMessage
    | JSONRPCPeerStatusMessage  # NEW
)
```

Update `JSONRPC_IN_METHODS`:

```python
JSONRPC_IN_METHODS = {
    "initialize",
    "prompt",
    "steer",
    "replay",
    "set_plan_mode",
    "cancel",
    "query_logs",
    "fetch_plan",
    "trace_entry",
    "get_peer_status",  # NEW
}
```

### 5B. Add handler in WireServer

**File:** `src/consilium/wire/server.py`

In `_dispatch_msg()`, add case:

```python
case JSONRPCPeerStatusMessage():
    resp = await self._handle_peer_status(msg)
```

Add handler method:

```python
async def _handle_peer_status(
    self, msg: JSONRPCPeerStatusMessage
) -> JSONRPCSuccessResponse | JSONRPCErrorResponse:
    if self._session is None:
        return JSONRPCSuccessResponse(
            id=msg.id,
            result={"think": None, "do": None},
        )
    from consilium.peer_status import read_peer_status
    peer = read_peer_status(self._session.work_dir_meta.sessions_dir)
    return JSONRPCSuccessResponse(
        id=msg.id,
        result={
            "think": asdict(peer.think) if peer.think else None,
            "do": asdict(peer.do) if peer.do else None,
        },
    )
```

**Note:** Import `asdict` from `dataclasses` at the top of `server.py`.

---

## Task 6: Tests

### 6A. Peer status I/O tests

**New file:** `tests/core/test_peer_status.py`

```python
import os
import tempfile
from pathlib import Path

import pytest

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
```

### 6B. Wire endpoint test

**New file:** `tests/wire/test_peer_status_endpoint.py`

```python
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from consilium.peer_status import update_own_peer_status
from consilium.wire.jsonrpc import JSONRPCPeerStatusMessage
from consilium.wire.server import WireServer
from consilium.wire.types import ClientCapabilities, ClientInfo


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
```

---

## Acceptance Criteria

- [x] `uv run pytest` passes (all existing tests + new tests)
- [x] `consilium --do --wire --plan-file plan/index.md --phase phase-01` starts without error
- [x] `consilium --wire` (Think mode) still works normally
- [x] Running both Think and Do on the same workDir creates `.peer-status.json` with both entries
- [x] Closing either process removes its entry from `.peer-status.json`
- [x] Wire `get_peer_status` request returns correct peer data
- [x] No file locking errors when both processes write status concurrently

---

## Implementation Order

1. **Task 2** -- Create `peer_status.py` + tests (`test_peer_status.py`)
2. **Task 1** -- Remove `--do` + `--wire` guard
3. **Task 3** -- WireServer lifecycle integration
4. **Task 4** -- Update call sites
5. **Task 5** -- Add `get_peer_status` endpoint + tests
6. **Task 6** -- Run full test suite, fix any regressions

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Do mode over Wire untested | Smoke test manually after guard removal |
| Concurrent file writes corrupt JSON | `atomic_json_write` + corrupt-file handler |
| ThinkSoul + WireServer edge cases | ThinkSoul is a Soul subclass; WireServer only uses Soul protocol |
| Do git stash conflicts if two Do processes run | Out of scope -- extension ensures only one Do per workDir |
| WireServer `_approval_runtime` is None for ThinkSoul | Correct behavior -- Think mode has no approval queue |

---

## Downstream

After this phase completes, the extension can:
1. Spawn two `consilium --wire` processes (Think + Do) for a single workDir
2. Query `get_peer_status` to discover the peer's session_id
3. Proceed with extension Phase 6B (MetaSession model + dual-tab UI)
