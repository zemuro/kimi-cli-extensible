---
phase_id: phase-04d
title: 4d: Plan-Driven Think/Do Orchestration & External Memory
status: implemented
dependencies:
  - phase-04c
files_involved:
  - src/consilium/plan/
  - src/consilium/plan/parser.py
  - src/consilium/plan/validator.py
---

**Status: IMPLEMENTED — 41 tests passing, ruff clean.**

**Replaces:** §4.3 (conversation-history bridge), §4c.2 (plan review gate — concept retained but integrated into phased workflow).

**Design principle:** Think and Do collaborate via structured **artifacts** (plan documents, audit reports, completion reports, living knowledge docs) stored in the project workspace. They do **not** exchange raw conversation history. The plan is a living Markdown document owned by Think; Do reads it and writes reports. The user approves each phase transition.

---

### §4d.1 Overview

**Old model (§4.3):**
```
Think chat history → JSON outbox → Do context injection → immediate execution
```

**New model (§4d):**
```
Think writes plan/index.md (phased, with stubs)
    ↓
Think dispatches Phase N to Do (user button, or auto if AFK)
    ↓
Do reads plan + external memory docs → audits Phase N
    ↓
Do writes audit report → auto-ingested into Think
    ↓
Think evaluates audit → edits plan or approves
    ↓
User approves Phase N → Do implements
    ↓
Do writes completion report → Phase N locked
    ↓
Do auto-advances to Phase N+1 audit
```

**Key properties:**
- **Think owns the plan.** Do never writes to `plan/index.md`.
- **Implemented phases are locked.** Historical record, immutable.
- **External memory survives sessions.** `docs/` is the long-term memory; sessions are ephemeral.
- **Session handovers** distill context into `docs/session_handover_YYYYMMDD.md`.
- **Auto-ingest** brings Do audit reports into Think's context automatically.

---

### §4d.2 Plan Document Format

**File:** `plan/index.md` (human-readable, living document)

```markdown
# Plan: Refactor Authentication Layer

## Metadata
- **plan_id:** plan_auth_refactor
- **created:** 2026-05-24
- **last_updated:** 2026-05-24

## Phase 1: Extract Token Validation
**status:** implemented
**locked:** true
**files_involved:** src/auth/token.py, src/auth/verify.py
**dependencies:** []

### Description
Move JWT validation logic from verify.py into a dedicated TokenValidator class.

### Acceptance Criteria
- [x] All existing tests pass
- [x] No regressions in token refresh flow

---

## Phase 2: Update Middleware
**status:** implemented
**locked:** true
**files_involved:** src/middleware/auth.py
**dependencies:** [phase-1]

### Description
Replace session-cookie checks with TokenValidator calls.

---

## Phase 3: Add Refresh Token Rotation
**status:** approved
**locked:** false
**files_involved:** src/auth/refresh.py
**dependencies:** [phase-1, phase-2]

### Description
Implement refresh token rotation with secure cookie flags.

---

## Phase 4: OAuth2 Integration (stub)
**status:** pending
**locked:** false
**files_involved:** []
**dependencies:** [phase-3]

### Known
- Need to support Google and GitHub providers
- PKCE required for SPA clients

### Unknown
- Which OAuth library: Authlib vs custom?
- How to handle mobile app flows?

---

## Phase 5: (stub)
**status:** pending
**locked:** false
```

**Machine-readable contract:** `docs/plan.schema.json`

Alongside `plan.md`, Think maintains a JSON schema that Do ingests programmatically. This prevents Do from misinterpreting prose, missing acceptance criteria, or skipping edge cases.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "plan_id": "plan_auth_refactor",
  "version": "2026-05-24T22:15:00Z",
  "phases": [
    {
      "phase_id": "phase-3",
      "title": "Add Refresh Token Rotation",
      "status": "approved",
      "locked": false,
      "files_involved": ["src/auth/refresh.py"],
      "dependencies": ["phase-1", "phase-2"],
      "inputs": ["docs/architecture.md", "docs/decisions.md#7"],
      "outputs": ["src/auth/refresh.py", "tests/test_refresh.py"],
      "completion_criteria": [
        "All existing tests pass",
        "No regressions in token refresh flow",
        "Migration script included if schema changes"
      ],
      "risks": ["Missing dependency: src/auth/refresh.py does not exist"],
      "audit_status": "approved"
    }
  ]
}
```

**Validation:** Do validates `plan.schema.json` against a Pydantic model on ingest. Schema mismatch → explicit field-level error, no silent misinterpretation.

**Rules:**
- Phases can be **stubs** (minimal Known/Unknown sections).
- Think fleshes out stubs as research progresses.
- Think appends new phases anytime.
- Think edits only phases with `status: pending` or `status: under_review`.
- `locked: true` is set automatically when `status` becomes `implemented`.

---

### §4d.3 Phase State Machine & Locking

```
                    Think edits OK?
pending ──► under_review ──► approved ──► implemented
  │              │              │              │
  ▼              ▼              ▼              ▼
  ✓             ✓              ✗              ✗ (locked)
```

| Status | Think can edit? | Do can read? | Description |
|--------|-----------------|--------------|-------------|
| `pending` | ✅ Yes | ✅ Yes (for audit prep) | Stub or awaiting dispatch |
| `under_review` | ⚠️ Yes (with warning) | ✅ Yes | Do is auditing; edits may cause stale audit |
| `approved` | ❌ No | ✅ Yes | Frozen pending implementation |
| `implemented` | ❌ **Locked** | ✅ Yes | Historical record; immutable |
| `aborted` | ❌ Locked | ✅ Yes | Implementation failed; preserved for analysis |

**Lock enforcement:**
- Think's plan editor validates locks before edits.
- Do's plan parser ignores `locked: true` phases for implementation (reads only for context).
- User can force-unlock via `/plan-force-unlock <phase_id>` (emergency override).

---

### §4d.4 External Memory Structure

**Principle:** `docs/` is the project's external memory. It survives session restarts, compaction, and agent turnover.

**Core skeleton (every project):**

```
docs/
├── README.md                 # Documentation index (§4d.5)
├── plan.md                   # Phased implementation plan
├── architecture.md           # What we're building, high-level design
├── decisions.md              # ADRs / design rationale (append-only)
├── guidelines.md             # Patterns, conventions, common errors (living)
├── findings.md               # Research discoveries (append-only)
├── inventory.md              # Components, APIs, endpoints, registers (living)
└── tools/
    └── README.md             # Project-specific tool registry
```

**Domain-specific extensions** (emergent, not prescribed):

| Domain | Additional docs |
|--------|-----------------|
| Reverse Engineering | `decoded_opcodes.md`, `memory_map.md`, `protocol_spec.md` |
| Embedded / RP2350 | `pinout.md`, `register_map.md`, `timing.md`, `dsp_algorithms.md`, `memory.md` |
| Web App | `api_spec.md`, `db_schema.md`, `component_library.md`, `deployment.md` |
| Website | `content_strategy.md`, `seo.md`, `user_flows.md` |

**Document types:**
- **Living:** Edited in place as the project evolves (`architecture.md`, `guidelines.md`, `inventory.md`).
- **Append-only:** New entries appended; old entries never modified (`decisions.md`, `findings.md`).
- **Frozen:** Archived, reference only (`session_handover_*.md` once superseded).

---

### §4d.5 Documentation Index

**Purpose:** Prevent agents from reading stale docs. Enable discovery of emergent docs.

**Human-readable source:** `docs/README.md`

```markdown
# Project Documentation

## Active Documents

| Document | Purpose | Status | Updated | Policy | Related Phases |
|----------|---------|--------|---------|--------|----------------|
| architecture.md | System design & data flow | current | 2026-05-20 | think_and_do | 1-3 |
| decisions.md | ADRs and design choices | current | 2026-05-22 | append_only | all |
| guidelines.md | Patterns and conventions | current | 2026-05-23 | think_and_do | all |
| findings.md | Research discoveries | current | 2026-05-24 | append_only | 4-12 |
| SLEIGH_development_guidelines.md | SLEIGH-specific patterns | current | 2026-05-18 | think_only | 1-8 |
| pi32v2_architecture.md | PI32 architecture notes | stale | 2026-04-15 | think_only | 1-2 |

## Stale Documents

| Document | Reason | Superseded By |
|----------|--------|---------------|
| pi32v2_architecture.md | Memory map wrong after Phase 8 | findings.md §3.2 |

## Emergent Docs Queue

| Document | Proposed By | Purpose | Status |
|----------|-------------|---------|--------|
| interrupt_vector.md | Phase 13 audit | Map interrupt handlers | draft |
```

**Machine-readable cache:** `.consilium/docs_index.json` (auto-generated from README.md)

```json
{
  "version": "2026-05-24T22:15:00Z",
  "documents": [
    {
      "path": "docs/architecture.md",
      "purpose": "System design & data flow",
      "status": "current",
      "last_updated": "2026-05-20T14:30:00Z",
      "update_policy": "think_and_do",
      "owner": "think",
      "related_phases": ["phase-1", "phase-2", "phase-3"],
      "stale_reason": null,
      "superseded_by": null
    },
    {
      "path": "docs/pi32v2_architecture.md",
      "purpose": "PI32 architecture notes",
      "status": "stale",
      "last_updated": "2026-04-15T10:00:00Z",
      "update_policy": "think_only",
      "owner": "think",
      "related_phases": ["phase-1", "phase-2"],
      "stale_reason": "Memory map wrong after Phase 8 findings",
      "superseded_by": "docs/findings.md"
    }
  ]
}
```

**Update policies:**

| Policy | Meaning |
|--------|---------|
| `think_only` | Only Think edits. Do reads but never writes. |
| `think_and_do` | Both can edit. (Guidelines, tools registry) |
| `append_only` | Both can append, not edit in place. (Findings, decisions) |
| `frozen` | Archived. Nobody edits. Preferably not read by agents. |

**Auto-maintenance:**
- Think updates `last_updated` when editing a doc.
- Think marks docs `stale` when discoveries contradict them.
- Think moves docs from "Emergent Docs Queue" to "Active Documents" when ready.
- A small parser regenerates `.consilium/docs_index.json` from `docs/README.md`.

---

### §4d.6 Dispatch Mechanism

**How Think signals Do to start work:**

**File:** `.consilium/dispatch.json`

```json
{
  "dispatch_id": "disp_20260524_221530",
  "plan_id": "plan_auth_refactor",
  "action": "start_review",
  "target_phase": "phase-3",
  "dispatched_at": "2026-05-24T22:15:30Z",
  "dispatched_by": "think",
  "require_user_approval": true,
  "afk_mode": false
}
```

**Flow:**

```
Think finishes plan.md update
    ↓
Think writes dispatch.json
    ↓
Extension detects dispatch.json (file watcher)
    ├── AFK OFF → shows [Push to Do] button in Think panel
    │              User clicks → sets dispatched_by: "user"
    │              Extension starts Do: kimi --do --plan plan/index.md --phase phase-3
    │
    └── AFK ON  → auto-sets dispatched_by: "afk_auto"
                  Extension starts Do immediately
    ↓
Do reads plan.md + docs_index.json + relevant docs
Do begins audit of target_phase
```

**Do CLI additions:**

```python
# src/consilium/cli/__init__.py
plan_file: Annotated[
    Path | None,
    typer.Option(
        "--plan",
        help="Path to phased plan document (Markdown)",
    ),
] = None,

phase: Annotated[
    str | None,
    typer.Option(
        "--phase",
        help="Target phase ID from the plan (e.g., phase-3)",
    ),
] = None,
```

**Do startup with plan:**

```bash
kimi --do --plan plan/index.md --phase phase-3
```

Do:
1. Reads `plan/index.md`, extracts the target phase
2. Reads `docs/README.md` (or `.consilium/docs_index.json`) to find relevant docs
3. Loads referenced docs into context as system messages
4. Begins audit (not implementation — audit comes first)

---

### §4d.7 Audit Reports & Auto-ingest

**Do audit report format:** `audits/phase-{N}-audit-{timestamp}.md`

```markdown
# Audit Report: Phase 3 — Add Refresh Token Rotation

## Feasibility: ✅ Yes (with corrections)

## Risks
1. **Architecture doc outdated**
   `docs/architecture.md` §4.1 claims refresh tokens are stateless,
   but the plan proposes server-side rotation. This contradicts the
   stated design. See docs/decisions.md #7 for original rationale.

2. **Missing dependency**
   The plan references `src/auth/refresh.py` which does not exist yet.
   Phase 2 should have created it.

## Recommendations
- Update `docs/architecture.md` §4.1 to reflect stateful rotation
- Create `src/auth/refresh.py` before implementing this phase

## Discovery
Ran existing test suite. 3 auth tests fail when rotation is enabled
(due to missing `token_family` column in users table).

## Questions
- Should migration be a separate pre-phase?
```

**Auto-ingest into Think:**

```
Do completes audit → writes audits/phase-3-audit-20260524_221800.md
    ↓
Extension detects new audit file
    ↓
If Think process is alive:
    Extension sends wire message / injects system message
    Think receives: "[Do Audit for Phase 3] ..."
    Think can auto-respond if AFK, or wait for user input
    ↓
If Think process is not alive:
    Audit queued in .consilium/think_inbox/
    Think checks inbox on next startup
```

**Think response options:**
1. **Edit plan** → updates phase description, adds dependencies
2. **Write corrections** → Think creates `docs/corrections.md` rebuttal
3. **Approve** → Think sets phase status = `approved`, writes new dispatch
4. **Discuss** → Think responds to user, waits for input

**Two-tier audit gate (cost optimization):**

Instead of always spawning an expensive LLM subagent, Do runs a fast heuristic check first:

| Tier | What | Latency | Cost |
|------|------|---------|------|
| **L1 (Heuristics)** | Regex/schema checks: missing files, circular deps, anti-patterns, acceptance criteria completeness | <100ms | Near zero |
| **L2 (LLM Audit)** | Full subagent investigation with read-only tools | 30-300s | Full LLM cost |

**L1 checks (before L2):**
- Do all `files_involved` exist? (unless `status: pending` explicitly allows creation)
- Are all `dependencies` satisfied (`status: implemented` or `approved`)?
- Any circular dependencies between phases?
- Are `completion_criteria` specific and testable?
- Any regex-matched anti-patterns in referenced files?

**Gate logic:**
```
L1 passes → skip L2, audit report = "Heuristic check passed. No risks detected."
L1 flags → run L2 for flagged items only
L1 fails hard (missing critical file) → reject immediately, no L2 needed
```

**Cache:** Project-specific rule overrides stored in `.consilium/audit_rules.yaml`. Known-safe patterns skip L2 on subsequent phases.

**Max iterations:** Default 3 audit cycles per phase. After 3 without consensus, pause for user.

---

### §4d.8 Session Handover

**Principle:** Sessions are ephemeral; handover documents are permanent. A new Think session starts by reading the handover, not old chat history.

**File:** `docs/session_handover_YYYYMMDD.md` (or `.consilium/session_handoff.json` for machine parsing)

```markdown
# Session Handover 2026-05-24

## Session Continuity
- **From:** think_abc123
- **To:** think_def456 (new session)
- **Plan version:** commit abc1234

## Completed Since Last Handover
| Phase | Status | Key Output |
|-------|--------|------------|
| 12 | implemented | src/disasm/fp_ops.sleigh |
| 13 | implemented | scratch/tools/opcode_decoder.py --fp-modifier |

## Knowledge Base Updates
- `pi32v2_architecture.md` §3.2: Corrected FP encoding group (D, not C)
- `SLEIGH_development_guidelines.md`: Added "Modifier field pitfalls"
- `decoded_opcodes.md`: Added 23 FP opcodes (0x40-0x57)

## Active Hypotheses
- Reserved modifier (111) is probably FMADD — need binary sample
- Interrupt handler might be at 0x8000_0000 (see Phase 15 stub)

## Open Questions
1. Phase 14: Verify interrupt vector table layout
2. Phase 15: Trace rekeying event (stub — needs research)

## Recommended First Action
Run `opcode_decoder` on section 0x8000_0000 to test interrupt hypothesis.
```

**New Think session startup:**
1. Read latest `docs/session_handover_*.md`
2. Read `plan/index.md` (full plan state)
3. Read `docs/README.md` (doc index — knows what's current)
4. Read docs referenced in active/open phases
5. **Do NOT read:** old chat history, old audit reports (unless referenced)

**Session rollover trigger:**
- Think context exceeds threshold (configurable, default ~30-40 turns)
- Think offers: "Context is getting full. Create handover and start new session?"
- User confirms → Think writes handover → exits → user starts new session

---

### §4d.9 Complete Workflow Examples

#### Example A: Normal mode (AFK off, user in the loop)

```
[Think] User: "Let's add OAuth2 support"
    ↓
Think appends Phase 4 stub to plan.md
Think researches Authlib vs custom
Think fleshes out Phase 4: library choice, flow diagram
    ↓
Think writes dispatch.json: target_phase=phase-4, require_user_approval=true
    ↓
[Extension] Shows [Push to Do] button in Think panel
User clicks button
    ↓
[Do] Loads plan.md + architecture.md + decisions.md
Do audits Phase 4 against codebase
    ↓
Do writes audits/phase-4-audit-20260524_103000.md
    ↓
[Extension] Auto-ingests audit into Think
[Think] "Do found that Authlib 1.3 breaks our pydantic models.
         I recommend switching to custom flow."
    ↓
User: "Agreed, update the plan"
Think edits Phase 4: switches to custom OAuth flow
Think re-dispatches Phase 4
    ↓
[Do] Re-audits → approves
    ↓
User clicks [Approve Phase 4]
Do implements Phase 4
    ↓
Do writes reports/phase-4-complete.md
Phase 4 status → implemented (LOCKED)
```

#### Example B: AFK symposium mode (agents debate, user absent)

```
[Think] AFK on. User away.
    ↓
Think writes plan → auto-dispatches Phase 1
    ↓
[Do] Audits Phase 1 → writes audit
    ↓
Auto-ingest → Think receives audit
Think AFK-auto-responds: corrects plan
    ↓
Auto-re-dispatch → Do re-audits → approves
    ↓
Think AFK-auto-approves Phase 1
Do implements Phase 1
    ↓
Auto-advance: Do begins Phase 2 audit
    ↓
... (cycle continues) ...
    ↓
After 3 audit iterations without consensus on Phase 3:
    → Pause, notify user: "Think and Do disagree on threading model"
```

#### Example C: Incremental discovery (stubs fleshed out mid-flight)

```
Think creates plan with Phases 1-3 detailed, Phases 4-6 as stubs
    ↓
Do implements Phases 1-2
    ↓
Do completion report for Phase 2 reveals: "The token format is
actually JWT+JWE, not plain JWT. This affects Phase 4 encryption."
    ↓
Think reads report → appends finding to findings.md
Think fleshes out Phase 4 stub with JWE details
Think appends Phase 7 (previously unplanned): "JWE key management"
    ↓
Do continues to Phase 3 audit...
```

---

### §4d.10 Testing Requirements

| Test | File | Description |
|------|------|-------------|
| `test_plan_parse_phases` | `tests/core/test_plan_document.py` | plan.md parsed into Phase objects |
| `test_plan_phase_lock` | `tests/core/test_plan_document.py` | implemented phase rejects edits |
| `test_plan_stub_promotion` | `tests/core/test_plan_document.py` | stub phase can be fleshed out |
| `test_docs_index_generation` | `tests/core/test_docs_index.py` | README.md → JSON index |
| `test_docs_index_stale_filter` | `tests/core/test_docs_index.py` | stale docs excluded from agent context |
| `test_dispatch_file_detected` | `tests/core/test_dispatch.py` | dispatch.json triggers Do startup |
| `test_dispatch_afk_auto` | `tests/core/test_dispatch.py` | AFK mode skips user approval |
| `test_audit_report_parsed` | `tests/core/test_audit.py` | Markdown audit → structured report |
| `test_audit_auto_ingest` | `tests/core/test_audit.py` | audit file injected into Think context |
| `test_session_handover_seed` | `tests/core/test_handover.py` | new session reads handover, has full context |
| `test_external_memory_in_context` | `tests/core/test_external_memory.py` | Do loads relevant docs before audit |
| `test_phase_completion_locks` | `tests/core/test_plan_workflow.py` | implemented phase is immutable |
| `test_incremental_plan_growth` | `tests/core/test_plan_workflow.py` | Think appends phase 7 mid-flight |

---

### §4d.11 File Inventory

| File | Purpose | Owner |
|------|---------|-------|
| `plan/index.md` | Phased implementation plan | Think (write), Do (read) |
| `docs/README.md` | Documentation index | Think (write), Do (read) |
| `.consilium/docs_index.json` | Machine-readable doc cache | Auto-generated |
| `.consilium/dispatch.json` | Think→Do signal | Think (write), Do (read) |
| `.consilium/think_inbox/` | Queued audits for offline Think | Do (write), Think (read) |
| `audits/phase-N-*.md` | Do audit reports | Do (write), Think (read) |
| `reports/phase-N-complete.md` | Do completion reports | Do (write), Think (read) |
| `docs/session_handover_*.md` | Session continuity docs | Think (write), Think (read) |
| `docs/*.md` | Domain knowledge docs | Think (write), Do (append if policy allows) |
| `docs/tools/README.md` | Tool registry | Think & Do (both write) |

---

### §4d.12 Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Markdown as source of truth** | LLMs read Markdown well; humans edit it; git diffs are clean |
| **JSON index as cache** | Programmatic access without parsing Markdown tables repeatedly |
| **Think owns plan.md exclusively** | Single writer prevents corruption; Do writes reports, not plans |
| **Implemented phases locked** | Historical record; prevents retroactive planning drift |
| **Auto-ingest audits** | Symposium feel; Think reacts to Do without manual copy-paste |
| **Session handover docs** | External memory replaces infinite context; new sessions start fresh |
| **Stubs allowed in plan** | Plans are discovered, not fully specified upfront |
| **Per-phase dispatch** | Think pushes one phase at a time; Do works sequentially |
| **Max 3 audit iterations** | Prevents infinite agent debate; user breaks ties |
| **AFK auto-dispatch** | Power users can let agents iterate unattended |

---
