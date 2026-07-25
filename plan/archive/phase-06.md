# Phase 6: Persistent Log Architecture

**Status: IMPLEMENTED — Phase 6a (parallel logging) complete. 35 new tests passing. Phases 6b–6d deferred.**

**Implementation report:** `plan/reports/phase-6-report.md`

**Design doc:** `scratch/phase_6_persistent_log_design.md` (Option C — Disjoint Persistent Logs with Cross-Reference Bridge)

**Decision driver:** Phase 5 (VS Code: Extension) is the primary user interface. The extension needs rich history, traceability, and undo capabilities that are impossible with the current split storage (Think JSONL + Do journal). Implement Phase 6 **before** Phase 5 so the extension builds against a clean log API.

**Revised dependency:** Phase 5 now depends on Phase 6, not vice versa.

---

## Problem

Current storage is fragmented and opaque:

| Storage | Format | Owned by | Problems |
|---------|--------|----------|----------|
| Think sessions | JSONL | Think | Edits/deletes rewrite history; no compaction trail |
| Do journal | JSONL | Do | Partial audit trail; no link to Think reasoning |
| Wire events | JSONL | Server | Ephemeral; not queryable |
| Context | JSONL | Soul | Duplicated from Think sessions |

**Consequences:**
- No Think → Do traceability ("Why was this file changed?")
- Undo limited to tail deletions
- Fork requires copying files (slow)
- Extension can only show current session state

## Solution

Two independent append-only logs (Think log, Do log) linked by cross-reference entries. Each log is owned by exactly one mode. Views are materialized slices of a log. Compaction appends summary entries; views choose whether to use them.

### Key properties

- **Immutable log** — append-only, never rewrite, hash-linked
- **Materialized views** — ephemeral slices of the log, cached
- **Cross-references** — pointers between Think and Do logs (not inclusions)
- **Extension-friendly** — JSONL format = trivial streaming over wire protocol

---

## Data Model

### LogEntry (universal schema)

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True, slots=True)
class LogEntry:
    id: str              # UUID, globally unique
    type: str            # Entry type (see table below)
    payload: dict[str, Any]  # Type-specific data
    prev_id: str | None  # Previous entry in this log (linked list)
    timestamp: float     # Unix float (Phase 10 unified format)
    log_owner: str       # "think" | "do"
```

### Entry Types

| Type | Owner | Payload | Extension Display |
|------|-------|---------|-------------------|
| `system` | T/D | `{"prompt": "..."}` | Collapsible system context |
| `message` | T/D | `{"role": "user\|assistant", "content": "..."}` | Chat bubble |
| `edit` | T | `{"target_id": "...", "new_content": "..."}` | "Edited" annotation |
| `delete` | T | `{"target_id": "..."}` | "Deleted" strikethrough |
| `checkpoint` | T/D | `{"label": "...", "git_ref": "..."}` | Named save point |
| `compact` | T/D | `{"covers": ["..."], "summary": "...", "preserved_ids": ["..."]}` | Summary card |
| `tool_call` | D | `{"tool": "...", "args": {...}}` | Tool invocation |
| `tool_result` | D | `{"output": "...", "exit_code": 0}` | Tool output |
| `diff` | D | `{"path": "...", "baseline_hash": "...", "post_hash": "..."}` | Inline diff |
| `review` | D | `{"feasible": true, "risks": [...]}` | Review report card |
| `bridge_out` | T | `{"target_session_id": "...", "pushed_entries": ["..."]}` | → Do push |
| `bridge_in` | D | `{"source_session_id": "...", "source_entry": "..."}` | ← Think receive |
| `phase_complete` | D | `{"phase_id": "...", "report_path": "..."}` | Phase completion |

**Extension metadata:** Each entry type has an optional `display` field in payload:
```python
{"icon": "chat", "label": "User message", "collapsible": false}
```

### Storage Layout

```
~/.consilium/think_logs/{session_id}.jsonl   # Think log
~/.consilium/do_logs/{session_id}.jsonl      # Do log
~/.consilium/log_index.json                  # Session → log file mapping
```

Append-only. Never rewrite. Rotation for archival only.

---

## Core Classes

### PersistentLog

```python
class PersistentLog:
    """Append-only log with in-memory indices."""
    
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[LogEntry] = []
        self._id_index: dict[str, int] = {}       # entry_id → list index
        self._type_index: dict[str, list[str]] = {}  # type → entry_ids
        self._checkpoint_index: dict[str, str] = {}  # label → entry_id
        self._tail_id: str | None = None
        self._load()
    
    def append(self, entry: LogEntry) -> None:
        """Append entry. Validate prev_id links."""
        if self._tail_id is not None and entry.prev_id != self._tail_id:
            raise ValueError(f"prev_id mismatch: {entry.prev_id} != {self._tail_id}")
        self._entries.append(entry)
        self._id_index[entry.id] = len(self._entries) - 1
        self._type_index.setdefault(entry.type, []).append(entry.id)
        if entry.type == "checkpoint":
            self._checkpoint_index[entry.payload["label"]] = entry.id
        self._tail_id = entry.id
        self._append_to_disk(entry)
    
    def get_entry(self, entry_id: str) -> LogEntry | None:
        idx = self._id_index.get(entry_id)
        return self._entries[idx] if idx is not None else None
    
    def find_entries_by_type(self, type: str, after_id: str | None = None) -> list[LogEntry]:
        """All entries of type, optionally after a given entry."""
        ...
    
    def find_checkpoint(self, label: str) -> LogEntry | None:
        entry_id = self._checkpoint_index.get(label)
        return self.get_entry(entry_id) if entry_id else None
    
    def tail_id(self) -> str | None:
        return self._tail_id
    
    def _load(self) -> None:
        """Load from disk on init. Build indices."""
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                self._load_entry(json.loads(line))
    
    def _append_to_disk(self, entry: LogEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.__dict__, default=str) + "\n")
```

### ContextView

```python
class ContextView:
    """Materialized slice of a log."""
    
    def __init__(
        self,
        log: PersistentLog,
        start_id: str | None = None,
        end_id: str | None = None,
        use_compacts: bool = True,
    ) -> None:
        self.log = log
        self.start_id = start_id or log._entries[0].id if log._entries else None
        self.end_id = end_id
        self.use_compacts = use_compacts
        self._cached_messages: list[Message] | None = None
        self._cache_tail: str | None = None
    
    def materialize(self) -> list[Message]:
        """Walk log from start to end, resolve edits/deletes/compacts."""
        if self._cached_messages is not None and self._cache_tail == self.log.tail_id():
            return self._cached_messages
        
        messages = []
        seen_ids: set[str] = set()
        edited: dict[str, str] = {}  # target_id → new_content
        deleted: set[str] = set()
        
        for entry in self._walk():
            if entry.type == "message":
                if entry.id not in deleted:
                    content = edited.get(entry.id, entry.payload["content"])
                    messages.append(Message(role=entry.payload["role"], content=content))
                    seen_ids.add(entry.id)
            elif entry.type == "edit":
                edited[entry.payload["target_id"]] = entry.payload["new_content"]
            elif entry.type == "delete":
                deleted.add(entry.payload["target_id"])
            elif entry.type == "compact" and self.use_compacts:
                # Insert summary as system message
                messages.append(Message(
                    role="system",
                    content=f"[Compacted] {entry.payload['summary']}"
                ))
                # Preserve explicitly kept IDs
                for preserved_id in entry.payload.get("preserved_ids", []):
                    preserved = self.log.get_entry(preserved_id)
                    if preserved and preserved.type == "message":
                        messages.append(Message(
                            role=preserved.payload["role"],
                            content=preserved.payload["content"]
                        ))
        
        self._cached_messages = messages
        self._cache_tail = self.log.tail_id()
        return messages
    
    def fork_at(self, entry_id: str) -> ContextView:
        """Create new view starting at entry_id (inclusive)."""
        return ContextView(self.log, start_id=entry_id, end_id=None)
    
    def _walk(self) -> Iterator[LogEntry]:
        """Iterate entries from start to end."""
        ...
```

---

## Bridge Protocol (Cross-References)

Think and Do logs are disjoint. Cross-references are **pointers**, not inclusions.

```python
# Think pushes to Do
think_log.append(LogEntry(
    id=f"bridge_t_{uuid.uuid4().hex[:8]}",
    type="bridge_out",
    payload={
        "target_session_id": do_session_id,
        "pushed_entries": [msg.id for msg in pushed_messages],
        "reason": "push_to_do",
    },
    prev_id=think_log.tail_id(),
    log_owner="think",
    timestamp=time.time(),
))

# Do receives from Think
do_log.append(LogEntry(
    id=f"bridge_d_{uuid.uuid4().hex[:8]}",
    type="bridge_in",
    payload={
        "source_session_id": think_session_id,
        "source_entry": bridge_out_id,
        "source_message_ids": [msg.id for msg in seeded_messages],
    },
    prev_id=do_log.tail_id(),
    log_owner="do",
    timestamp=time.time(),
))
```

**Traceability queries:**

```python
def trace_think_to_do(do_diff: LogEntry, do_log: PersistentLog, think_log: PersistentLog) -> list[LogEntry]:
    """What Think reasoning led to this Do change?"""
    bridge = do_log.find_last_before(do_diff.id, type="bridge_in")
    if not bridge:
        return []
    msg_ids = bridge.payload["source_message_ids"]
    return [think_log.get_entry(id) for id in msg_ids if think_log.get_entry(id)]
```

---

## Wire Protocol Extensions (for Extension)

The extension needs log query endpoints. Add to wire protocol:

```python
# New wire message types
class LogQueryRequest(BaseModel):
    session_id: str
    log_owner: str  # "think" | "do"
    query_type: str  # "all", "by_type", "after_id", "checkpoint"
    filter_type: str | None = None
    after_id: str | None = None

class LogQueryResponse(BaseModel):
    entries: list[dict]  # Serialized LogEntry
    total: int
    has_more: bool

class CrossReferenceRequest(BaseModel):
    session_id: str
    entry_id: str
    direction: str  # "think_to_do" | "do_to_think"

class CrossReferenceResponse(BaseModel):
    linked_entries: list[dict]
    source_session_id: str
    target_session_id: str
```

**Endpoints:**
- `POST /api/log/query` — Query log entries
- `POST /api/log/cross-reference` — Trace cross-log references
- `GET /api/log/sessions` — List all sessions with logs
- `GET /api/log/view/{session_id}` — Materialize current view

---

## Phase 6b+ Revised Plan: Think + Do Journal Storage Migration

**Status:** REVIEWED — plan rewritten after architectural review.

### Should we even do this?

**Probably not yet.** Phase 5A (wire protocol queries) + Phase 6a (parallel logging) already gives the extension everything it needs:
- Extension queries logs via `query_logs` / `fetch_plan` / `trace_entry`
- PersistentLog entries are written on every operation
- No UI feature is blocked by the CLI runtime still reading legacy storage

The 6b+ cutover is a **runtime-internal refactor** with no user-visible benefit. It only makes sense if:
1. We need runtime-level log queries (e.g., `/review` reading its own history)
2. We want to delete the parallel write overhead
3. We want a unified storage model for maintainability

If none of these are pressing, **skip 6b+ and go to Phase 5B** (extension-side integration).

---

### Scope (Narrowed)

**IN scope:**
- Think mode: `think/storage.py`, `think/history.py`, `think/context.py`, `think/models.py`, `think/slash.py`
- Do journal: `do/journal.py`, `do/session.py` (change tracking only)
- `app.py` entry point updates

**EXPLICITLY OUT of scope:**
- `soul/context.py` — Do mode conversation context manager. This is a separate system from the Do journal. Migrating it would require changes to `KimiSoul`, `soul/compaction.py`, and the entire agent loop.
- `soul/kimisoul.py` — Agent loop uses `self._context` directly.
- Wire protocol extensions — **DONE in Phase 5A**.

**Why exclude `soul/context.py`?**
Do mode has TWO storage systems:
1. `soul/context.py` — conversation history for the LLM loop (`context.jsonl`)
2. `do/journal.py` — change tracking metadata (diffs, reviews, checkpoints)

The 6b+ plan only addresses (2). Addressing (1) is a separate, larger refactor. If we later want to unify them, that's a new phase.

---

### Data Model Mismatch (The Hard Part)

Current `HistoryManager` uses **mutable** `ThinkMessage` objects:
```python
msg.compacted_into = summary_id      # mutation
msg.content = new_content            # mutation
msg.deleted = True                   # mutation
messages = messages[:idx]            # list slice (prune)
```

PersistentLog uses **immutable** `LogEntry` append-only:
```python
append(LogEntry(type="compact", ...))   # new entry
append(LogEntry(type="edit", ...))      # new entry
append(LogEntry(type="delete", ...))    # new entry
ContextView(log, end_id=...).materialize()  # new view (prune)
```

**Every `HistoryManager` operation needs redesign:**

| Operation | Current | New | Difficulty |
|-----------|---------|-----|------------|
| `add_message` | `messages.append()` | `log.append(ENTRY_MESSAGE)` | ✅ Easy |
| `edit_message` | `msg.content = new` | `log.append(ENTRY_EDIT)` | ✅ Easy |
| `delete_message` | `msg.deleted = True` | `log.append(ENTRY_DELETE)` | ✅ Easy |
| `compact` | Mutates `compacted_into`, inserts summary in-place | `log.append(ENTRY_COMPACT)` + view materializes summary | 🔴 **Hard** |
| `prune_after` | `messages = messages[:idx]` | `ContextView(log, end_id=target)` | ⚠️ Semantics differ |
| `fork_from` | Copies `messages` list | `ContextView.fork_at()` | ⚠️ Returns view, not copy |

**Compaction is the bottleneck.** Current code marks messages with `compacted_into` and filters them in `get_active_messages()`. With logs, compaction appends a single `compact` entry; `ContextView.materialize()` inserts the summary and skips the compacted range. All callers that expect `ThinkMessage` objects with `.compacted_into` fields will break.

---

### Files to Modify (Expanded)

| File | Change | Est. Time |
|------|--------|-----------|
| `think/history.py` | Rewrite all mutations as log appends; `get_active_messages()` becomes `ContextView.materialize()` | 2–3 days |
| `think/storage.py` | Remove parallel write; `save_session()` writes LogEntry sequence; `load_session()` reads from PersistentLog | 1 day |
| `think/context.py` | Build LLM context from `ContextView(log).materialize()` | 30 min |
| `think/models.py` | `ThinkSession.messages` becomes a `@property` or is removed; `ThinkMessage` may be replaced by plain dicts | 4 hrs |
| `think/slash.py` | Replace `history.session.messages` access (~14 call sites) | 2 hrs |
| `think/push.py` | Replace `session.messages` access (line 33) | 30 min |
| `think/plan_commands.py` | Replace `session.messages` access (line 249) | 30 min |
| `do/journal.py` | Remove parallel write; `record_diff/review/checkpoint` append LogEntry | 1 day |
| `do/session.py` | Read change history from ContextView instead of journal.jsonl | 4 hrs |
| `app.py` | Update `ThinkSession` construction to load from PersistentLog | 2 hrs |

**Total: 5–7 days** (not 2–3)

---

### Feature Flag

Even with zero shipped users, a simple feature flag saves debugging time:

```python
# consilium/config.py or env var
USE_PERSISTENT_LOG = os.environ.get("CONSILIUM_USE_PERSISTENT_LOG", "0") == "1"
```

- `0` (default): Uses legacy storage, but parallel writes still populate PersistentLog
- `1`: Uses PersistentLog for reads and writes

This lets you bisect issues by toggling the flag, without reverting commits.

---

### Implementation Order

| Order | Task | Files |
|-------|------|-------|
| 1 | Add feature flag | `config.py` or `plan/persistent_log.py` |
| 2 | Rewrite `HistoryManager` (hardest part) | `think/history.py` |
| 3 | Update `think/models.py` | `think/models.py` |
| 4 | Update `think/storage.py` (save/load) | `think/storage.py` |
| 5 | Update `think/context.py` | `think/context.py` |
| 6 | Update `think/slash.py`, `push.py`, `plan_commands.py` | `think/*.py` |
| 7 | Rewrite `do/journal.py` | `do/journal.py` |
| 8 | Update `do/session.py` | `do/session.py` |
| 9 | Update `app.py` | `app.py` |
| 10 | Tests | `tests/core/test_history.py`, `tests/core/test_journal.py`, etc. |

---

### Testing Requirements

| Test | Description |
|------|-------------|
| `test_history_add_message` | `add_message()` appends `message` entry |
| `test_history_edit_message` | `edit_message()` appends `edit` entry; view resolves it |
| `test_history_delete_message` | `delete_message()` appends `delete` entry; view excludes it |
| `test_history_compact` | `compact()` appends `compact` entry; view inserts summary + preserved |
| `test_history_prune` | `prune_after()` creates view with `end_id` |
| `test_history_fork` | `fork_from()` creates view with `start_id` |
| `test_storage_save_load` | `save_session()` + `load_session()` roundtrip via PersistentLog |
| `test_checkpoint_save_load` | `save_checkpoint()` + `load_checkpoint()` roundtrip |
| `test_journal_diff` | `record_diff()` appends `diff` entry |
| `test_journal_review` | `record_review()` appends `review` entry |
| `test_journal_checkpoint` | `record_checkpoint()` appends `checkpoint` entry |
| `test_feature_flag_off` | Flag off → uses legacy storage |
| `test_feature_flag_on` | Flag on → uses PersistentLog |

---

## Files to Create

```
src/consilium/plan/persistent_log.py    # ✅ DONE in 6a
src/consilium/plan/context_view.py      # ✅ DONE in 6a
src/consilium/plan/log_entry.py         # ✅ DONE in 6a
src/consilium/plan/bridge.py            # ✅ DONE in 6a

tests/core/test_persistent_log.py      # ✅ DONE in 6a
tests/core/test_context_view.py        # ✅ DONE in 6a
tests/core/test_bridge.py              # ✅ DONE in 6a
```

## Files to Modify (6b+)

| File | Changes |
|------|---------|
| `think/storage.py` | Remove parallel write; load/save from PersistentLog |
| `think/history.py` | Mutable → immutable operations |
| `think/context.py` | Read from ContextView |
| `think/models.py` | Remove `messages` list; session becomes log handle |
| `think/slash.py` | Replace `.messages` access |
| `think/push.py` | Replace `.messages` access |
| `think/plan_commands.py` | Replace `.messages` access |
| `do/journal.py` | Remove parallel write; append LogEntry |
| `do/session.py` | Read from ContextView |
| `app.py` | Load ThinkSession from PersistentLog |

---

## Dependencies

- **Phase 6a** — PersistentLog, ContextView, LogEntry must exist ✅
- **Phase 5A** — Wire protocol query handlers must exist ✅
- **Phase 10** — LogEntry.timestamp must be float ✅

**Downstream:** None. This is an internal refactor.

---

## Notes

- **Log format stays JSONL** — streamable over wire, human-readable, extension-friendly
- **Indices are in-memory only** — rebuilt on load. No separate index file to keep in sync.
- **Views are ephemeral** — not persisted to disk. Recreated on demand.
- **`soul/context.py` is NOT migrated in 6b+** — Do mode conversation context remains separate. If unification is needed later, it is a new phase.
- **Wire protocol extensions — DONE in Phase 5A.** See `plan/phase-05a.md` and `plan/reports/phase-5a-report.md`.
- **Old storage remains during migration** — parallel write gives rollback safety
