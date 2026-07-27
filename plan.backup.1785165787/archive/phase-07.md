---
phase_id: phase-07
title: 7: `/review` Slash Command in Do Mode
status: implemented
dependencies:
  - phase-04d
files_involved:
  - src/consilium/do/session.py
---

**Status: STAGED — ready for implementation.**

**Decision driver:** User requested in `scratch/discussion_features_next.md`.

### Problem

The plan review gate (Phase 4c) only auto-triggers when Do is seeded from Think (`--seed-from-think`). If a user types a plan directly into Do mode, there is no way to manually trigger the same `PlanReviewer` audit before execution.

### Solution

Add a `/review` slash command to Do mode that:
1. Extracts plan text from the current conversation context
2. Lazily creates a `PlanReviewer` if one does not exist
3. Runs the review subagent
4. Puts the session into `awaiting_review` state
5. Emits a `PlanReviewEvent` on the wire

The existing `/approve` and `/reject` commands (Phase 4c) already handle the `awaiting_review` state — no changes needed there.

### Implementation

#### 7.1 Lazy `PlanReviewer` creation in `DoSession`

In `src/consilium/do/session.py`:

```python
def _ensure_reviewer(self) -> PlanReviewer:
    """Lazy-create a PlanReviewer if one was not provided at init."""
    if self._reviewer is None:
        from consilium.config import DoConfig
        do_config = getattr(self.soul._runtime.config, "do", None)
        if do_config is None:
            do_config = DoConfig()
        self._reviewer = PlanReviewer(self.soul._runtime, do_config)
    return self._reviewer

async def trigger_manual_review(self) -> PlanReviewReport:
    """Manually trigger a plan review (e.g. from /review slash command)."""
    plan_text = self._extract_plan_from_context()
    if not plan_text:
        raise RuntimeError("No plan found in context to review.")
    reviewer = self._ensure_reviewer()
    review = await reviewer.review(plan_text)
    self._pending_review = review
    self._state = "awaiting_review"
    self._emit_plan_review_event(review)
    return review
```

#### 7.2 `/review` slash command

In `src/consilium/ui/shell/slash.py`, add:

```python
@registry.command
@shell_mode_registry.command
async def review(app: Shell, args: str) -> None:
    """Manually trigger a plan review for the current Do session."""
    soul = ensure_kimi_soul(app)
    if soul is None:
        return
    from consilium.do.registry import get_do_session
    do_session = get_do_session(soul._runtime.session.id)
    if do_session is None:
        console.print("[red]No Do session found.[/red]")
        return
    if do_session.state == "awaiting_review":
        console.print("[yellow]A plan review is already pending. Use /approve or /reject.[/yellow]")
        return
    try:
        report = await do_session.trigger_manual_review()
    except RuntimeError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return
    # Print formatted report
    ...
```

### Testing Requirements

| Test | Description |
|------|-------------|
| `test_trigger_manual_review_no_plan_raises` | Raises RuntimeError when no plan in context |
| `test_trigger_manual_review_creates_lazy_reviewer` | Creates reviewer, runs review, sets state |
| `test_ensure_reviewer_reuses_existing` | Does not recreate if reviewer already exists |

**Estimated effort:** 1 day.

---
