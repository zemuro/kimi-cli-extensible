# Phase 5: VS Code: Extension — Incremental UI Enhancement

**Status: IN PROGRESS — 5A implemented, rename implemented, 5B–5E pending.**

**Dependencies:**
- Phase 6a (Persistent Log Architecture) — log writes are parallel
- Phase 6b (Log Read API) — **hard dependency for LogPanel**; extension needs to query logs

**Target codebases:**
- **Backend (this repo):** `src/consilium/` — wire protocol message additions ✅ DONE
- **Extension (sibling repo):** `../kimi_extension_mod/` — incremental UI additions

**Key insight:** The extension already exists with 108 source files. It uses `@moonshot-ai/kimi-agent-sdk` `ProtocolClient` for wire protocol communication. Phase 5 is **incremental enhancement**, not greenfield.

---

## Existing Extension Architecture

The `kimi_extension_mod` repo is a fork of MoonshotAI's Kimi Code: VS Code: extension with:
- `ProtocolClient` from `@moonshot-ai/kimi-agent-sdk` — wire protocol (JSON-RPC)
- Single-panel webview (`ChatArea.tsx` + `InputArea.tsx`)
- Extension ↔ Webview bridge via `shared/bridge.ts` (`Methods` + `Events`)
- CLI spawned as subprocess, extension talks via SDK protocol
- Existing components: `FileChangesPanel.tsx`, `PlanCard.tsx`, `CompactionCard.tsx`, `SessionList.tsx`, `BaselineManager`

**Transport:** Wire protocol only. No HTTP APIs. The extension does not talk REST to the CLI.

---

## Decision: Wire Protocol Extensions, Not HTTP APIs

The extension already speaks wire protocol. Adding HTTP means:
- CLI must run a web server alongside wire server
- Extension manages two transports
- Auth must work across both

**Approach:** Extend the **existing wire protocol** with new message types. This reuses the transport, requires minimal extension changes, and aligns with upstream architecture.

| Data | Approach | New Wire Messages |
|------|----------|-------------------|
| Log entries | Wire protocol query | `LogQueryRequest` / `LogQueryResponse` |
| Plan documents | Wire protocol fetch | `PlanFetchRequest` / `PlanFetchResponse` |
| Cross-reference trace | Wire protocol trace | `TraceRequest` / `TraceResponse` |
| Token usage | Wire protocol status | Extend `StatusUpdate` or new `TokenStatusUpdate` |

---

## Phase 5A: Wire Protocol Extensions (This Repo)

**Backend work in `src/kimi_cli/`**

### New Wire Message Types

```python
# src/kimi_cli/wire/types.py

class LogQueryRequest(BaseModel):
    """Extension requests log entries for a session."""
    session_id: str
    log_owner: str  # "think" | "do"
    filter_type: str | None = None  # "message", "diff", "review", etc.
    after_id: str | None = None
    limit: int = 100

class LogQueryResponse(BaseModel):
    """Backend returns log entries."""
    entries: list[dict]  # Serialized LogEntry
    has_more: bool

class PlanFetchRequest(BaseModel):
    """Extension requests plan document."""
    plan_file: str  # "plan/index.md" or "plan/phase-01.md"

class PlanFetchResponse(BaseModel):
    """Backend returns plan document content."""
    content: str
    parsed: dict | None = None  # Optional: parsed frontmatter + body

class TraceRequest(BaseModel):
    """Extension requests cross-log traceability."""
    entry_id: str
    direction: str  # "think_to_do" | "do_to_think"

class TraceResponse(BaseModel):
    """Backend returns linked entries."""
    linked_entries: list[dict]
    source_session_id: str
    target_session_id: str
```

### Wire Protocol Handlers

In `src/kimi_cli/wire/server.py`, add handlers for the new request types:

```python
async def _handle_log_query(self, request: LogQueryRequest) -> LogQueryResponse:
    from kimi_cli.plan.persistent_log import PersistentLog
    log = PersistentLog.for_session(request.session_id, request.log_owner)
    entries = log.find_entries_by_type(request.filter_type, after_id=request.after_id)
    return LogQueryResponse(
        entries=[e.__dict__ for e in entries[:request.limit]],
        has_more=len(entries) > request.limit,
    )

async def _handle_plan_fetch(self, request: PlanFetchRequest) -> PlanFetchResponse:
    path = Path(request.plan_file)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {path}")
    content = path.read_text(encoding="utf-8")
    # Optionally parse frontmatter
    return PlanFetchResponse(content=content)
```

### Files to Create/Modify (This Repo)

| File | Change |
|------|--------|
| `wire/types.py` | Add `LogQueryRequest/Response`, `PlanFetchRequest/Response`, `TraceRequest/Response` to `WireEvent` union |
| `wire/server.py` | Add `_handle_log_query`, `_handle_plan_fetch`, `_handle_trace` methods |
| `plan/persistent_log.py` | Add `for_session()` classmethod; verify `find_entries_by_type()` works |
| `plan/bridge.py` | Verify `trace_think_to_do()` and `trace_do_to_think()` are callable from wire handler |

### Testing (This Repo)

| Test | Description |
|------|-------------|
| `test_wire_log_query` | `LogQueryRequest` → `LogQueryResponse` roundtrip |
| `test_wire_plan_fetch` | `PlanFetchRequest` → `PlanFetchResponse` with real plan file |
| `test_wire_trace` | `TraceRequest` → `TraceResponse` with cross-references |
| `test_wire_unknown_type` | Unknown filter_type returns empty list |
| `test_wire_pagination` | `limit=2` returns 2 entries, `has_more=true` |

**Estimated effort:** 1–2 days.

---

## Phase 5B: Extension Shared Types + Handlers (Extension Repo)

**Work in `kimi extension_mod/`**

### Shared Types

Add to `shared/types.ts`:

```typescript
export interface LogEntry {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  prev_id: string | null;
  timestamp: number;  // Unix float
  log_owner: "think" | "do";
}

export interface LogQueryRequest {
  session_id: string;
  log_owner: "think" | "do";
  filter_type?: string;
  after_id?: string;
  limit: number;
}

export interface LogQueryResponse {
  entries: LogEntry[];
  has_more: boolean;
}

export interface PlanFetchRequest {
  plan_file: string;
}

export interface PlanFetchResponse {
  content: string;
  parsed?: { frontmatter: Record<string, unknown>; body: string };
}
```

### Bridge Methods

Add to `shared/bridge.ts`:

```typescript
export const Methods = {
  // ... existing methods ...
  QueryLogs: "queryLogs",
  FetchPlan: "fetchPlan",
  TraceEntry: "traceEntry",
} as const;

export const Events = {
  // ... existing events ...
  LogQueryResult: "logQueryResult",
  PlanFetched: "planFetched",
  TraceResult: "traceResult",
} as const;
```

### Extension Handlers

In `src/handlers/` (or existing handler files):

```typescript
// Handle webview → extension → CLI
async function handleQueryLogs(request: LogQueryRequest): Promise<LogQueryResponse> {
  const cli = cliManager.getActiveCLI();
  if (!cli) throw new Error("No active CLI session");
  return cli.sendRequest(Methods.QueryLogs, request);
}

async function handleFetchPlan(request: PlanFetchRequest): Promise<PlanFetchResponse> {
  const cli = cliManager.getActiveCLI();
  if (!cli) throw new Error("No active CLI session");
  return cli.sendRequest(Methods.FetchPlan, request);
}
```

### Files to Modify (Extension Repo)

| File | Change |
|------|--------|
| `shared/types.ts` | Add LogEntry, LogQuery*, PlanFetch* interfaces |
| `shared/bridge.ts` | Add `QueryLogs`, `FetchPlan`, `TraceEntry` to Methods; add result events |
| `src/handlers/chat.handler.ts` or new `log.handler.ts` | Wire handler functions |
| `src/managers/cli.manager.ts` | Ensure `sendRequest` method exists on CLI client |

### Testing (Extension Repo)

| Test | Description |
|------|-------------|
| `types_compile` | TypeScript compiles with new shared types |
| `bridge_methods` | New methods are in Methods enum |
| `handler_queryLogs` | Handler calls CLI client with correct payload |

**Estimated effort:** 1 day.

---

## Phase 5C: Webview UI Enhancements (Extension Repo)

**Enhance existing single-panel webview with new components.**

### Plan Status Table

Extend existing `PlanCard.tsx`:

```tsx
// Add to PlanCard or create PlanStatusModal
interface PlanStatusTableProps {
  phases: Array<{
    phase_id: string;
    title: string;
    status: string;
    locked: boolean;
  }>;
}

export function PlanStatusTable({ phases }: PlanStatusTableProps) {
  return (
    <table>
      <thead>
        <tr><th>Phase</th><th>Title</th><th>Status</th><th>Locked</th></tr>
      </thead>
      <tbody>
        {phases.map(p => (
          <tr key={p.phase_id}>
            <td>{p.phase_id}</td>
            <td>{p.title}</td>
            <td>{p.status}</td>
            <td>{p.locked ? "✅" : "❌"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

**Integration:** Call `bridge.fetchPlan({ plan_file: "plan/index.md" })` on mount, parse Markdown table.

### Log Timeline (Modal or Expandable)

New component `LogTimeline.tsx`:

```tsx
interface LogTimelineProps {
  entries: LogEntry[];
  onTrace: (entryId: string) => void;
}

export function LogTimeline({ entries, onTrace }: LogTimelineProps) {
  return (
    <div className="log-timeline">
      {entries.map(entry => (
        <div key={entry.id} className={`log-entry log-entry-${entry.type}`}>
          <span className="timestamp">{formatTimestamp(entry.timestamp)}</span>
          <span className="type">{entry.type}</span>
          <span className="payload">{JSON.stringify(entry.payload).slice(0, 100)}</span>
          {entry.type === "diff" && (
            <button onClick={() => onTrace(entry.id)}>Trace</button>
          )}
        </div>
      ))}
    </div>
  );
}
```

**Integration:** Call `bridge.queryLogs({ session_id, log_owner: "do", limit: 50 })`.

### Token Usage Display

Extend existing status bar or add `TokenUsageBar.tsx`:

```tsx
interface TokenUsageProps {
  contextUsage: number;
  contextTokens: number;
  maxContextTokens: number;
}

export function TokenUsageBar({ contextUsage, contextTokens, maxContextTokens }: TokenUsageProps) {
  const percent = (contextTokens / maxContextTokens) * 100;
  return (
    <div className="token-bar">
      <div className="token-bar-fill" style={{ width: `${percent}%` }} />
      <span>{contextTokens} / {maxContextTokens} ({Math.round(percent)}%)</span>
    </div>
  );
}
```

**Integration:** Already receives `StatusUpdate` via wire protocol. Extract `context_tokens` and `max_context_tokens`.

### Files to Create/Modify (Extension Repo)

| File | Change |
|------|--------|
| `webview-ui/src/components/PlanStatusTable.tsx` | NEW: Render plan index status table |
| `webview-ui/src/components/LogTimeline.tsx` | NEW: Render log entry timeline |
| `webview-ui/src/components/TokenUsageBar.tsx` | NEW: Token usage bar |
| `webview-ui/src/components/PlanCard.tsx` | MODIFY: Add "View Plan" button that opens PlanStatusTable |
| `webview-ui/src/stores/log-store.ts` | NEW: Zustand store for log entries |
| `webview-ui/src/stores/plan-store.ts` | NEW: Zustand store for plan documents |
| `webview-ui/src/App.tsx` | MODIFY: Add modals or sections for new components |

### Testing (Extension Repo)

| Test | Description |
|------|-------------|
| `PlanStatusTable_renders` | Renders phases with correct statuses |
| `LogTimeline_renders` | Renders entries with timestamps |
| `TokenUsageBar_percentage` | Calculates percentage correctly |
| `App_modal_plan` | Clicking "View Plan" opens modal |

**Estimated effort:** 2–3 days.

---

## Phase 5D: Review + Diff Polish (Extension Repo)

### Review Report Modal

New component `ReviewReportModal.tsx`:

```tsx
interface ReviewReportProps {
  feasible: boolean;
  risks: string[];
  recommendations: string[];
  onApprove: () => void;
  onReject: () => void;
}

export function ReviewReportModal({ feasible, risks, recommendations, onApprove, onReject }: ReviewReportProps) {
  return (
    <div className="review-modal">
      <h3>Plan Review</h3>
      <div className={feasible ? "feasible" : "not-feasible"}>
        {feasible ? "✅ Feasible" : "❌ Not Feasible"}
      </div>
      <h4>Risks</h4>
      <ul>{risks.map(r => <li key={r}>{r}</li>)}</ul>
      <h4>Recommendations</h4>
      <ul>{recommendations.map(r => <li key={r}>{r}</li>)}</ul>
      <button onClick={onApprove}>Approve</button>
      <button onClick={onReject}>Reject</button>
    </div>
  );
}
```

**Integration:** Listen for `PlanReviewEvent` on wire. Show modal when received.

### Inline Diff Accept/Reject

Reference: `scratch/frontend/inline_diff_implementation_plan.md`

**Key decision:** The existing `FileChangesPanel.tsx` already shows changes. Inline diff decorations (green/red backgrounds + CodeLens buttons) require the full 53KB spec. This is complex enough to be a standalone phase.

**For Phase 5D MVP:** Add accept/reject buttons to `FileChangesPanel.tsx` (list level, not inline decorations). Inline decorations deferred to Phase 12.

```tsx
// In FileChangesPanel.tsx
<button onClick={() => bridge.acceptFile(file.path)}>Accept</button>
<button onClick={() => bridge.rejectFile(file.path)}>Reject</button>
```

### Commands

Add to VS Code: command palette:

```typescript
vscode.commands.registerCommand("kimi.planStatus", () => {
  // Open PlanStatusTable modal
});
vscode.commands.registerCommand("kimi.logTimeline", () => {
  // Open LogTimeline modal
});
vscode.commands.registerCommand("kimi.approveReview", () => {
  // Send /approve to CLI
});
vscode.commands.registerCommand("kimi.rejectReview", () => {
  // Send /reject to CLI
});
```

### Files to Create/Modify (Extension Repo)

| File | Change |
|------|--------|
| `webview-ui/src/components/ReviewReportModal.tsx` | NEW: Review report display |
| `webview-ui/src/components/FileChangesPanel.tsx` | MODIFY: Add accept/reject buttons per file |
| `src/commands/plan.commands.ts` | NEW: `kimi.planStatus`, `kimi.logTimeline` |
| `src/commands/review.commands.ts` | NEW: `kimi.approveReview`, `kimi.rejectReview` |
| `extension.ts` | MODIFY: Register new commands |

### Testing (Extension Repo)

| Test | Description |
|------|-------------|
| `ReviewReportModal_renders` | Shows feasibility, risks, recommendations |
| `ReviewReportModal_buttons` | Approve/Reject buttons call callbacks |
| `FileChangesPanel_accept` | Accept button calls bridge method |
| `command_planStatus` | Command opens plan status |

**Estimated effort:** 2 days.

---

## Summary: Corrected Phase Breakdown

| Phase | Where | What | Effort |
|-------|-------|------|--------|
| **5A** | This repo | Wire protocol extensions (`LogQuery`, `PlanFetch`, `Trace`) | 1–2 days |
| **5B** | Extension repo | Shared types + bridge Methods/Events + handlers | 1 day |
| **5C** | Extension repo | PlanStatusTable, LogTimeline, TokenUsageBar | 2–3 days |
| **5D** | Extension repo | ReviewReportModal, commands, file accept/reject | 2 days |
| **5E** | Extension repo | **Inline diff decorations** (deferred — see inline_diff_plan) | — |

**Total: 6–8 days** (vs. 4 weeks in original over-scoped plan)

---

## Pre-existing Issues to Note

1. **Repo path has space**: `kimi extension_mod` — may cause script/tooling issues. Consider renaming to `kimi-extension-mod`.
2. **SDK compatibility**: `@moonshot-ai/kimi-agent-sdk` is upstream. If CLI fork diverges, SDK may need forking too.
3. **Dual UI**: CLI has `web/` (React SPA) and extension has `webview-ui/` (React webview). Feature parity between them is unsustainable. Extension is primary.
4. **Phase 6b dependency**: LogPanel needs `PersistentLog` read API. Phase 6a only writes. Ensure 6b is done before 5C LogPanel.
