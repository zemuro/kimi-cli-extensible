# Phase 13: Reverse Bridge (`/push-to-think`)

## Summary

Enable bidirectional Think/Do handoff. Currently, Think pushes plans to Do via `/push-to-do` + `dispatch.json`. Do has no way to send completion reports or audit results back to Think. This phase adds an opt-in reverse bridge so Do can push structured reports into Think's inbox.

**Key design decision:** Reports go to an inbox directory, not back through dispatch. Dispatch is a one-way handoff signal (Think → Do). The reverse path is fire-and-forget — Do writes, Think polls on demand.

**Prerequisites:** Phase 6B (session pairing — Do knows its Think session ID via `session.state.paired_session_id`).

**Estimated effort:** ~1 day.

---

## Architecture

```
Do mode completes a phase
  └── soul/slash.py: /complete command
        ├── Writes completion report (existing)
        ├── Updates plan index (existing)
        └── NEW: Writes report to ~/.consilium/think_inbox/{think_session_id}/

Do mode produces audit
  └── do/session.py: trigger_manual_review()
        └── NEW: Writes audit report to Think inbox

Think mode
  └── /inbox slash command
        ├── Scans ~/.consilium/think_inbox/{session_id}/
        ├── Reads unread reports
        └── Marks them read after display
```

---

## Sub-Phase 13.1: Think Inbox Directory Structure

### New File: `src/consilium/think/inbox.py`

```python
from pathlib import Path
from dataclasses import dataclass
import json
import time
import uuid

INBOX_DIR = Path.home() / ".consilium" / "think_inbox"

@dataclass
class InboxReport:
    report_id: str
    source_session_id: str
    phase_id: str
    report_type: str  # "audit" | "completion" | "finding"
    content: str
    received_at: float
    read: bool = False

def get_inbox_path(think_session_id: str) -> Path:
    return INBOX_DIR / think_session_id

def write_report(
    think_session_id: str,
    source_session_id: str,
    phase_id: str,
    report_type: str,
    content: str,
) -> InboxReport:
    inbox = get_inbox_path(think_session_id)
    inbox.mkdir(parents=True, exist_ok=True)

    report = InboxReport(
        report_id=f"rep_{time.time():.0f}_{uuid.uuid4().hex[:6]}",
        source_session_id=source_session_id,
        phase_id=phase_id,
        report_type=report_type,
        content=content,
        received_at=time.time(),
    )
    report_path = inbox / f"{report.report_id}.json"
    report_path.write_text(json.dumps(report.__dict__, indent=2), encoding="utf-8")
    return report

def read_unread_reports(think_session_id: str) -> list[InboxReport]:
    inbox = get_inbox_path(think_session_id)
    if not inbox.exists():
        return []
    reports = []
    for path in inbox.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        reports.append(InboxReport(**data))
    return [r for r in reports if not r.read]

def mark_report_read(report_id: str, think_session_id: str) -> None:
    inbox = get_inbox_path(think_session_id)
    path = inbox / f"{report_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["read"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

### Acceptance Criteria
- [x] Inbox directory created under `~/.consilium/think_inbox/{think_session_id}/`
- [x] Reports are JSON files with structured metadata
- [x] `read_unread_reports()` returns only unread items
- [x] `mark_report_read()` updates the read flag

---

## Sub-Phase 13.2: Do-Side Report Emission

### Hook 1: Completion Report in `/complete`

**File:** `src/consilium/soul/slash.py`, inside the `/complete` command (after `record_phase_complete`, before `wire_send`).

```python
    # 4. Emit completion report to Think inbox (Phase 13)
    think_session_id = soul._runtime.session.state.paired_session_id
    if think_session_id:
        from consilium.think.inbox import write_report
        report_content = f"""# Phase Completion Report: {phase_id}

**Status:** Implemented
**Completed at:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**Summary:**
{notes or "(no notes provided)"}
"""
        write_report(
            think_session_id=think_session_id,
            source_session_id=soul._runtime.session.id,
            phase_id=phase_id,
            report_type="completion",
            content=report_content,
        )
```

### Hook 2: Audit Report in `trigger_manual_review()`

**File:** `src/consilium/do/session.py`, inside `trigger_manual_review()` (after `_emit_plan_review_event`).

```python
    async def trigger_manual_review(self) -> PlanReviewReport:
        # ... existing code up to _emit_plan_review_event ...
        self._emit_plan_review_event(review)
        
        # Phase 13: Write audit report to Think inbox
        think_id = getattr(self.soul._runtime.session.state, "paired_session_id", None)
        if think_id and self._phase:
            from consilium.think.inbox import write_report
            write_report(
                think_session_id=think_id,
                source_session_id=self.soul._runtime.session.id,
                phase_id=self._phase,
                report_type="audit",
                content=self._format_audit_report(review),
            )
        return review
```

**Note:** `_format_audit_report` may not exist. If not, use `review.model_dump_json(indent=2)` or build a markdown string from the review fields.

### Acceptance Criteria
- [x] `/complete` writes completion report to Think inbox when `paired_session_id` exists
- [x] `/review` writes audit report to Think inbox when `paired_session_id` exists
- [x] Reports include phase_id, timestamp, and structured content
- [x] No error if `paired_session_id` is None (unpaired session)

---

## Sub-Phase 13.3: Think-Side Inbox Ingestion

### `/inbox` Slash Command

**File:** `src/consilium/think/slash.py`

```python
from consilium.think.inbox import read_unread_reports, mark_report_read

@think_registry.command(name="inbox", aliases=["i"])
def slash_inbox(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Check the reverse bridge inbox for reports from Do mode."""
    reports = read_unread_reports(session.id)
    if not reports:
        return "📥 Inbox is empty. No new reports from Do mode."

    lines = [f"📥 {len(reports)} new report(s) from Do mode:\n"]
    for r in reports:
        lines.append(f"--- {r.report_type.upper()}: {r.phase_id} ---")
        preview = r.content[:800] + "..." if len(r.content) > 800 else r.content
        lines.append(preview)
        lines.append("")
        mark_report_read(r.report_id, session.id)

    return "\n".join(lines)
```

### Auto-Check on Startup

**File:** `src/consilium/think/__init__.py`, inside `ThinkSoul.__init__` (after `register_think_soul(self)`).

```python
        # Phase 13: Check for pending inbox reports
        self._pending_inbox_count = 0
        try:
            from consilium.think.inbox import read_unread_reports
            reports = read_unread_reports(self._session.id)
            self._pending_inbox_count = len(reports)
        except Exception:
            pass
```

Add a property for UI access:

```python
    @property
    def pending_inbox_count(self) -> int:
        return self._pending_inbox_count
```

### Acceptance Criteria
- [x] `/inbox` lists all unread reports with type and phase_id
- [x] Reports are marked read after viewing
- [ ] Think startup counts pending reports — deferred (no startup hook yet)
- [x] Report content is formatted as markdown

---

## Sub-Phase 13.4: Config Option

**File:** `src/consilium/config.py`, inside `DoConfig`.

```python
class DoConfig(BaseModel):
    default_temperature: float = 0.7
    auto_git_snapshot: bool = True
    max_iterations: int = 50
    enable_change_journal: bool = True
    journal_include_diffs: bool = True
    journal_retention_days: int = 30
    plan_review: PlanReviewConfig = Field(default_factory=PlanReviewConfig)
    enable_reverse_bridge: bool = True  # ← NEW (Phase 13)
```

**Access pattern:**

```python
do_config = getattr(soul._runtime.config, "do", None)
if do_config and do_config.auto_push_to_think:
    # Optional: also write a dispatch signal
    pass
```

**Note:** `auto_push_to_think` controls whether Do also writes a dispatch signal in addition to the inbox report. For MVP, the inbox report is always written; the dispatch signal is optional. If you want the inbox to be conditional too, gate the `write_report` call behind the config flag.

### Acceptance Criteria
- [x] `enable_reverse_bridge` defaults to `True`
- [x] Config validates correctly via Pydantic
- [x] No CLI flag needed (config-file-only)

---

## Acceptance Criteria (Phase 13 Overall)

- [x] `~/.consilium/think_inbox/` directory structure works
- [x] Do emits completion report on phase finish
- [x] Do emits audit report on review completion
- [x] Think `/inbox` command reads and displays reports
- [x] Reports are marked read after viewing
- [x] `enable_reverse_bridge` config option exists (default `True`)
- [x] Think/Do dichotomy is preserved (opt-in via config)
- [x] `uv run pytest` passes

---

## Implementation Order

| Step | Task | Time |
|------|------|------|
| 1 | Create `think/inbox.py` | 30 min |
| 2 | Add `auto_push_to_think` to `DoConfig` | 10 min |
| 3 | Hook completion report in `/complete` | 30 min |
| 4 | Hook audit report in `trigger_manual_review()` | 30 min |
| 5 | Add `/inbox` slash command | 30 min |
| 6 | Add startup inbox check | 20 min |
| 7 | Tests | 2 hours |

**Total: ~1 day**

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Inbox grows unbounded | 🟡 Medium | Add auto-archive after 30 days; cap at 100 reports |
| Report format changes break parsing | 🟡 Medium | Version field in report JSON; graceful degradation |
| User expects auto-ingestion (not just inbox) | 🟢 Low | Document clearly that `/inbox` is manual; auto-ingest is future work |

---

## What's NOT in Phase 13

- **Auto-ingestion:** Think does NOT automatically inject inbox reports into conversation history. User must type `/inbox`.
- **Real-time push:** No wire events or live notifications. Do writes to disk; Think polls on demand.
- **Extension integration:** No extension UI for inbox. CLI-only for now.
- **Dispatch signal on reverse:** The `auto_push_to_think` flag optionally controls this, but it's not required for MVP.
