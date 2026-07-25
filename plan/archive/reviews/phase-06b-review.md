# Phase 6B Review: Session Pairing Support for Dual-Process

**Reviewer:** Consilium CLI  
**Date:** 2026-06-01  
**Verdict:** 🟢 **Approved with 2 minor corrections**

---

## Summary

Clean, focused plan. Six small, additive changes to enable persistent Think/Do session pairing. No new storage layers. Backward-compatible via Pydantic default fields.

---

## Change 1: `SessionState.paired_session_id`

**Verdict:** 🟢 **Approved**

- Single field addition
- Pydantic `model_validate()` handles missing fields gracefully → `None`
- No migration needed

---

## Change 2: `Dispatch.think_session_id`

**Verdict:** 🟢 **Approved**

- Single field addition
- Pydantic handles backward compat

---

## Change 3: `write_dispatch()` parameter

**Verdict:** 🟢 **Approved**

- Straightforward parameter plumbing
- No breaking changes (optional parameter with default `None`)

---

## Change 4: `push_plan_to_do()` parameter

**Verdict:** 🟢 **Approved**

- Straightforward parameter plumbing

---

## Change 5: `slash_push_to_do()` session ID access

**Verdict:** 🟡 **Approved with 1 correction**

### Issue: `think_soul.session.id` attribute path unverified (🟡)

The plan uses:
```python
think_session_id = think_soul.session.id
```

But `ThinkSoul` may not expose `session` directly. It might be `think_soul._session.id` or `think_soul.runtime.session.id` or similar.

**Fix:** Verify before implementing. Common patterns in this codebase:
```python
# Option A
think_session_id = think_soul.session.id

# Option B
think_session_id = think_soul._session.id

# Option C
think_session_id = think_soul.runtime.session_id

# Option D (most robust)
think_session_id = getattr(think_soul, 'session', getattr(think_soul, '_session', None))
if think_session_id:
    think_session_id = getattr(think_session_id, 'id', None)
```

**Recommended:** Read `src/consilium/think/soul.py` to find the exact attribute path.

---

## Change 6: `app.py` dispatch reading + session linking

**Verdict:** 🟡 **Approved with 1 correction**

### Issue: `read_dispatch()` doesn't exist yet (🟡)

The plan correctly identifies this and provides an implementation:
```python
def read_dispatch() -> Dispatch | None:
    if not DISPATCH_PATH.exists():
        return None
    try:
        return Dispatch.model_validate_json(DISPATCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
```

**Fix is correct.** Add this to `plan/dispatch.py`.

### Minor concern: Dispatch path is global, not per-workDir

`DISPATCH_PATH = Path.home() / ".consilium" / "dispatch.json"` is a single global file. If the user has multiple workspaces open, the dispatch from one workspace could leak to another.

**Mitigation:** This is acceptable for now since:
1. Only one Do session typically runs at a time
2. The Do session reads dispatch on startup, then the file is effectively consumed
3. The `think_session_id` is only used to set `paired_session_id`; wrong pairing is harmless (just shows wrong badge in SessionList)

**Future improvement:** Store dispatch in the workDir (`.consilium/dispatch.json`) instead of home directory.

---

## Tests

The test plan is minimal but sufficient:
- Backward compat for missing `paired_session_id`
- Round-trip for `write_dispatch` / `read_dispatch`
- Do session creation sets `paired_session_id`

**Add one more test:** Verify that `Session.list()` surfaces `paired_session_id` correctly. The plan mentions this as an acceptance criterion but not as an explicit test.

---

## Dependencies

| Dependency | Status |
|------------|--------|
| Phase 6a (peer status) | ✅ Complete |
| Extension Phase 7.5 | Reads `paired_session_id` from `SessionInfo` |

---

## Implementation Order

1. Add `paired_session_id` to `SessionState` (5 min)
2. Add `think_session_id` to `Dispatch` and `write_dispatch()` (10 min)
3. Pass Think session ID from `slash_push_to_do()` (10 min)
4. Add `read_dispatch()` to `plan/dispatch.py` (10 min)
5. Read dispatch and link Do session in `app.py` (20 min)
6. Tests (30 min)

**Total: ~1.5 hours** (as estimated)

---

## Final Verdict

🟢 **Ready for implementation.** Small, well-scoped, backward-compatible. The two corrections (attribute path verification, adding `read_dispatch`) are trivial to resolve during implementation.
