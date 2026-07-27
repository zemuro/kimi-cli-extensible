---
document_type: implementation_report
phase: 07
title: Investigate Why Only Think Sessions Show in History
author: Kimi Code
completion_date: 2026-07-27
---

# Phase 07 — Investigate Why Only Think Sessions Show in History

## Executive Summary

Investigated the full data flow from frontend (`SessionList.tsx`) through handler (`session.handler.ts`) into SDK (`storage.ts`) and storage (`~/.consilium/do_sessions/`). Root cause is a single missing scan path: `GetAllConsiliumSessions()` never calls a `listDoSessions()` function. Fix proposal filed with ~15 lines of new code.

## Files Changed

| File | Change |
|------|--------|
| `C:/Users/zemuro/Antigravity/kimi_cli_mod/plan/phase-07.md` | Added root cause analysis (Section 6); updated risks table; added storage comparison table |
| `C:/Users/zemuro/Antigravity/kimi_cli_mod/plan/index.md` | Updated Phase 07 status from `research` to `completed` |
| `C:/Users/zemuro/Antigravity/kimi_cli_mod/plan/reviews/phase-07-review.md` | Created review document with 🟢 verdict |
| `C:/Users/zemuro/Antigravity/kimi_cli_mod/plan/reports/phase-07-fix-proposal.md` | New fix proposal with before/after code snippets, edge cases, and effort estimate |

## Code Traced

### Layer 1: Frontend

- `kimi_extension_mod/webview-ui/src/components/SessionList.tsx` — React component, already has `<ModeBadge>` for `think`/`do`/`legacy` modes. No frontend changes needed.

### Layer 2: Handler

- `kimi_extension_mod/src/handlers/session.handler.ts` — `GetAllConsiliumSessions` (lines 96-135) performs exactly two scans: SDK `listSessions()` + local `listThinkSessions()`. No `listDoSessions()` call.
- `listThinkSessions()` (lines 58-82) — scans `~/.consilium/think_sessions/*.jsonl`.
- Confirmed: no mention of `do_sessions` or `journal.jsonl` in this file beyond the LLM title generator.

### Layer 3: SDK

- `agent_sdk/storage.ts` — `listSessions(workDir)` (line 148) scans `~/.consilium/sessions/{md5(workDir)}/wire.jsonl`. No awareness of `do_sessions/`.
- `listThinkSessions(workspaceRoot)` (line 89) — scans `~/.consilium/think_sessions/*.jsonl`.
- `ConsiliumPaths` in `paths.ts` — has `sessionsDir()` and `sessionDir()` but no `doSessionsDir()`.

### Layer 4: Storage (on disk)

| Aspect | Do sessions | Think sessions |
|--------|-------------|----------------|
| Root | `~/.consilium/do_sessions/` | `~/.consilium/think_sessions/` |
| Per-session | UUID subdirectory | Flat `{uuid}.jsonl` file |
| Data | `{uuid}/journal.jsonl` | `{uuid}.jsonl` |
| Title source | `work_dir` from first `session_start` entry | First `role:"user"` content |

## Root Cause (one sentence)

`GetAllConsiliumSessions()` in `session.handler.ts` scans `~/.consilium/think_sessions/` and `~/.consilium/sessions/{hash}/` but never scans `~/.consilium/do_sessions/`, making Do mode sessions invisible in the history dropdown.

## Acceptance Criteria

- [x] All code paths in `getAllConsiliumSessions()` traced from frontend to storage
- [x] Do session storage format and location documented and compared against Think sessions
- [x] Exact code changes identified (file, line, function) with before/after snippets
- [x] Root cause document written with clear one-sentence bug description
- [x] Fix proposal filed with effort estimate, edge cases, and risks

## Delta from Spec

| Spec Item | Actual | Notes |
|-----------|--------|-------|
| Files under `kimi_cli_mod/web/src/` | Actually in `kimi_extension_mod/` | Spec had wrong repo path; actual code found in extension repo |
| SDK in `sdks/consilium-sdk/` | Actually in `agent_sdk/` under extension repo | SDK source found at `kimi_extension_mod/agent_sdk/storage.ts` |
| `listThinkSessions()` in SDK | Actually in `session.handler.ts` AND in `agent_sdk/storage.ts` | Two separate implementations found: one in the handler (extension) and one in the SDK; extension's handler calls its own local version, not the SDK's |

## Conclusion

Investigation complete. The fix is straightforward (~15 lines in `session.handler.ts`). Recommend implementing it next — either fold into Phase 07 or make it Phase 08.

Implementation complete. Review: `C:/Users/zemuro/Antigravity/kimi_cli_mod/plan/reports/phase-07-implementation.md`
Switch to Think tab to approve or revise.
Next: implement the fix (add `listDoSessions()` to `session.handler.ts` and wire it into `GetAllConsiliumSessions`).