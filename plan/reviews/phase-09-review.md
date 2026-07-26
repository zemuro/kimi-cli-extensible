---
document_type: review
phase: 09
title: Pre-Implementation Review — Move Session Archive to Workspace-Specific Directory
created: 2026-07-26
author: Consilium
verdict: 🟡 Feasible with Corrections
---

# Pre-Implementation Review — Phase 09

## Verdict: 🟡 Feasible with Corrections

The plan is well-structured and thorough. Two major corrections and one addition are required before implementation:

---

## Correction 1: Remove Migration Entirely (Spec §2.3, Task 6)

**User directive:** "We will not copy the existing global history anywhere, that's insane."

The plan currently includes a one-time migration function (`migrate_global_sessions()`) that copies all existing global Think/Do/regular sessions from `~/.consilium/` into the workspace-local `.consilium/sessions/` directory.

**Action:** Delete Task 6 entirely. Do not create `migration.py`. Do not call any migration during workspace init. This eliminates:
- The `migrate_global_sessions()` function
- The `shutil.copy2()` logic
- The sentinel file (`{workDir}/.consilium/.workspace-initialized`)
- All associated migration tests (Tasks 9-10 adjust accordingly)

**Impact on spec:**
- §1.2 Goal: Remove "Existing global sessions are migrated with no data loss"
- §2.3: Delete entirely
- Task 6: Delete
- Task 7: Remove "Runs the migration" bullet
- Acceptance Criteria: Remove "Migration function copies..." and "Migration is called..."
- §5.3, §5.4, §5.5: Delete migration-specific test sections
- Risks table: Remove data-loss and backward-compat-shim rows

**Backward-compat shim:** The old global path constants (`THINK_DIR`, `JOURNAL_DIR`) will be retained as **read-only fallbacks** with a deprecation warning. This allows reading pre-existing sessions without migrating them. New sessions always write to workspace-local paths.

---

## Correction 2: Remove Old Constants Cleanly (Spec Task 8)

The plan says "Keep the old constants with a deprecation comment for backward compatibility." Per the user's directive, we will NOT keep the old constants as writable targets. Instead:

- Old constants remain as module-level `Path` objects but are **no longer used internally** by any function
- A `__getattr__` deprecation warning fires on access (or a comment marking them as deprecated)
- All internal functions use the new `_think_dir(work_dir)` / `_journal_dir(work_dir, session_id)` builders
- After one release cycle, the old constants can be removed entirely

---

## Addition: MAX_PATH Mitigation on Windows (Spec §6)

**User directive:** "MAX_PATH mitigated."

The spec's risk table mentions the Windows 260-character path limit but does not include it in any task. Add:

**New Task 6b (was Task 8):** Add `_win_safe_path()` helper that prepends `\\?\` for absolute paths on Windows when path length exceeds 200 characters. Use this helper in:
- `_think_dir()` mkdir calls
- `_journal_dir()` mkdir calls
- `WorkDirMeta.sessions_dir` mkdir calls

---

## Correction 3: Expand File Scope

The spec lists `session.py` in Task 0's file list but does not include it in any refactoring task. It must be refactored:

**`src/consilium/session.py`:**
- Line 70: `think_path(self.id).exists()` — must pass `work_dir` from `self.work_dir_meta.path`
- Line 119: `Path.home() / ".consilium" / "think_sessions" / ...` — **hardcoded duplicate**, replace with `think_path(self.id, work_dir)`
- Line 339: `think_path(session_id)` — must pass `work_dir`

**`src/consilium/cli/__init__.py`:**
- Lines 1166, 1174: `think_path(session.id).exists()` — must pass `work_dir`

**`src/consilium/do/session.py`:**
- Line 128: `ChangeJournal(session_id)` — must pass `work_dir`
- Line 144: `archive_old_journals(retention_days)` — must pass `work_dir`

**`src/consilium/vis/api/sessions.py`**, **`src/consilium/vis/api/statistics.py`**, **`src/consilium/cli/export.py`:**
- References to `get_share_dir() / "sessions"` for listing — must be updated to use workspace-local paths or removed

---

## Revised Task List

| # | Task | Est. | Files |
|---|------|------|-------|
| 0 | Map all current session storage paths | ✅ Done by audit | (all listed files) |
| 1 | Design final directory structure | 0.5h | `plan/phase-09.md` |
| 2 | Refactor Think storage paths | 2h | `think/storage.py` |
| 3 | Refactor Do/ChangeJournal paths | 2h | `do/journal.py` |
| 4 | Update WorkDirMeta.sessions_dir | 1h | `metadata.py` |
| 5 | Refactor session.py (remove hardcoded paths) | 1h | `session.py` |
| 6 | Update DoSession + callers | 1h | `do/session.py`, `cli/__init__.py`, `app.py` |
| 7 | Update web store + vis + export paths | 1.5h | `web/store/sessions.py`, `vis/api/sessions.py`, `vis/api/statistics.py`, `cli/export.py` |
| 8 | Add MAX_PATH mitigation | 0.5h | `share.py` or path utility |
| 9 | Update test monkeypatches | 2h | `tests/test_think.py`, `tests/core/test_timestamp_unification.py`, `tests/core/test_do_session.py`, `tests/core/test_journal.py`, `tests/core/test_journal_and_binary.py`, `tests/core/test_wire_events.py` |
| 10 | Test session isolation + regression | 1.5h | New test file |
| | **Total** | **13h** | |

---

## Summary of Changes to Spec

| Spec Section | Action |
|---|---|
| §1.2 Goal — migration sentence | Delete |
| §2.3 Migration approach | Delete entire section |
| Task 6 (migration logic) | Delete |
| Task 6b (MAX_PATH) | **Add** |
| Task 5 (session.py) | **Add to scope** |
| Task 7 (workspace init) | Remove "Runs the migration" |
| Acceptance Criteria — migration items | Delete |
| §5.3, §5.4, §5.5 | Delete or replace |
| §6 Risks — data loss, compat shim | Delete or update |
| §8 Deferred Items — migration UI | Delete |

---

## Implementation Strategy

1. **Bottom-up**: Start with `think/storage.py` and `do/journal.py` (the foundations), then update callers.
2. **No migration**: New sessions go to `{workDir}/.consilium/sessions/{type}/`. Old global sessions are left in place.
3. **Old constants as read-only fallback**: `think_path()` and `list_sessions()` without a `work_dir` still scan the global `~/.consilium/think_sessions/` for backward compat.
4. **Test monkeypatches**: Replace `monkeypatch.setattr(mod, "THINK_DIR", tmp_path)` with `monkeypatch.setattr(mod, "think_path", lambda sid, work_dir=None: tmp_path / f"{sid}.jsonl")` or similar.
