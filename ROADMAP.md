# Roadmap

> Last updated: 2026-05-29

This document tracks what has been built and what is planned for the `kimi-cli-extensible` fork.

For implementation details, see `scratch/implementation_plan.md`.

---

## Implemented ✅

### Phase 1: Token Tracker
- Global token logging across all sessions
- `/token-usage` slash command
- `--budget-tokens` CLI flag
- CSV storage with session aggregation

### Phase 2: Think Mode
- Mutable-history REPL with JSONL storage
- Message edit, delete, prune, regenerate
- Checkpoint save/restore
- Context assembly with compaction awareness

### Phase 2.5: Think Mode Manual Compaction
- `/compact` command with threshold warnings
- LLM-generated summaries or naive fallback
- `compacted_into` flag on compacted messages
- Context usage estimation

### Phase 3: Do Mode — Git Snapshotting, Change Journal
- Git stash on session start, restore on abort
- Change journal records every file-modifying tool call
- Unified diff computation
- Blob storage for baselines
- `DoSession` wrapper with pre/post tool hooks

### Phase 4a: Think Python Execution & Bridge
- `run_python` tool with sandbox levels
- Think → Do bridge (`/push-to-do`, `--seed-from-think`)
- `force_abort()` instant cancellation

### Phase 4b: Polish
- Journal retention policy (archive old journals)
- Binary file handling in diffs

### Phase 4c: Subagents & Plan Review Gate
- `/explore` subagent from Think mode
- `PlanReviewer` subagent for Do mode
- `/approve` and `/reject` commands
- Pre-run hook for Think-seeded sessions

### Phase 4d: Plan Orchestration
- Plan parser, validator, audit L1/L2
- Docs index generation
- Dispatch mechanism (`dispatch.json`)
- Handover documents
- `--plan-file` and `--phase` CLI flags

### Phase 7: `/review` Slash Command
- Manually trigger plan review in Do mode
- Lazy `PlanReviewer` creation
- Works even when not seeded from Think

### Phase 8: Plan Decomposition
- Monolithic `plan.md` → `docs/plan/index.md` + `docs/plan/phase-*.md`
- YAML frontmatter per phase
- Backward-compatible single-file parsing
- Reduced token load for large projects

### Phase 9: Budget Gate
- `SubagentBudgetConfig` in TOML config
- Token and tool-call limits per subagent task
- `register_usage_hook()` on `KimiSoul`
- Graceful stop with partial results
- Coverage for both foreground and background runners

---

## Planned 🔮

### Reverse Bridge (`/push-to-think`)
**Status:** Deferred.  
**Effort:** 2–3 days.  
**Blocker:** None — waiting for user priority.  

Send Do findings (audit reports, completion reports) back to Think. Must be opt-in (`auto_push_to_think = false` default) to preserve the Think/Do dichotomy.

### `/investigate` — Parallel Background Subagents
**Status:** Deferred.  
**Effort:** 4–5 days.  
**Blocker:** Examine upstream background task architecture first.  

Spawn multiple explore subagents in parallel with different angles, collect results, and synthesize. Needs the budget gate (Phase 9) as prerequisite.

### E2E Integration Test
**Status:** Deferred.  
**Effort:** 3–4 days.  
**Blocker:** Explore Ollama for lightweight local LLM testing.  

Full pipeline test: Think generates plan → pushes to Do → Do audits → implements → Think reads completion report.

### Budget Display in Dollars
**Status:** Deferred.  
**Effort:** 1–2 days (UI).  
**Blocker:** Requires model pricing tables and user configuration.  

Convert token usage to USD for user-facing displays. Defer until extension UI work (Phase 5).

### Kimi Code Platform Quota Overlay
**Status:** Deferred.  
**Effort:** 1 day (backend) + 2 days (UI).  
**Blocker:** Phase 5 extension UI.  

Hook into the existing `(slash)usage` API to show weekly/5-hour quota remaining. Platform-specific; not universal.

### Phase 5: VS Code: Extension — Dual-Tab UI
**Status:** Deferred.  
**Effort:** 4–6 weeks.  
**Blocker:** Separate TypeScript dev cycle in `kimi extension_mod` repo.  

Think tab (mutable history, token gauge, reference collector) and Do tab (immutable timeline, tool call rendering, workspace breadcrumbs) in a VS Code: webview.

### Phase 6: Persistent Log Architecture
**Status:** Designed, not implemented.  
**Effort:** 2–3 weeks.  
**Blocker:** Real usage patterns needed to justify migration.  

Unified append-only log replacing split storage (Think JSONL + Do journal + wire.jsonl). Design doc at `scratch/phase_6_persistent_log_design.md`.

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-24 | Subagent budgets are token-based only | Dollar conversion requires pricing tables; defer to UI phase |
| 2026-05-24 | Budget gate applies to subagents only | Main Think/Do loop is user-visible; subagents are opaque |
| 2026-05-24 | Plan decomposition uses YAML frontmatter | Machine-readable + human-editable; standard tool support |
| 2026-05-24 | Reverse bridge is opt-in | Preserves Think/Do dichotomy; automatic flow breaks the model |
| 2026-05-24 | `/investigate` deferred | Examine upstream background task architecture before custom protocol |
| 2026-05-29 | Graceful stop on budget exceeded | Never cancel in-flight `kosong.step()` — risk of losing output |
| 2026-05-29 | Warnings are informational only | Async subagents can't block for `[Y/n]` prompt |
