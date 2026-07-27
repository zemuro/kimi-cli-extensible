---
document_type: phase_spec
phase: 07
id: 07
title: Investigate Why Only Think Sessions Show in History
description: >-
  The session history dropdown in the header only shows Think mode sessions.
  Do mode sessions are missing. This phase investigates the full data flow
  from frontend -> backend -> storage to find the root cause.
status: research
priority: high
created: 2026-07-26
author: Consilium
dependencies:
  - Phase 06
acceptance_criteria_summary:
  - Trace getAllConsiliumSessions() -> listSessions() -> SDK code to confirm what directories/formats are scanned
  - Compare Do session storage format/location vs Think session storage format/location
  - Identify the exact code that needs to change to include Do sessions
  - Document root cause
  - File a fix proposal
---

# Phase 07: Investigate Why Only Think Sessions Show in History

## Summary

The session history dropdown in the header only displays Think mode sessions. Do mode sessions are entirely absent. This phase traces the full data flow from the frontend `SessionList.tsx` component through the handler layer and into the SDK/storage layer to pinpoint the root cause and produce a fix proposal.

## 1. Overview

### 1.1 Problem Statement

Users who work in Do mode cannot see their Do sessions in the session history dropdown. Only Think sessions appear. This makes it impossible to browse, select, or re-enter past Do sessions through the UI, severely limiting the usability of Do mode for iterative workflows.

### 1.2 Goal

Identify all code paths that populate the session history list in the frontend, trace each path to its storage backend, determine why Do sessions are excluded, and document the root cause with a concrete fix proposal.

### 1.3 Scope Boundaries

**In scope:**
- Frontend component `SessionList.tsx` and its data-fetching logic
- Handler layer: `session.handler.ts` — specifically `getAllConsiliumSessions()`
- Backend SDK code called by the handler (session listing APIs)
- Do session storage format and location (`~/.consilium/do_sessions/`)
- Think session storage format and location (`~/.consilium/think_sessions/`)
- Regular session storage format and location (`~/.consilium/sessions/`)

**Out of scope:**
- Changes to the frontend UI layout or styling
- Fixing the actual listing bug (this phase is investigative only)
- Performance optimization of session listing
- Authentication or authorization concerns around sessions
- Non-session history features (e.g., activity logs, audit trails)

## 2. Architecture

The session history data flow has three layers:

1. **Frontend** (`SessionList.tsx`) — React component that renders the dropdown and calls a handler function.
2. **Handler** (`session.handler.ts`) — TypeScript module that provides `getAllConsiliumSessions()`, which performs two separate scans:
   - Regular sessions via SDK's `listSessions()` — looks for `wire.jsonl` in `~/.consilium/sessions/{hash}/` directories.
   - Think sessions via `listThinkSessions()` — scans for `*.jsonl` files in `~/.consilium/think_sessions/`.
3. **Storage** — Three possible directories:
   - `~/.consilium/sessions/{hash}/` — contains `wire.jsonl` for regular CLI sessions.
   - `~/.consilium/think_sessions/` — contains `*.jsonl` files for Think mode sessions.
   - `~/.consilium/do_sessions/` — contains `journal.jsonl` files for Do mode sessions (hypothesis: never scanned).

```
SessionList.tsx
    └── getAllConsiliumSessions()
            ├── listSessions() → ~/.consilium/sessions/{hash}/wire.jsonl
            └── listThinkSessions() → ~/.consilium/think_sessions/*.jsonl
            ❌ ~/.consilium/do_sessions/  ← NOT scanned
```

## 3. Detailed Design

### Task 0: Trace `getAllConsiliumSessions()` → `listSessions()` → SDK code

**Effort:** 2 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\web\src\...\SessionList.tsx` (frontend component)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\web\src\...\session.handler.ts` (handler)
- SDK source files responsible for `listSessions()` and `listThinkSessions()`

**Description:**
Read and understand the full call chain starting from `SessionList.tsx` through to the SDK's session listing functions. Document every filtering step, path construction, and file format check along the way.

### Task 1: Compare Do vs Think session storage format/location

**Effort:** 1.5 hours

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\` (check `~/.consilium/do_sessions/` and `~/.consilium/think_sessions/` sample contents)

**Description:**
Examine the directory structure, file naming conventions, and file formats used by Do sessions (`journal.jsonl`) vs Think sessions (`*.jsonl`). Identify differences that would cause the listing code to miss Do sessions entirely.

### Task 2: Identify the exact code that needs to change

**Effort:** 1 hour

**Files:**
- `session.handler.ts` (primary candidate for modification)
- Any SDK-level listing functions that need corresponding changes

**Description:**
Based on the trace from Task 0 and the comparison from Task 1, pinpoint the exact code locations (file, line number, function) that must be changed to add Do session scanning. Distinguish between:
- A missing scan path (easy fix — add a `listDoSessions()` call)
- A format incompatibility (harder fix — may need format conversion or dual-scan logic)
- A path casing issue (e.g., `c:\` vs `C:\` affecting MD5 hashes)
- A naming convention mismatch (`consilium.json` vs `kimi.json`)
- Sessions without titles being silently skipped

### Task 3: Document root cause

**Effort:** 0.5 hours

**Files:**
- This spec document (Section 6)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\index.md`

**Description:**
Write a clear root cause analysis that explains:
- What the bug is (one sentence)
- Where it occurs (file and function name)
- Why it happens (the logical gap in the code)
- What the impact is (user-facing symptom)

### Task 4: File a fix proposal

**Effort:** 1 hour

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-07-fix-proposal.md` (new file)

**Description:**
Create a fix proposal document that:
- References the root cause analysis
- Suggests concrete code changes (with before/after snippets)
- Identifies any edge cases or risks
- Estimates implementation effort
- Recommends whether this should be Phase 08 or a combined fix in Phase 07

## 4. Acceptance Criteria

- [ ] All code paths in `getAllConsiliumSessions()` are fully traced from frontend to storage
- [ ] Do session storage format and location are documented and compared against Think sessions
- [ ] The exact code changes needed to include Do sessions are identified with file paths and line numbers
- [ ] Root cause document is written with clear one-sentence bug description
- [ ] Fix proposal is filed with before/after code snippets and effort estimate

## 5. Test Plan

### 5.1 Code trace verification

1. Read `SessionList.tsx` and confirm it calls `getAllConsiliumSessions()`.
2. Read `session.handler.ts` and trace every path in `getAllConsiliumSessions()`.
3. Read SDK source (or API docs) for `listSessions()` and `listThinkSessions()`.
4. Verify that no mention of `do_sessions` or `journal.jsonl` exists in any of these files.

### 5.2 Storage inspection

1. List contents of `~/.consilium/sessions/`, `~/.consilium/think_sessions/`, and `~/.consilium/do_sessions/`.
2. Compare file names, extensions, and metadata between a sample Do session and a sample Think session.

## 6. Root Cause Analysis

### Root Cause (one sentence)

`GetAllConsiliumSessions()` in `session.handler.ts` scans `~/.consilium/think_sessions/` for Think sessions and calls the SDK's `listSessions()` for regular sessions, but never scans `~/.consilium/do_sessions/`, so Do sessions are invisible to the frontend.

### Where it occurs

- **File:** `C:/Users/zemuro/Antigravity/kimi_extension_mod/src/handlers/session.handler.ts`
- **Handler:** `[Methods.GetAllConsiliumSessions]` (line 96)
- **Missing:** A `listDoSessions()` call analogous to `listThinkSessions()` (line 123)

### Why it happens

The extension was developed with Think sessions added as a separate scan path (`listThinkSessions()` at line 58, called at line 123). When Do mode was introduced later and started storing sessions under `~/.consilium/do_sessions/{uuid}/journal.jsonl`, the `GetAllConsiliumSessions` handler was never updated to include a corresponding `listDoSessions()` scan. The SDK's `listSessions()` only covers the `~/.consilium/sessions/{hash}/wire.jsonl` path used by legacy CLI sessions.

### Impact

Users working in Do mode cannot see their Do sessions in the session history dropdown. They cannot re-enter, rename, delete, or fork a Do session through the UI. This makes Do mode functionally invisible in the session history, severely limiting iterative workflow.

### Storage comparison (Do vs Think)

| Aspect | Do sessions | Think sessions |
|--------|-------------|----------------|
| Root dir | `~/.consilium/do_sessions/` | `~/.consilium/think_sessions/` |
| Per-session format | UUID-named subdirectory | Flat `{uuid}.jsonl` file |
| Data file | `{uuid}/journal.jsonl` | `{uuid}.jsonl` |
| Extra dirs | `{uuid}/diffs/` | None |
| JSONL format | `{"id","timestamp","type","session_id","work_dir",...}` | `{"role","content"}` |
| Title source | Not embedded in journal; use workDir as display name | First `role:"user"` content |

## 7. Risks & Mitigations

Now mitigated by the investigation:

| Risk | Status | Mitigation |
|------|--------|------------|
| SDK is closed-source or hard to find | ✅ Resolved | Found at `agent_sdk/storage.ts` in the extension repo |
| Multiple root causes interact | 🟢 Low risk | Single cause: missing scan path |
| Do session files use a completely different schema | 🟢 Low risk | Both use JSONL; Do sessions in subdirectories is trivially handled |
| Sessions without titles are silently skipped | ⚠️ Medium | Do journal.jsonl doesn't embed a user message; use workDir as fallback title |

## 7. Effort Estimate

| Sub-task | Hours | Notes |
|----------|-------|-------|
| Trace getAllConsiliumSessions() -> SDK code | 2 | Frontend + handler + SDK reading |
| Compare Do vs Think storage format/location | 1.5 | Directory inspection and format comparison |
| Identify exact code needing changes | 1 | Pinpoint file, line, and function |
| Document root cause | 0.5 | Write analysis in this spec |
| File a fix proposal | 1 | Create proposal doc with code snippets |
| **Total** | **6** | Investigation phase only; no implementation |

## 8. Deferred Items

| Item | Reason |
|------|--------|
| Implementing the fix | Out of scope for this investigative phase; will be done in a follow-up phase |
| Adding automated tests for session listing | Cannot add until the fix is implemented |
| Performance profiling of the listing code | Low priority — listing is fast even with O(n) scan |
| Refactoring the handler to unify session scanning | Separate concern; not required for the root cause fix |