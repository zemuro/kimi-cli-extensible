---
document_type: phase_spec
phase: 09
id: 09
title: Move Session Archive to Workspace-Specific Directory
description: >-
  Currently, all sessions (Think, Do, regular) are stored globally under
  `~/.consilium/think_sessions/`, `~/.consilium/do_sessions/`, and
  `~/.consilium/sessions/{md5(workDir)}/`. This phase relocates session
  storage to be per-workspace under `{workDir}/.consilium/sessions/` so
  that each workspace has its own isolated session archive.
status: planning
priority: medium
created: 2026-07-26
author: Consilium
dependencies:
  - Phase 07
acceptance_criteria_summary:
  - Sessions stored under `{workDir}/.consilium/sessions/` with subdirectories per type
  - New workspaces get their session directory auto-created on init
  - Session history only shows sessions from the current workspace
  - Existing global sessions are migrated or accessible via a shim
  - No data loss during migration
---

# Phase 09: Move Session Archive to Workspace-Specific Directory

## Summary

Relocate all session storage (Think, Do, and regular CLI sessions) from the global `~/.consilium/` directory to a per-workspace location under `{workDir}/.consilium/sessions/`. This ensures session isolation between different workspaces: sessions from workspace A never appear in workspace B's history, and each workspace maintains its own independent session archive. Existing global sessions must be migrated or exposed through a backward-compatibility shim to prevent data loss.

## 1. Overview

### 1.1 Problem Statement

All three session types currently write to global directories under `~/.consilium/`:

| Session type | Current path | Controlled by |
|---|---|---|
| Regular (wire) | `~/.consilium/sessions/{md5(workDir)}/{sessionId}/` | `WorkDirMeta.sessions_dir` in `src/consilium/metadata.py` |
| Think | `~/.consilium/think_sessions/{sessionId}.jsonl` | `THINK_DIR` constant in `src/consilium/think/storage.py` |
| Do | `~/.consilium/do_sessions/{sessionId}/journal.jsonl` | `JOURNAL_DIR` constant in `src/consilium/do/journal.py` |
| Think logs | `~/.consilium/think_logs/{sessionId}.jsonl` | `THINK_LOGS_DIR` in `src/consilium/think/storage.py` |
| Do logs | `~/.consilium/do_logs/{sessionId}.jsonl` | `DO_LOGS_DIR` in `src/consilium/do/journal.py` |

This global layout has two problems:

1. **Cross-workspace leaking**: Regular sessions are already weakly scoped by an MD5 hash of the workdir path, but Think and Do sessions are entirely global. Switching workspaces surfaces all Think/Do sessions regardless of which workspace they were created in.
2. **No easy cleanup**: Removing a workspace's sessions requires manual browsing of three separate directories under `~/.consilium/`.

### 1.2 Goal

Move all session storage into `{workDir}/.consilium/sessions/{type}/{sessionId}/` so that:
- Each workspace has its own fully isolated session directory.
- There is a single, predictable location for all sessions belonging to a workspace.
- Workspace cleanup can be done by removing the `.consilium/sessions/` directory.
- Existing global sessions are migrated with no data loss.

### 1.3 Scope Boundaries

**In scope:**
- `src/consilium/think/storage.py` — `THINK_DIR`, `THINK_LOGS_DIR` constant refactoring
- `src/consilium/do/journal.py` — `JOURNAL_DIR`, `DO_LOGS_DIR` constant refactoring
- `src/consilium/metadata.py` — `WorkDirMeta.sessions_dir` path change to point to workspace-local directory
- `src/consilium/think/` — session read paths in `load_session()`, `list_sessions()`, checkpoint functions
- `src/consilium/do/` — `ChangeJournal` constructor, session directory initialization
- `src/consilium/web/store/sessions.py` — `_iter_session_dirs()` and session index building
- `src/consilium/web/api/sessions.py` — any direct path references
- `src/consilium/app.py` — workspace initialization flow (auto-create `.consilium/sessions/` directories)
- Workspace init in the extension's session handler — ensure new directories are created
- Migration script or shim for existing global sessions
- Tests: session isolation between workspaces, backward compatibility

**Out of scope:**
- Changes to the wire protocol or session data formats
- Frontend UI changes beyond session listing fixes
- Performance optimization of session listing
- Encryption or access control for session files
- Non-session `.consilium/` contents (config, logs, MCP configs)

## 2. Architecture

### 2.1 Target directory structure

```
{workDir}/.consilium/
└── sessions/
    ├── regular/                  ← formerly ~/.consilium/sessions/{md5}/
    │   └── {sessionId}/
    │       ├── wire.jsonl
    │       ├── context.jsonl
    │       ├── state.jsonl
    │       └── subagents/
    │           └── ...
    ├── think/                    ← formerly ~/.consilium/think_sessions/
    │   ├── {sessionId}.jsonl
    │   ├── {sessionId}/checkpoints/*.json
    │   └── logs/{sessionId}.jsonl
    └── do/                       ← formerly ~/.consilium/do_sessions/
        ├── {sessionId}/
        │   ├── journal.jsonl
        │   └── diffs/*.patch
        └── logs/{sessionId}.jsonl
```

### 2.2 Path resolution flow

Each session type needs to know the workdir to construct its target path. The approach:

1. **Regular sessions**: Already receive `work_dir_meta` via the `Session` dataclass. `WorkDirMeta.sessions_dir` property changes from `get_share_dir() / "sessions" / {md5}` to `Path(work_dir) / ".consilium" / "sessions" / "regular"`.
2. **Think sessions**: `THINK_DIR` and `THINK_LOGS_DIR` cease to be module-level constants. Instead, functions like `think_path()` and `_think_log_path()` accept an optional `work_dir` parameter, defaulting to a global fallback (for backward compat).
3. **Do sessions**: `ChangeJournal.__init__()` receives a `work_dir` parameter. `JOURNAL_DIR` and `DO_LOGS_DIR` cease to be module-level constants. The journal directory is derived from the workdir.

### 2.3 Migration approach

A one-time migration function reads existing global session directories and copies (or symlinks) them into the new per-workspace location. The migration is idempotent: it skips sessions that already exist in the target.

```python
def migrate_global_sessions(work_dir: Path) -> None:
    """Copy existing global sessions under work_dir/.consilium/sessions/."""
    # 1. Regular: ~/.consilium/sessions/{md5(workDir)}/* → {workDir}/.consilium/sessions/regular/
    # 2. Think:   ~/.consilium/think_sessions/*          → {workDir}/.consilium/sessions/think/
    # 3. Do:      ~/.consilium/do_sessions/*              → {workDir}/.consilium/sessions/do/
```

Because Think and Do session files do not currently embed a workdir reference, the migration copies all global Think/Do sessions. A future phase could add workdir tracking to the session metadata.

## 3. Detailed Design

### Task 0: Map out all current session storage paths and their corresponding handler code

**Effort:** 1 hour

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\think\storage.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\do\journal.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\do\blob_store.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\session.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\metadata.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\web\store\sessions.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\web\api\sessions.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py`

**Description:**
Read the files listed above to produce a complete inventory of every path constant, directory creation call, path resolution function, and listing function related to session storage. Document the full call graph so no path is missed during refactoring.

### Task 1: Design the new directory structure under `{workDir}/.consilium/sessions/`

**Effort:** 0.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\phase-09.md` (this document — update Section 2.1)

**Description:**
Finalize the target layout (Section 2.1) and decide naming conventions:
- Should regular sessions go under `regular/` or remain at the top of `sessions/`?
- Should think log files go under `think/logs/` or `think_logs/`?
- Should the directory creation be eager (on import) or lazy (on first write)?

Document the final decisions in this spec.

### Task 2: Refactor `ThinkSession` storage paths

**Effort:** 2 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\think\storage.py`

**Description:**
Replace the module-level constants `THINK_DIR` and `THINK_LOGS_DIR` with path builders that accept an optional `work_dir` parameter:

```python
def _think_dir(work_dir: Path | None = None) -> Path:
    base = work_dir / ".consilium" / "sessions" / "think" if work_dir else Path.home() / ".consilium" / "think_sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _think_logs_dir(work_dir: Path | None = None) -> Path:
    base = work_dir / ".consilium" / "sessions" / "think" / "logs" if work_dir else Path.home() / ".consilium" / "think_logs"
    base.mkdir(parents=True, exist_ok=True)
    return base
```

Update:
- `think_path(session_id)` → accept optional `work_dir`, delegate to `_think_dir()`
- `_checkpoint_dir(session_id)` → derive from `_think_dir()`
- `_think_log_path(session_id)` → derive from `_think_logs_dir()`
- `list_sessions()` → accept optional `work_dir`, scan `_think_dir()` for `*.jsonl` files
- All callers that currently rely on the global constants need updating

Keep the old constants with a deprecation comment for backward compatibility during the migration window.

### Task 3: Refactor `DoSession` (ChangeJournal) storage paths

**Effort:** 2 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\do\journal.py`

**Description:**
Replace the module-level constants `JOURNAL_DIR` and `DO_LOGS_DIR` with path builders that accept a `work_dir` parameter:

```python
def _journal_dir(work_dir: Path, session_id: str) -> Path:
    return work_dir / ".consilium" / "sessions" / "do" / session_id

def _do_logs_dir(work_dir: Path) -> Path:
    return work_dir / ".consilium" / "sessions" / "do" / "logs"
```

Update `ChangeJournal.__init__()` to accept a `work_dir: Path` parameter and use it to compute `_journal_dir` and `_journal_file`:

```python
def __init__(self, session_id: str, work_dir: Path) -> None:
    self.session_id = session_id
    self._journal_dir = work_dir / ".consilium" / "sessions" / "do" / session_id
    self._journal_file = self._journal_dir / "journal.jsonl"
    self._diffs_dir = self._journal_dir / "diffs"
    self._journal_dir.mkdir(parents=True, exist_ok=True)
    self._diffs_dir.mkdir(parents=True, exist_ok=True)
```

Find and update all callers of `ChangeJournal(session_id)` to pass `work_dir`.

### Task 4: Update regular (wire) session paths in `WorkDirMeta`

**Effort:** 1 hour

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\metadata.py`

**Description:**
Change `WorkDirMeta.sessions_dir` property to point to the workspace-local path:

```python
@property
def sessions_dir(self) -> Path:
    path = Path(self.path) / ".consilium" / "sessions" / "regular"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

This removes the MD5-hash-based directory naming and the global `get_share_dir()` dependency. Existing sessions under `~/.consilium/sessions/{md5}/` will need migration (Task 6).

### Task 5: Update session read/listing paths

**Effort:** 1.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\web\store\sessions.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\web\api\sessions.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\think\storage.py` (already covered in Task 2)

**Description:**
Update `_iter_session_dirs()` in `web/store/sessions.py` to scan the new `regular/` subdirectory:

```python
def _iter_session_dirs(wd: WorkDirMeta) -> list[tuple[Path, Path]]:
    session_dirs: list[tuple[Path, Path]] = []
    regular_dir = wd.sessions_dir  # now points to {workDir}/.consilium/sessions/regular/
    for context_file in regular_dir.glob("*/context.jsonl"):
        session_dir = context_file.parent
        session_dirs.append((session_dir, context_file))
    return session_dirs
```

Also update any listing functions in the web API that currently scan `~/.consilium/think_sessions/` or `~/.consilium/do_sessions/` to instead scan the workspace-local `think/` and `do/` subdirectories.

### Task 6: Add migration logic for existing global sessions

**Effort:** 2 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\migration.py` (new file)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py` (call migration on workspace init)

**Description:**
Create a `migrate_global_sessions(work_dir: Path)` function:

```python
def migrate_global_sessions(work_dir: Path) -> None:
    """Copy existing global sessions into the workspace-local structure."""
    target = work_dir / ".consilium" / "sessions"

    # 1. Migrate regular sessions
    from consilium.share import get_share_dir
    from hashlib import md5
    md5_hash = md5(str(work_dir).encode()).hexdigest()
    global_regular = get_share_dir() / "sessions" / md5_hash
    if global_regular.exists():
        _copy_tree(global_regular, target / "regular")

    # 2. Migrate Think sessions
    global_think = Path.home() / ".consilium" / "think_sessions"
    for f in global_think.glob("*.jsonl"):
        # Copy the session JSONL file
        shutil.copy2(f, target / "think" / f.name)
    # Copy checkpoints
    for d in global_think.iterdir():
        if d.is_dir() and (d / "checkpoints").exists():
            _copy_tree(d / "checkpoints", target / "think" / d.name / "checkpoints")
    # Copy think logs
    global_think_logs = Path.home() / ".consilium" / "think_logs"
    for f in global_think_logs.glob("*.jsonl"):
        shutil.copy2(f, target / "think" / "logs" / f.name)

    # 3. Migrate Do sessions
    global_do = Path.home() / ".consilium" / "do_sessions"
    for d in global_do.iterdir():
        if d.is_dir():
            _copy_tree(d, target / "do" / d.name)
    global_do_logs = Path.home() / ".consilium" / "do_logs"
    for f in global_do_logs.glob("*.jsonl"):
        shutil.copy2(f, target / "do" / "logs" / f.name)
```

Call this function during workspace initialization in `app.py` (within `KimiCLI.create()` or a new `init_workspace()` helper).

### Task 7: Add workspace initialization to create `.consilium/sessions/` directory structure

**Effort:** 0.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py`
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\workspace.py` (new file, optional)

**Description:**
Add a workspace initialization step that:
1. Creates `{workDir}/.consilium/sessions/regular/`
2. Creates `{workDir}/.consilium/sessions/think/`
3. Creates `{workDir}/.consilium/sessions/think/logs/`
4. Creates `{workDir}/.consilium/sessions/do/`
5. Creates `{workDir}/.consilium/sessions/do/logs/`
6. Runs the migration (Task 6)

This should be triggered once per workspace, idempotently (e.g., by checking for a sentinel file like `{workDir}/.consilium/.workspace-initialized`).

### Task 8: Update all relevant config constants

**Effort:** 0.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\share.py` (if needed)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\config.py` (if any session path configs exist)

**Description:**
Audit all config and share-directory constants for references to the old session paths. Remove or deprecate any that are no longer needed. Ensure `get_share_dir()` is no longer referenced by any session path code (it remains valid for config, MCP configs, etc.).

### Task 9: Test that sessions from workspace A don't appear in workspace B

**Effort:** 1.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\` (new test file or additions to existing test files)

**Description:**
Write integration tests that:
1. Create two temporary workspaces A and B.
2. Create a regular session, a Think session, and a Do session in workspace A.
3. Verify that workspace B's session listing shows zero sessions.
4. Verify that workspace A's session listing shows all three sessions.
5. Switch back and forth to confirm isolation is maintained.

### Task 10: Test backward compatibility with existing sessions

**Effort:** 1 hour

**Description:**
1. Set up global session directories (`~/.consilium/think_sessions/`, `~/.consilium/do_sessions/`, `~/.consilium/sessions/{md5}/`) with test data.
2. Run the migration function.
3. Verify all files exist in the new location.
4. Verify the session listing in the web API returns the migrated sessions.
5. Verify the session listing still works with the old global fallback path (if a shim is kept).

## 4. Acceptance Criteria

- [ ] Sessions are stored under `{workDir}/.consilium/sessions/` with subdirectories `regular/`, `think/`, and `do/`
- [ ] New workspaces get the full session directory tree auto-created on init
- [ ] Session listing (`getAllConsiliumSessions` / `_build_sessions_index`) only shows sessions from the current workspace
- [ ] Think session paths no longer use the global `~/.consilium/think_sessions/` — the new path is `{workDir}/.consilium/sessions/think/`
- [ ] Do session paths no longer use the global `~/.consilium/do_sessions/` — the new path is `{workDir}/.consilium/sessions/do/`
- [ ] `WorkDirMeta.sessions_dir` points to `{workDir}/.consilium/sessions/regular/` instead of `~/.consilium/sessions/{md5}/`
- [ ] Migration function copies all existing global sessions to the new locations with no data loss
- [ ] Migration is called automatically on first workspace initialization in an existing workspace
- [ ] Sessions from workspace A do not appear in workspace B's session history
- [ ] All existing tests pass (no regressions from path changes)
- [ ] `ChangeJournal` accepts a `work_dir` parameter and computes paths from it
- [ ] Think `list_sessions()` is scoped to a workspace when `work_dir` is provided

## 5. Test Plan

### 5.1 Path refactoring verification

1. Create a temporary workspace `A` and initialize it.
2. Start a regular CLI session — verify `wire.jsonl` appears at `{A}/.consilium/sessions/regular/{id}/wire.jsonl`.
3. Start a Think session — verify `{sessionId}.jsonl` appears at `{A}/.consilium/sessions/think/{sessionId}.jsonl`.
4. Start a Do session — verify `journal.jsonl` appears at `{A}/.consilium/sessions/do/{sessionId}/journal.jsonl`.
5. Confirm no files were written to `~/.consilium/think_sessions/`, `~/.consilium/do_sessions/`, or `~/.consilium/sessions/{md5}/`.

### 5.2 Session isolation verification

1. Create workspace `A` and workspace `B`.
2. Create one session of each type in workspace `A`.
3. Query the session listing for workspace `A` — expect 3 sessions.
4. Query the session listing for workspace `B` — expect 0 sessions.
5. Create one session of each type in workspace `B`.
6. Query the session listing for workspace `B` — expect 3 sessions.
7. Query the session listing for workspace `A` — expect still exactly 3 sessions.

### 5.3 Migration verification

1. Pre-populate `~/.consilium/think_sessions/test-session.jsonl` and `~/.consilium/think_sessions/test-session/checkpoints/ckpt.json`.
2. Pre-populate `~/.consilium/do_sessions/test-do-session/journal.jsonl` and `~/.consilium/do_sessions/test-do-session/diffs/`.
3. Pre-populate `~/.consilium/sessions/{md5}/` with a regular session.
4. Initialize workspace `A` pointing to the same path.
5. Verify all files are copied to `{A}/.consilium/sessions/think/`, `{A}/.consilium/sessions/do/`, and `{A}/.consilium/sessions/regular/`.
6. Verify the session listing includes all migrated sessions.

### 5.4 Idempotency verification

1. Run the migration function twice.
2. Verify no duplicate files, no overwrite errors, and the session listing is identical between runs.

### 5.5 Regression: global fallback path

1. If a backward-compatibility shim is kept (optional), verify that `list_sessions()` called without a `work_dir` still works against the old global `~/.consilium/think_sessions/`.
2. If the shim is not kept, verify that calling old global path functions raises a clear deprecation error.

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss during migration if a copy fails mid-way | L | H | Use `shutil.copy2` with try/except; verify checksums after each copy; implement atomic rename for the final step |
| Think/Do session files do not embed workdir info, making per-workspace migration of individual sessions impossible | H | M | Copy all global Think/Do sessions to each workspace during migration; add workdir tracking to session metadata in a follow-up phase |
| Callers of `ChangeJournal` and `think_path` that are hard to find (dynamic imports, test fixtures) | M | M | Use the audit from Task 0 to build a complete caller list; add a `__init_subclass__` or deprecation warning to catch any missed callers at runtime |
| Backward-compatibility shim causes confusion about source-of-truth paths | M | L | Remove the shim after one release cycle; document the migration path clearly in CHANGELOG |
| The `.consilium/sessions/` directory structure is created but not cleaned up when a workspace is deleted | L | L | Document as a manual cleanup step; a follow-up phase could add a `consilium workspace clean` command |
| Long paths on Windows exceed MAX_PATH (260 characters) | M | M | Use `\\?\` prefix for paths over 200 characters; ensure all path operations use `pathlib` which handles this on recent Python versions |
| Race condition if two consilium instances initialize the same workspace simultaneously | L | M | Use a file lock (`portalocker` or similar) during workspace initialization and migration |

## 7. Effort Estimate

| Sub-task | Hours | Notes |
|----------|-------|-------|
| Map out all current session storage paths and handler code | 1 | Code audit — read all relevant files and document the call graph |
| Design the new directory structure under `{workDir}/.consilium/sessions/` | 0.5 | Finalize naming conventions and path resolution strategy |
| Refactor Think session storage paths | 2 | Module-level constants → workdir-aware path builders |
| Refactor Do session (ChangeJournal) storage paths | 2 | `__init__` accepts `work_dir`; path constants become functions |
| Update regular (wire) session paths in `WorkDirMeta` | 1 | Change `sessions_dir` property to local path |
| Update session read/listing paths (web API, store) | 1.5 | `_iter_session_dirs()`, listing endpoints |
| Add migration logic for existing global sessions | 2 | New `migration.py` module; copy all three session types |
| Add workspace initialization to create directory structure | 0.5 | Create subdirectories; trigger migration once |
| Update relevant config constants | 0.5 | Audit and clean up old path references |
| Test session isolation (workspace A ≠ workspace B) | 1.5 | Integration tests with multiple temp workspaces |
| Test backward compatibility with existing sessions | 1 | Pre-populate global directories; run migration; verify |
| **Total** | **13.5** | |

## 8. Deferred Items

| Item | Reason |
|------|--------|
| Adding workdir metadata to Think/Do session files for selective migration | Over-engineering for initial migration; all global sessions are copied to each workspace; can be refined in a follow-up |
| `consilium workspace clean` command to remove `.consilium/sessions/` | Out of scope — this phase focuses on moving + migrating, not workspace management |
| Encryption or access control for session files | Not required; sessions are local files on the user's machine |
| Refactoring Think/Do storage into a unified `SessionStorage` abstraction | Separate concern; each session type has different storage semantics (JSONL vs journal) — premature unification adds risk |
| Removing the `THINK_DIR` / `JOURNAL_DIR` old constants entirely | Keep for one release cycle with deprecation warnings; remove in a follow-up phase |
| Migration UI progress bar for large session archives | The migration is fast (file copy), and progress reporting adds UI complexity not warranted for initial release |
| Portable mode (USB drive with sessions relative to consilium binary) | Distinct use case; out of scope for workspace-specific session isolation |