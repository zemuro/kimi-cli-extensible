---
phase_id: phase-06
title: 6: Persistent Log Architecture (PENDING)
status: pending
dependencies:
  - phase-05
files_involved:
  []
---

**Status: DESIGNED — implementation deferred.**

**Design doc:** `scratch/phase_6_persistent_log_design.md`  
**Plan file:** `C:\Users\zemuro\.kimi\plans\colossus-yelena-belova-scarlet-witch.md` (Pragmatic Option C selected)

### Overview

Replace the current split storage (Think JSONL + Do journal + wire.jsonl + context.jsonl) with a unified **persistent log + materialized view** architecture.

### Core Concepts

- **Log = immutable, append-only, forever** (the ground truth)
- **View = mutable slice of the log** (what the LLM sees)
- **Compaction = append summary entry**, don't rewrite history
- **Undo/fork = create new view from any log position**
- **Think and Do have disjoint logs**, linked by cross-reference entries

### Key Benefits

| Feature | Before | After |
|---------|--------|-------|
| Think ↔ Do traceability | None | Cross-reference entries |
| Undo range | Within tail only | Any point in full log |
| Fork cost | Copy files (slow) | Create view (instant) |
| Compaction loss | Loses history | Keeps history, views choose |
| Audit trail | Partial | Complete |

### Deferred To

This phase is intentionally deferred until:
1. Extension UI (Phase 5) is functional
2. Real usage patterns reveal whether traceability is needed
3. Performance of current storage becomes a bottleneck

**Design is complete and ready to implement when prioritized.**

---
