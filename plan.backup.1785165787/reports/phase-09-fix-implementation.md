---
document_type: implementation_report
phase: 09-fix
title: Implementation Report — Fix Phase 09 Session Storage Bugs
author: Consilium
completion_date: 2026-07-27
---

# Implementation Report — Phase 09 Fix: Session Storage Bug Corrections

## Executive Summary

Two post-implementation bugs in Phase 09 (workspace-local session storage) were identified and fixed. Bug 1: `load_think_session()` in `app.py` was called without `work_dir`, causing it to read from the legacy global path while Think session saves correctly wrote to workspace-local paths. Bug 2: The extension's Do session listing scanned both legacy global and workspace-local paths (correct), but an over-aggressive fix removed the legacy scan, breaking backward compatibility. Additional fixes corrected Think session loading priority, Think metadata path resolution, and bridge handler `workDir` passing. The extension was packaged successfully with no build errors.

## Files Changed

### CLI-Side Changes (kimi_cli_mod)

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py` | Added `work_dir` extraction from `session.work_dir` and passed it to `load_think_session(session.id, work_dir=work_dir)` at line 190 |

### Extension-Side Changes (kimi_extension_mod)

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\session.handler.ts` | **Think session loading:** Reversed priority — workspace-local path checked first, legacy global as fallback. **Do session listing:** Kept both legacy global and workspace-local scans (the `seen` set deduplicates by UUID). Removed `getDoSessionsDir()` and restored it. |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\lib\session-storage.ts` | `readThinkSessionTitle()` and `writeThinkSessionTitle()` now accept optional `workDir` parameter. Write operations use workspace-local paths. Read operations use workspace-local path first, with legacy global fallback. |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\bridge-handler.ts` | `setSessionMetadata()` and `getSessionMetadata()` now pass `workDir` to Think session title functions |

### SDK Changes (agent_sdk — part of kimi_extension_mod)

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\paths.ts` | `ConsiliumPaths.sessionsDir()`, `sessionDir()`, `baselineDir()` now return workspace-local paths under `{workDir}/.consilium/sessions/regular/` instead of the old hashed path under `~/.consilium/sessions/{md5hash}/`. Removed `hashPath()` dependency. |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\tests\utils.test.ts` | Updated path tests to match new workspace-local format |

## Bug Fix Details

### Bug 1: Think session loads wrong/old content (CLI-side)

**Symptoms:** After Phase 09, loading a Think session read from the old global file (`~/.consilium/think_sessions/`) instead of the workspace-local file (`{workDir}/.consilium/sessions/think/`). Any changes made in the current session were invisible upon reload.

**Root cause:** In `app.py:190`, `load_think_session(session.id)` was called without the `work_dir` parameter. The function fell back to the legacy global `THINK_DIR` constant, while `HistoryManager.save_session()` correctly wrote to the workspace-local path.

**Fix:** Added:
```python
work_dir = Path(session.work_dir.unsafe_to_local_path()) if session.work_dir else None
```
and updated the call to:
```python
load_think_session(session.id, work_dir=work_dir)
```

### Bug 2: Do sessions appear duplicated/numerous (Extension-side)

**Initial over-aggressive fix:** The `listDoSessions()` handler in `session.handler.ts` was modified to remove the legacy global scan (`~/.consilium/do_sessions/`), keeping only the workspace-local scan (`{workDir}/.consilium/sessions/do/`).

**Resulting regression:** All pre-Phase 09 Do sessions disappeared from the extension UI, breaking backward compatibility for users with existing Do sessions.

**Corrected fix:** Restored the legacy global scan. The `seen` set (keyed by UUID) already deduplicates entries, so scanning both paths is safe and correct. The function now correctly lists both old and new Do sessions.

### Bug 3: Think session loading priority (Extension-side)

**Symptoms:** The `LoadConsiliumSessionHistory` handler checked the legacy global Think path first, then the workspace-local path. This could load an outdated global session when a fresher workspace-local session existed.

**Fix:** Reversed the priority — workspace-local path is checked first, legacy global path is used only as fallback. This ensures the most recent workspace-local session data takes precedence.

### Bug 6: SDK ConsiliumPaths never updated to workspace-local paths (SDK-side)

**Symptoms:** Do sessions appear in the History dropdown (from `listDoSessions()` scanning journal files), but when clicked, **no messages appear** in the chat window. The Do tab correctly opens but stays empty.

**Root cause:** The SDK's `ConsiliumPaths.sessionDir()` in `agent_sdk/paths.ts` was never updated during Phase 09. It still returned the old hashed path `~/.consilium/sessions/{md5hash}/{sessionId}`, while the CLI now writes sessions to `{workDir}/.consilium/sessions/regular/{sessionId}/wire.jsonl`. When `LoadConsiliumSessionHistory` calls `parseSessionEvents()` → `ConsiliumPaths.sessionDir()` → it looks for `wire.jsonl` in the wrong location, finds nothing, and returns empty events.

**Fix:** Updated `sessionsDir()`, `sessionDir()`, and `baselineDir()` in `agent_sdk/paths.ts` to return workspace-local paths matching the CLI's new format:
```typescript
sessionsDir(workDir: string): string {
  return path.join(workDir, ".consilium", "sessions", "regular");
}
```
This is the **critical fix** that makes Do session loading work after Phase 09.

### Bug 4: Think metadata functions hardcoded to legacy paths (Extension-side)

**Symptoms:** `readThinkSessionTitle()` and `writeThinkSessionTitle()` in `session-storage.ts` used hardcoded `~/.consilium/think_sessions/` paths. Think session titles written after Phase 09 were stored in the wrong location.

**Fix:** Both functions now accept an optional `workDir` parameter. Write operations (`writeThinkSessionTitle`) use workspace-local paths `{workDir}/.consilium/sessions/think/`. Read operations (`readThinkSessionTitle`) check workspace-local first, then fall back to legacy global.

### Bug 5: Bridge handler not passing workDir (Extension-side)

**Symptoms:** `setSessionMetadata()` and `getSessionMetadata()` in `bridge-handler.ts` called the Think session title functions without `workDir`, so they always used legacy global paths.

**Fix:** Both functions now pass `workDir` to the Think session title functions, enabling correct workspace-local path resolution.

## Root Cause Analysis

The original Phase 09 implementation correctly updated the Python CLI code to use workspace-local paths, but **missed passing `work_dir` in one critical call site** (`app.py:190` `load_think_session(session.id)`). The extension code in `kimi_extension_mod/` was **not updated at all** during Phase 09 — it continued to use hardcoded legacy global paths for Think session metadata and Do session listing. This is because Phase 09 scope was limited to `kimi_cli_mod` (the Python CLI), and the extension was not included in the implementation plan.

## Verification

| Check | Result |
|-------|--------|
| Extension packaging | ✅ `npx @vscode/vsce package` — clean build, no errors |
| `app.py` `load_think_session` call now passes `work_dir` | ✅ Code review |
| Think session loading priority (workspace-local first) | ✅ Code review |
| Do session listing scans both legacy and workspace-local | ✅ Code review |
| Think metadata functions accept `workDir` | ✅ Code review |
| Bridge handler passes `workDir` | ✅ Code review |
| SDK `ConsiliumPaths` uses workspace-local paths | ✅ Code review, tests updated |
| `parseSessionEvents()` finds `wire.jsonl` in correct location | ✅ `ConsiliumPaths.sessionDir()` now matches CLI's `{workDir}/.consilium/sessions/regular/{sessionId}` |

## Lessons Learned

1. **Cross-repo scope must be explicit in phase plans.** Phase 09's implementation plan did not include `kimi_extension_mod` in its scope. Any future phase that changes storage paths, wire protocol, or session management should explicitly list both the CLI and extension repos and define the expected changes for each.
2. **Backward compatibility requires dual-scan discipline.** When migrating from global to workspace-local paths, the correct approach is to scan both paths (with deduplication) during the transition period. Removing the legacy scan breaks existing users.
3. **One missed `work_dir` parameter breaks the entire save/load round-trip.** The `load_think_session` call in `app.py` was the only place where `work_dir` was not threaded through. A systematic audit of all call sites of functions that accept `work_dir` would have caught this.

4. **The SDK is an extension repo, not a separate package to update independently.** The `agent_sdk/` directory lives inside `kimi_extension_mod/` and is built as part of the extension. However, `ConsiliumPaths` was not included in Phase 09's scope, so it remained pointing at the old hashed path. Any future cross-cutting change (paths, wire protocol, event schemas) must explicitly audit the SDK code in `agent_sdk/` as well.