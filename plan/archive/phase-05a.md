# Phase 5A Implementation Plan: Wire Protocol Extensions (CLI Side)

**Status:** PLANNED — approved, ready for execution.

**Dependencies:** Phase 6a (Persistent Log Architecture) ✅

---

## Goal
Enable the VS Code: extension to query persistent logs, plan documents, and cross-log traces from the CLI via the existing JSON-RPC wire protocol. This is **CLI-side only** work; extension-side changes are Phase 5B.

## Key Finding: Transport Architecture

The current wire protocol is **unidirectional server→client for requests**:
- Client → Server (inbound): `initialize`, `prompt`, `steer`, `replay`, `set_plan_mode`, `cancel`
- Server → Client (outbound): `event` (fire-and-forget), `request` (expects response)
- Client responds to server requests with `JSONRPCSuccessResponse` / `JSONRPCErrorResponse`

**Phase 5A adds the missing direction:** client-initiated queries that return data.

## Approach: New JSON-RPC Methods (Not WireMessage Types)

Rather than adding new `WireMessage` types to the `Event` union, we add new JSON-RPC inbound methods:

| Method | Direction | Purpose |
|--------|-----------|---------|
| `query_logs` | Client → Server | Query persistent log entries |
| `fetch_plan` | Client → Server | Read plan markdown files |
| `trace_entry` | Client → Server | Cross-log traceability |

**Why plain JSON-RPC results instead of Wire Events?**
1. Simpler: no new Pydantic models in `wire/types.py`
2. No `Event` union bloat — these are not LLM-turn events
3. Direct request/response pattern matches what we need
4. Easier to test — just assert on JSON result objects
5. Extension's `ProtocolClient.sendRequest()` already supports arbitrary methods

## API Specification

### `query_logs`

**Request params:**
```json
{
  "session_id": "think-abc123",
  "log_owner": "think",
  "filter_type": "diff",
  "after_id": "entry-uuid-456",
  "limit": 50
}
```

**Response result:**
```json
{
  "entries": [
    {
      "id": "entry-uuid-789",
      "type": "diff",
      "payload": { "path": "src/main.py", "operation": "edit" },
      "prev_id": "entry-uuid-456",
      "timestamp": 1716580000.0,
      "log_owner": "do"
    }
  ],
  "has_more": false
}
```

**Error cases:**
- `INVALID_PARAMS` — missing `session_id` or `log_owner`
- `INTERNAL_ERROR` — log file read failure

### `fetch_plan`

**Request params:**
```json
{
  "plan_file": "plan/index.md"
}
```

**Response result:**
```json
{
  "content": "# Plan\n\n| Phase | Title | Status |...",
  "parsed": {
    "phases": [
      { "phase_id": "phase-01", "title": "Setup", "status": "implemented", "locked": true }
    ]
  }
}
```

**Error cases:**
- `INVALID_PARAMS` — missing `plan_file`
- `METHOD_NOT_FOUND` equivalent — file not found (use `INVALID_PARAMS` with message)

### `trace_entry`

**Request params:**
```json
{
  "direction": "think_to_do",
  "source_session_id": "think-abc123",
  "target_session_id": "do-xyz789",
  "entry_id": "entry-uuid-789"
}
```

**Response result:**
```json
{
  "linked_entries": [
    { "id": "entry-uuid-111", "type": "message", "payload": {...}, ... }
  ]
}
```

**Error cases:**
- `INVALID_PARAMS` — missing required fields
- `INTERNAL_ERROR` — log files missing or entry not found

## Files to Modify

### 1. `src/kimi_cli/wire/jsonrpc.py`

Add three new JSON-RPC message classes and update unions:

```python
class JSONRPCLogQueryMessage(_MessageBase):
    class Params(BaseModel):
        session_id: str
        log_owner: str
        filter_type: str | None = None
        after_id: str | None = None
        limit: int = 100

    method: Literal["query_logs"] = "query_logs"
    id: str
    params: Params


class JSONRPCPlanFetchMessage(_MessageBase):
    class Params(BaseModel):
        plan_file: str

    method: Literal["fetch_plan"] = "fetch_plan"
    id: str
    params: Params


class JSONRPCTraceMessage(_MessageBase):
    class Params(BaseModel):
        direction: str  # "think_to_do" | "do_to_think"
        source_session_id: str
        target_session_id: str
        entry_id: str

    method: Literal["trace_entry"] = "trace_entry"
    id: str
    params: Params
```

Update:
- `JSONRPCInMessage` union to include the three new types
- `JSONRPC_IN_METHODS` to add `"query_logs"`, `"fetch_plan"`, `"trace_entry"`

### 2. `src/kimi_cli/wire/server.py`

Add dispatch cases and handlers:

```python
async def _dispatch_msg(self, msg: JSONRPCInMessage) -> None:
    match msg:
        # ... existing cases ...
        case JSONRPCLogQueryMessage():
            resp = await self._handle_log_query(msg)
        case JSONRPCPlanFetchMessage():
            resp = await self._handle_plan_fetch(msg)
        case JSONRPCTraceMessage():
            resp = await self._handle_trace(msg)
```

Handler implementations:

**`_handle_log_query`:**
1. Resolve log path: `~/.kimi/{log_owner}_logs/{session_id}.jsonl`
2. Load `PersistentLog(path, log_owner)`
3. Call `find_entries_by_type(filter_type, after_id)`
4. Serialize entries with `entry.to_dict()`
5. Apply limit, return `{"entries": [...], "has_more": bool}`

**`_handle_plan_fetch`:**
1. Resolve `plan_file` relative to current working directory
2. Validate path is within CWD (path traversal guard)
3. Read file content
4. If `plan/index.md`, parse with `parse_plan_directory_from_path()` and include structured `phases` in `parsed`
5. Return `{"content": str, "parsed": {...} | null}`

**`_handle_trace`:**
1. Load source and target PersistentLogs from session IDs
2. Get the entry from the appropriate log
3. Call `trace_think_to_do()` or `trace_do_to_think()` from `bridge.py`
4. Serialize results, return `{"linked_entries": [...]}`

### 3. `src/kimi_cli/plan/persistent_log.py`

Add a factory method for resolving logs by session ID:

```python
@classmethod
def for_session(cls, session_id: str, log_owner: str) -> PersistentLog:
    """Load a persistent log for a given session."""
    from pathlib import Path
    log_dir = Path.home() / ".kimi" / f"{log_owner}_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return cls(log_dir / f"{session_id}.jsonl", log_owner=log_owner)
```

Also verify `find_entries_by_type()` supports `after_id=None` (returns all).

### 4. `src/kimi_cli/plan/bridge.py` (verify only)

Confirm `trace_think_to_do()` and `trace_do_to_think()` can be called with log objects loaded by `PersistentLog.for_session()`. No changes expected unless interfaces don't match.

## Testing Strategy

Create `tests/core/test_wire_queries.py`:

| Test | What it checks |
|------|----------------|
| `test_handle_log_query_returns_entries` | Creates a temp log, appends entries, queries via `_handle_log_query`, asserts correct entries returned |
| `test_handle_log_query_pagination` | Appends 5 entries, queries with `limit=2`, asserts `has_more=True` and exactly 2 entries |
| `test_handle_log_query_filter_by_type` | Mixed entry types, filter returns only matching |
| `test_handle_log_query_after_id` | `after_id` filters to entries after that ID |
| `test_handle_log_query_invalid_params` | Missing `session_id` returns `INVALID_PARAMS` |
| `test_handle_plan_fetch_returns_content` | Creates temp `plan/index.md`, fetches, asserts content and parsed phases |
| `test_handle_plan_fetch_path_traversal` | `plan_file="../etc/passwd"` returns `INVALID_PARAMS` |
| `test_handle_plan_fetch_not_found` | Nonexistent file returns error response |
| `test_handle_trace_think_to_do` | Creates Think+Do logs with bridge entries, traces, asserts linked entries |
| `test_handle_trace_invalid_direction` | Invalid `direction` value returns `INVALID_PARAMS` |

**Test fixtures:** Use `tmp_path` for log/plan files, `runtime` fixture for `WireServer` construction. Pattern follows `test_wire_server_steer.py`.

## Extension-Side Implications (Phase 5B Preview)

No code changes in this repo, but Phase 5B will need:

1. **`agent_sdk/protocol.ts`**: Add public methods:
   ```typescript
   queryLogs(params: LogQueryParams): Promise<LogQueryResult>
   fetchPlan(params: PlanFetchParams): Promise<PlanFetchResult>
   traceEntry(params: TraceParams): Promise<TraceResult>
   ```
   These are thin wrappers around `sendRequest(method, params)`.

2. **No schema changes needed**: Results are plain JSON objects, not WireMessage events. The extension can define TypeScript interfaces locally.

3. **`CLIManager`**: Expose the new `ProtocolClient` methods to handlers.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| New JSON-RPC methods break old extension clients | Old clients simply won't send these methods; server ignores unknown methods gracefully (already handled in `_dispatch_msg` match) |
| Path traversal in `fetch_plan` | Use `Path.is_relative_to()` guard; reject paths outside CWD |
| Large log files cause memory issues | `limit` enforced server-side; client can paginate with `after_id` |
| `PersistentLog.for_session()` doesn't exist | Create it as part of this phase (trivial factory) |
| Trace requires both logs to exist | Return empty `linked_entries` if either log missing |

## Estimated Effort

1 day. The pattern is established (`_handle_steer`, `_handle_prompt`), the APIs are thin wrappers over existing modules (`PersistentLog`, `bridge`, `parse_plan_directory_from_path`), and tests follow existing wire test patterns.

## Rollback

All changes are additive. Removing the three JSON-RPC methods and their handlers reverts to prior behavior with no data loss.
