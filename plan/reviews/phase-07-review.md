---
document_type: review
phase: 07
title: Phase 07 Review — Investigate Why Only Think Sessions Show in History
reviewer: Kimi Code
review_date: 2026-07-27
verdict: 🟢
---

# Phase 07 Review — Investigate Why Only Think Sessions Show in History

## Verdict

🟢 **Feasible and investigation is complete** — all five acceptance criteria can be met.

## Actual Code Trace Results

### Layer 1: Handler (`kimi_extension_mod/src/handlers/session.handler.ts`)

`GetAllConsiliumSessions` (line 96) performs exactly two scans:

1. **`listSessions(dir)`** (SDK) — scans `~/.consilium/sessions/{hash}/` for UUID-named subdirectories containing `wire.jsonl`. These are regular/legacy CLI sessions.
2. **`listThinkSessions()`** (local, lines 58-82) — scans `~/.consilium/think_sessions/*.jsonl`. These are Think-mode sessions.

**No scan of `~/.consilium/do_sessions/` exists.** This is the root cause.

### Layer 2: SDK (`agent_sdk/storage.ts`)

`listSessions(workDir)` (line 148):
- Resolves `sessionsDir = ~/.consilium/sessions/{md5(workDir)}/`
- Iterates UUID-named subdirectories
- Looks for `wire.jsonl` inside each
- Reads `metadata.json` or first `TurnBegin` user message for title

`listThinkSessions(workspaceRoot)` (line 89):
- Scans `~/.consilium/think_sessions/*.jsonl`
- Reads first `role: "user"` message for title

**No `listDoSessions()` function exists anywhere in the codebase.**

### Layer 3: Storage (on disk)

| Aspect | Do sessions | Think sessions |
|--------|-------------|----------------|
| Root dir | `~/.consilium/do_sessions/` | `~/.consilium/think_sessions/` |
| Per-session format | UUID-named subdirectory | Flat `{uuid}.jsonl` file |
| Data file | `{uuid}/journal.jsonl` | `{uuid}.jsonl` |
| Extra dirs | `{uuid}/diffs/` | None |
| File format | JSONL, `{"id","timestamp","type","session_id","work_dir","initial_git_head"}` | JSONL, `{"role","content"}` |
| Title source | Not embedded — must come from metadata or workDir | First `role: "user"` content |

### Frontend (`kimi_extension_mod/webview-ui/src/components/SessionList.tsx`)

Already has `<ModeBadge>` for `think`/`do`/`legacy` modes — no frontend changes needed.

## Risks/Mitigations

| Risk | Status | Mitigation |
|------|--------|------------|
| SDK source hard to find | ✅ Resolved | Found at `agent_sdk/storage.ts` in the extension repo |
| Format incompatibility | 🟢 Low risk | Both use JSONL; Do sessions are in subdirectories but that's easy to scan |
| Sessions without titles skipped | ⚠️ Medium | Do journal.jsonl doesn't embed a user message; need to derive title from `work_dir` or CLI-side metadata |

## Acceptance Criteria Status

- [x] All code paths in `getAllConsiliumSessions()` traced from frontend to storage
- [x] Do session storage format and location documented and compared against Think sessions
- [x] Exact code changes identified (see fix proposal)
- [ ] Root cause document written
- [ ] Fix proposal filed

**Items remaining:** Root cause + fix proposal (Tasks 3 & 4).