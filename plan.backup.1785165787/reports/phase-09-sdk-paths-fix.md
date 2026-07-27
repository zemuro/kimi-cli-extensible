---
document_type: implementation_report
phase: 09-sdk-paths
title: Implementation Report — Fix SDK ConsiliumPaths After Phase 09
author: Consilium
completion_date: 2026-07-27
---

# Implementation Report — Fix SDK ConsiliumPaths After Phase 09

## Executive Summary

Phase 09 moved all session storage from global `~/.consilium/` to workspace-local `{workDir}/.consilium/sessions/`. The Python CLI was correctly updated, but the extension's SDK (`agent_sdk/paths.ts`) was **never updated** — it still returned the old hashed path format. This caused the extension's History dropdown to show sessions (because `listDoSessions()` scans journal files directly) but fail to load any content because `parseSessionEvents()` looked for `wire.jsonl` in the wrong location. The fix updates `ConsiliumPaths` in the SDK to return workspace-local paths matching the CLI's Phase 09 layout.

## Root Cause

Phase 09 scope was limited to `kimi_cli_mod` (Python CLI). The extension repo (`kimi_extension_mod/`) was not audited. The `agent_sdk/` directory lives inside the extension repo and contains its own independent path logic (`ConsiliumPaths`) that was never updated.

## The Bug

The SDK's `ConsiliumPaths.sessionDir()` returned:

```
~/.consilium/sessions/{md5hash(workDir)}/{sessionId}
```

While the CLI (after Phase 09) writes to:

```
{workDir}/.consilium/sessions/regular/{sessionId}
```

This mismatch meant:
- **`parseSessionEvents()`** looked for `wire.jsonl` in `~/.consilium/sessions/{md5hash}/{id}/` — found nothing → returned empty events → **no messages appeared** when loading any Do or regular session from the History dropdown.
- **Sessions appeared in the History list** because `listDoSessions()` scans journal files directly (not via `ConsiliumPaths`), but the **loading** path was dead.

## The Fix

Changed `agent_sdk/paths.ts`:

- **`sessionsDir()`**: `~/.consilium/sessions/{md5hash}` → `{workDir}/.consilium/sessions/regular/`
- **`sessionDir()`**: `~/.consilium/sessions/{md5hash}/{id}` → `{workDir}/.consilium/sessions/regular/{id}`
- **`baselineDir()`**: `~/.consilium/sessions/{md5hash}/{id}/baseline` → `{workDir}/.consilium/sessions/regular/{id}/baseline`
- Removed `crypto` import and `hashPath()` function (no longer needed)

Updated `agent_sdk/tests/utils.test.ts` to match new path expectations.

## Files Changed

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\paths.ts` | SDK paths now use workspace-local `{workDir}/.consilium/sessions/regular/` format |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\tests\utils.test.ts` | Updated path tests to match new workspace-local format |

## Other Fixes in This Round

For completeness, the following fixes were also applied in this round (already documented in `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-09-fix-implementation.md`):

- **CLI `app.py`**: pass `work_dir` to `load_think_session()`
- **Extension `session.handler.ts`**: Think load priority, Do dual-scan restored
- **Extension `session-storage.ts`**: Think metadata uses workspace-local paths
- **Extension `bridge-handler.ts`**: pass `workDir` to Think title functions

## Verification

| Check | Result |
|-------|--------|
| Extension packaging | ✅ `npx @vscode/vsce package` — clean build, no errors |
| `ConsiliumPaths.sessionDir()` returns workspace-local path | ✅ Code review |
| `ConsiliumPaths.sessionsDir()` returns workspace-local path | ✅ Code review |
| `ConsiliumPaths.baselineDir()` returns workspace-local path | ✅ Code review |
| SDK path tests updated | ✅ `tests/utils.test.ts` updated |
| `parseSessionEvents()` finds `wire.jsonl` in correct location | ✅ `ConsiliumPaths.sessionDir()` now matches CLI's `{workDir}/.consilium/sessions/regular/{sessionId}` |

## Delta from Spec

| Spec Item | Actual Implementation | Notes |
|-----------|----------------------|-------|
| Phase 09: Move sessions to workspace-local paths | CLI updated correctly; SDK was missed | This report documents the SDK fix |
| SDK `ConsiliumPaths` matches CLI layout | Updated `paths.ts` to use `{workDir}/.consilium/sessions/regular/` format | Hash-based paths removed |

## Lessons Learned

The SDK (`agent_sdk/`) is part of the extension repo but has its own independent path logic. Any future cross-cutting change that affects storage paths, wire protocol, or session management must explicitly include `agent_sdk/` in the audit scope. The `ConsiliumPaths` type is the single source of truth for where the SDK reads/writes session data — it must be updated in lockstep with the CLI.