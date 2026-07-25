---
phase_id: phase-10
title: 10: Timestamp Format Unification
status: implemented
dependencies:
  - phase-09
files_involved:
  - src/kimi_cli/utils/timestamp.py
  - src/kimi_cli/token_tracker.py
  - src/kimi_cli/think/models.py
  - src/kimi_cli/think/storage.py
  - src/kimi_cli/think/history.py
  - src/kimi_cli/think/slash.py
  - src/kimi_cli/plan/models.py
  - src/kimi_cli/plan/parser.py
  - src/kimi_cli/plan/audit_report.py
  - src/kimi_cli/plan/handover.py
  - src/kimi_cli/plan/dispatch.py
  - src/kimi_cli/plan/docs_index.py
  - src/kimi_cli/do/journal.py
---

**Status: IMPLEMENTED — 993 tests passing.**

**Implementation report:** `scratch/reports/phase_10_report.md`

**Decision driver:** User analysis revealed three timestamp formats (ISO strings, `datetime` objects, Unix floats) with inconsistent timezone handling. Fork `datetime` fields are used for zero calculations — only display and serialization.

### Problem

| Format | Used in | Issue |
|---|---|---|
| ISO 8601 strings | Journal JSONL, token tracker CSV, Think storage | Verbose for machine files; humans don't read JSONL/CSV directly |
| `datetime` objects | Plan models, Think models | Naive (no timezone) in plan/think; timezone-aware only in journal; unnecessary third format |
| Unix `float` | Subagents, wire, approvals, background, notifications | Correct for protocol/runtime, upstream-compatible |

**Timezone inconsistency:**
- Journal uses `datetime.now(timezone.utc).isoformat()` ✅
- Plan models use `datetime.now()` (naive) 🔴
- Think models use `datetime.now()` (naive) 🔴

This means a journal entry and a plan model created at the same moment cannot be directly compared.

### Solution

**Single rule:** Unix `float` for everything internal; ISO 8601 only for human-facing Markdown output.

#### 10.1 Machine-readable files → Unix float

| File | Current | Target |
|---|---|---|
| `~/.kimi/do_sessions/{id}/journal.jsonl` | ISO string | Unix float |
| `~/.kimi/token_log/{date}.csv` | ISO string | Unix float |
| `~/.kimi/think_sessions/{id}.jsonl` | ISO string | Unix float |
| `~/.kimi/think_checkpoints/{name}.json` | ISO string | Unix float |
| `~/.kimi/think_outbox/{id}.json` | ISO string | Unix float |

**Migration:** On read, accept both ISO string and float for backward compatibility. On write, emit float.

#### 10.2 In-memory models → Unix float

| Model | Fields | Change |
|---|---|---|
| `ThinkMessage` | `timestamp`, `edited_at` | `float` (Unix timestamp) |
| `ThinkSession` | `created_at` | `float` |
| `PlanMetadata` | `created`, `last_updated` | `float` |
| `AuditReport` | `timestamp` | `float` |
| `DocEntry` | `last_updated` | `float` |
| `DocsIndex` | `version` | `float` |
| `Dispatch` | `dispatched_at` | `float` |
| `Handover` | `created_at` | `float` |

**Formatting at display time:**
```python
# Audit report rendering
from datetime import datetime, timezone
lines.append(f"_Generated: {datetime.fromtimestamp(report.timestamp, tz=timezone.utc).isoformat()}_")

# Handover rendering
lines.append(f"# Session Handover {datetime.fromtimestamp(h.created_at, tz=timezone.utc):%Y-%m-%d}")
```

#### 10.3 Human-facing Markdown → ISO 8601 (unchanged)

Plan frontmatter, audit reports, handovers, and any commentable documents keep ISO 8601 because humans read them.

```markdown
---
created: 2026-05-29
last_updated: 2026-05-29
---
```

Note: Plan frontmatter currently uses `date` (no time). This is acceptable — the precision of "day" is sufficient for plan documents.

#### 10.4 Timezone policy

**Rule:** All Unix floats are **implicitly UTC**. No exceptions.

**Display code must always use:**
```python
from datetime import datetime, timezone

datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
# → "2026-05-29T14:00:00+00:00"
```

**Common mistake to avoid:**
```python
# WRONG — produces naive datetime, depends on system timezone
datetime.fromtimestamp(ts).isoformat()
# → "2026-05-29T16:00:00" (if host is UTC+2)
```

**Enforcement:** Add a lint rule or code review checklist item: "Any `fromtimestamp()` call without `tz=timezone.utc` is a bug."

**Migration note:** Existing ISO strings in storage may have been written with `datetime.now()` (naive, local time). During backward-compat loading, naive ISO strings should be interpreted as UTC, not local time. If the string lacks `+00:00` suffix, append it before parsing:
```python
if isinstance(value, str) and not value.endswith("Z") and "+" not in value[-6:]:
    value = value + "+00:00"
return datetime.fromisoformat(value).timestamp()
```

#### 10.5 Backward compatibility strategy

**Transition period:** All file loaders must accept BOTH old ISO strings and new floats. Writers emit only floats.

```python
def _parse_timestamp(value: str | float | int | None) -> float:
    """Parse timestamp from legacy or new format, returning Unix timestamp (UTC)."""
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    # ISO string (legacy)
    try:
        s = value.strip()
        # Naive ISO strings → assume UTC
        if not s.endswith("Z") and "+" not in s[-6:] and "-" not in s[-6:]:
            s = s + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    # Fallback
    return float(value)
```

**Deprecation timeline:**
- Phase 10 release: Loaders accept both formats, writers emit floats
- Phase 11 release: Keep backward compat in loaders
- Phase 12+: Remove ISO string parsing from loaders (major version bump)

**Files needing backward-compat loaders:**
- `think/storage.py` — `load_session()`, `load_checkpoint()`
- `do/journal.py` — `ChangeJournal.load()`
- `token_tracker.py` — `TokenTracker._load_file()`
- `think/push.py` — `load_outbox()` (if still used)

### Implementation

#### 10.1 Update `think/models.py`

```python
import time

@dataclass
class ThinkMessage:
    id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:8]}")
    role: Literal["system", "user", "assistant"] = "user"
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    tokens_in: int | None = None
    tokens_out: int | None = None
    deleted: bool = False
    edited_at: float | None = None
    compacted_into: str | None = None

@dataclass
class ThinkSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: float = field(default_factory=time.time)
    messages: list[ThinkMessage] = field(default_factory=list[ThinkMessage])
```

#### 10.2 Update `plan/models.py`

```python
class PlanMetadata(BaseModel):
    plan_id: str = ""
    created: float | None = None      # Unix timestamp
    last_updated: float | None = None

class AuditReport(BaseModel):
    phase_id: str
    timestamp: float = Field(default_factory=time.time)
    # ...

class Dispatch(BaseModel):
    dispatch_id: str
    # ...
    dispatched_at: float = Field(default_factory=time.time)

class Handover(BaseModel):
    # ...
    created_at: float = Field(default_factory=time.time)
```

#### 10.3 Update `do/journal.py`

```python
@dataclass(slots=True)
class JournalEntry:
    id: str = field(default_factory=lambda: f"je_{uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    type: str = "unknown"
```

#### 10.4 Update `token_tracker.py`

```python
# LogEntry.timestamp becomes float
@dataclass
class LogEntry:
    timestamp: float  # Unix timestamp
    session_id: str
    # ...

# CSV format: timestamp as float (not ISO string)
CSV_HEADER = "timestamp,session_id,turn_id,model,tokens_in,tokens_out,active_context\n"
```

#### 10.5 Backward compatibility

All loaders must accept both formats during a transition period:

```python
def _parse_timestamp(value: str | float | None) -> float:
    """Parse timestamp from string or float, returning Unix timestamp."""
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    # Try ISO format first
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        pass
    # Try other formats as needed
    return float(value)
```

### Testing Requirements

| Test | Description |
|------|-------------|
| `test_journal_entry_timestamp_is_float` | Journal entries store Unix float |
| `test_think_message_timestamp_is_float` | ThinkMessage stores Unix float |
| `test_plan_metadata_created_is_float` | PlanMetadata stores Unix float |
| `test_backward_compat_iso_string` | Loader accepts old ISO string format |
| `test_audit_report_renders_iso` | Audit report output contains ISO date |
| `test_handover_renders_iso` | Handover output contains ISO date |
| `test_token_tracker_csv_float` | CSV contains float timestamps |
| `test_timezone_utc_from_float` | Display formatting uses UTC |

**Estimated effort:** 1–2 days (actual: 1 day).

---
