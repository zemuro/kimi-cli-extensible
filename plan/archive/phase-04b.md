---
phase_id: phase-04b
title: 4b: CLI Polish & Integration
status: implemented
dependencies:
  - phase-04a
files_involved:
  - src/consilium/do/session.py
  - src/consilium/think/push.py
---

**Status: PLANNED — implement after Phase 4a report.**

Phase 4a delivered all core backend features. Phase 4b is a hardening pass: integration tests, edge-case handling, and documentation before switching to extension-side work.

### 4b.1 End-to-End Integration Test

**File:** `tests/core/test_e2e_think_do_flow.py` — new module

A single test that exercises the full Think → Push → Do pipeline:

```python
async def test_think_push_do_flow():
    # 1. Start Think session, send a message
    think = ThinkSoul(...)
    await think.run(Message(role="user", content="Plan a todo app"))

    # 2. Export Think history via /push-to-do
    await slash_push_to_do(think, "")

    # 3. Start Do session with --seed-from-think
    do = DoSession(..., seed_from_think=True)

    # 4. Verify seed loaded into Do context
    assert len(do.soul._context.history) > 1

    # 5. Trigger a tool call that modifies a file
    await do.soul.run(Message(role="user", content="Create src/main.py"))

    # 6. Verify journal recorded the change
    journal = do.journal_store.load()
    assert any(e.tool_name == "Bash" for e in journal.entries)

    # 7. Verify ToolFileModifiedEvent was emitted
    # (requires a mock wire hub or event capture)
```

**Value:** Catches regressions in the bridge, seeding, and journal pipeline that unit tests miss.

---

### 4b.2 Journal Retention Policy

**File:** `src/consilium/do/journal.py` — modifications to `JournalStore`

Old journals accumulate indefinitely in `~/.consilium/do_sessions/`. Add auto-archive:

```python
class JournalStore:
    def archive_old_journals(self, max_age_days: int = 30) -> list[Path]:
        """Move journals older than max_age_days to ~/.consilium/do_sessions/.archive/"""
        ...
```

**Config:**
```toml
[do]
journal_retention_days = 30  # 0 = disable archiving
```

**Behavior:**
- On `DoSession` startup, check and archive old journals (non-blocking, fire-and-forget)
- Archive is a move, not delete — user can recover from `~/.consilium/do_sessions/.archive/`
- Compact archived journals to a single `.tar.gz` per month if space is a concern

---

### 4b.3 Binary File Handling in Diffs

**File:** `src/consilium/do/diff.py` — modifications to `DiffComputer`

The diff system currently assumes text. Binary files (images, `.pyc`, `.so`, `.dll`) should be tracked in the journal but without unified diff text.

```python
class DiffComputer:
    def compute(self, baseline: str | bytes, post: str | bytes, path: Path) -> DiffResult:
        if _is_binary(path):
            return DiffResult(
                is_binary=True,
                unified_diff="",  # no diff text for binaries
                lines_added=0,
                lines_removed=0,
            )
        # existing text diff logic
```

**Detection:** Check for null bytes in first 8KB, or use `file` command if available.

**Journal entry for binary files:**
```json
{"is_binary": true, "size_before": 1234, "size_after": 5678}
```

---

### 4b.4 Windows Sandbox for Python Tool

**File:** `src/consilium/think/python_tool.py` — additions to `SandboxedExecutor`

The `sandboxed` restriction level currently falls back to `restricted` on non-macOS. Add Windows-specific sandboxing via Windows Job Objects:

```python
import ctypes
from ctypes import wintypes

def _create_job_object() -> wintypes.HANDLE:
    """Create a Windows Job Object with resource limits."""
    job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
    # Configure job limits: kill on close, memory cap, no child processes
    ...
    return job
```

**Limits enforced:**
- Kill subprocess tree when parent exits (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)
- Memory cap (`JOB_OBJECT_LIMIT_JOB_MEMORY`)
- No network access (firewall rule or loopback-only — research needed)

**Fallback:** If Job Object creation fails, fall back to `restricted` level.

**Scope:** Only affects `run_python` with `restriction_level = "sandboxed"` on Windows. macOS `sandbox-exec` path unchanged.

---

### 4b.5 Web API (Optional — When `kimi web` Running)

**Status: Optional. Extension reads journal directly, so this is low priority.**

If implemented, these endpoints are useful when `kimi web` is explicitly running:

```python
# src/consilium/web/routes.py
@router.get("/{session_id}/changes")
async def get_changes(session_id: str, since: int | None = None):
    ...

@router.get("/{session_id}/baselines/{content_hash}")
async def get_baseline(content_hash: str):
    ...

@router.get("/{session_id}/turns/{turn_index}/summary")
async def get_turn_summary(session_id: str, turn_index: int):
    ...
```

**Decision point:** Skip unless a concrete use case emerges (e.g., third-party dashboard).

---

### 4b.6 AGENTS.md Update

**File:** `AGENTS.md` — update with final architecture

Document for future agents:
- Think/Do relationship diagram (disjoint processes, unidirectional push)
- File inventory (which files belong to Think vs Do vs shared)
- Hook mechanism (`pre_tool` / `post_tool`)
- Storage layout (`~/.consilium/think_sessions/` vs `~/.consilium/do_sessions/`)
- Fork-specific features (`force_abort`, `ToolFileModifiedEvent`)
- Testing strategy (`tests/core/` structure)

---

### 4b.7 Testing Requirements

| Test | File | Description |
|------|------|-------------|
| `test_think_push_do_flow` | `tests/core/test_e2e_think_do_flow.py` | Full pipeline integration |
| `test_journal_archive_old` | `tests/core/test_journal.py` | Archives journals >30 days |
| `test_journal_archive_disabled` | `tests/core/test_journal.py` | Retention=0 skips archive |
| `test_diff_binary_file` | `tests/core/test_diff.py` | Binary file detected, no diff text |
| `test_python_sandbox_windows` | `tests/core/test_python_tool.py` | Job Object creation + memory limit |

---
