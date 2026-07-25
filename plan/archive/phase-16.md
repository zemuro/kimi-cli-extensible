# Phase 16: Platform Quota Backend

## Summary

The extension's quota overlay (Phase 7.6) polls a `GetQuota` bridge method, but the CLI side has no implementation — the extension handler throws "not implemented." This phase adds a lightweight CLI endpoint that returns quota information, either from the Consilium platform API (if available) or from local `TokenTracker` data.

**Prerequisites:** Phase 7.6 (quota overlay UI in extension), Phase 1 (Token Tracker).

**Estimated effort:** 4–6 hours.

---

## Architecture

```
Extension quota overlay (every 60s)
  └── bridge.getQuota()
        └── CLI wire handler: get_quota()
              ├── Option A: Query Consilium platform API (if platform user)
              ├── Option B: Return TokenTracker session summary
              └── Fallback: Return null (overlay hides gracefully)
```

---

## Sub-Phase 16.1: Quota Data Model

### Files

#### `src/consilium/wire/types.py` (or `wire/schema.py`)

```python
from pydantic import BaseModel

class QuotaInfo(BaseModel):
    weekly_used_minutes: int
    weekly_limit_minutes: int
    weekly_used_percentage: float
    source: "platform" | "local" | "unavailable"
```

### Acceptance Criteria
- [x] `QuotaInfo` model exists in CLI
- [x] Matches extension's expected schema

---

## Sub-Phase 16.2: Local TokenTracker Quota

### Files

#### `src/consilium/token_tracker.py`

Add `get_quota_summary()`:

```python
def get_quota_summary(session_id: str | None = None) -> QuotaInfo | None:
    """Return token usage as a quota-like structure."""
    summary = get_session_summary(session_id) if session_id else get_global_summary()
    if not summary:
        return None

    # Convert tokens to approximate minutes (very rough heuristic)
    tokens = summary.get("burned_tokens", 0)
    approx_minutes = tokens // 2000  # heuristic: ~2000 tokens ≈ 1 minute of API time

    # Use config limit if set, else default
    limit = config.budget.session_limit if config.budget else 100000
    limit_minutes = limit // 2000

    return QuotaInfo(
        weekly_used_minutes=approx_minutes,
        weekly_limit_minutes=limit_minutes,
        weekly_used_percentage=min(100.0, (tokens / limit) * 100) if limit else 0.0,
        source="local",
    )
```

### Acceptance Criteria
- [x] `get_quota_summary()` returns `QuotaInfo` from TokenTracker data
- [x] Percentage capped at 100%
- [x] Returns `None` if no tracking data exists

---

## Sub-Phase 16.3: Wire Handler

### Files

#### `src/consilium/wire/server.py` (or dedicated handler file)

Add `get_quota` endpoint:

```python
@wire_handler("get_quota")
async def handle_get_quota(params: dict, ctx: WireContext) -> dict | None:
    from consilium.token_tracker import get_quota_summary
    quota = get_quota_summary(ctx.session_id)
    return quota.model_dump() if quota else None
```

### Acceptance Criteria
- [x] Wire `get_quota` request returns `QuotaInfo` dict or `null`
- [x] Handler does not crash if TokenTracker is disabled
- [x] Response time < 100ms

---

## Sub-Phase 16.4: Platform API Integration (Optional)

If the user has Consilium platform credentials, query the real quota API (same endpoint used by `(slash)usage`).

```python
try:
    platform_quota = await platform_api.get_usage()
    return QuotaInfo(
        weekly_used_minutes=platform_quota.used_minutes,
        weekly_limit_minutes=platform_quota.limit_minutes,
        weekly_used_percentage=platform_quota.percentage,
        source="platform",
    )
except Exception:
    # Fallback to local
    return get_quota_summary(session_id)
```

**Decision:** Platform integration is optional. Local TokenTracker quota is sufficient for MVP.

### Acceptance Criteria
- [ ] Platform API queried if credentials available — skipped per plan (local quota sufficient for MVP)
- [ ] Falls back to local on any error — skipped
- [ ] Source field indicates which data was returned — skipped

---

## Acceptance Criteria (Phase 16 Overall)

- [x] Extension quota overlay shows real data (not "not implemented")
- [x] Local token usage displayed as percentage
- [x] Gracefully hides if no data available
- [x] `uv run pytest` passes

---

## Implementation Order

1. **16.1** — QuotaInfo model (15 min)
2. **16.2** — TokenTracker integration (1 hour)
3. **16.3** — Wire handler (30 min)
4. **16.4** — Platform API (optional, 2 hours)
5. **Tests** — Mock TokenTracker, verify wire response (1 hour)

**Total: ~4–6 hours**

---

## Related Deferred Items

- **Dollar budget display:** Convert token usage to estimated dollars. Requires model pricing tables. Defer — token percentage is sufficient for now.
- **Investigate wire events (12.3):** Progress notifications for `/investigate`. Low priority — CLI-only MVP is sufficient.
- **Investigate extension integration (12.5):** Investigation progress panel. Depends on 12.3.
