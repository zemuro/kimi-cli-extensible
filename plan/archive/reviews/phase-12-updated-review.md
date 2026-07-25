# Phase 12 Updated Review: `/investigate` — Parallel Background Subagents

**Reviewer:** Kimi Code CLI  
**Date:** 2026-06-01  
**Verdict:** 🟡 **Approved with 3 corrections**

---

## Summary

All review corrections from the previous review have been applied:
- ✅ Angle mapping fixed (`task_angles` dict)
- ✅ LLM access via `_runtime.soul.llm` with fallback to static angles
- ✅ `format_task()` has `ImportError` fallback
- ✅ Wire events made optional and deferred
- ✅ Extension integration deferred
- ✅ Auto-angles capped at 3

Remaining issues are minor and can be fixed during implementation.

---

## Sub-Phase 12.1: Result Collection Infrastructure

**Verdict:** 🟡 **Approved with 2 corrections**

### Issue 1: `response` undefined in fallback path (🔴)

```python
try:
    response = await soul.llm.complete(prompt)
    angles = json.loads(response)
    ...
except (json.JSONDecodeError, AttributeError):
    pass

# Fallback: response may be undefined!
return [line.strip("- ").strip() for line in response.splitlines() ...]
```

If `soul.llm.complete()` throws `AttributeError` (soul or llm missing), `response` is never assigned. The fallback throws `NameError`.

**Fix:** Initialize `response` before the try block:
```python
response = ""
try:
    response = await soul.llm.complete(prompt)
    angles = json.loads(response)
    if isinstance(angles, list) and all(isinstance(a, str) for a in angles):
        return angles
except (json.JSONDecodeError, AttributeError):
    pass

return [line.strip("- ").strip() for line in response.splitlines() if line.strip()][:5]
```

### Issue 2: `_generate_angles` fallback uses `response` from outer scope (🟡)

The fallback `return [line.strip("- ").strip() ...]` references `response` which was assigned inside the `try` block. If the `try` block fails before `response = await soul.llm.complete(prompt)`, `response` is undefined.

This is the same issue as #1. Fixing #1 resolves this.

**Additional fix:** If `response` is empty (soul missing, no LLM), return static angles:
```python
if not response:
    return ["Root cause", "Impact assessment", "Resolution options"]
```

---

## Sub-Phase 12.2: Slash Command Integration

**Verdict:** 🟢 **Approved as-is**

Clean and straightforward. No issues.

---

## Sub-Phase 12.3: Wire Event Streaming

**Verdict:** 🟢 **Approved — correctly marked as optional**

Good decision to skip for CLI-only MVP. The text report is sufficient.

---

## Sub-Phase 12.4: Budget Gate Integration

**Verdict:** 🟢 **Approved — verification only**

The cap at 3 angles is a good safeguard:
```python
return angles[:3]
```

**One addition:** Also enforce `max_running_tasks` before spawning:
```python
max_tasks = self._runtime.config.background.max_running_tasks or 4
if len(angles) > max_tasks:
    angles = angles[:max_tasks]
```

This prevents spawning more tasks than the system allows.

---

## Sub-Phase 12.5: Extension Webview Integration

**Verdict:** 🟢 **Approved — correctly deferred**

Not needed for CLI-only MVP.

---

## Acceptance Criteria Review

| Criterion | Status | Notes |
|-----------|--------|-------|
| `/investigate <question>` auto-generates up to 3 angles | ✅ | Cap at 3 angles |
| `/investigate <question> | angle1, angle2` uses provided angles | ✅ | Straightforward parsing |
| All background tasks complete and results collected | ✅ | Wait + read_output loop |
| Unified report returned to user | ✅ | Simple concatenation |
| Timed-out tasks killed and reported | ✅ | `except TimeoutError` + `kill()` |
| Failed tasks reported with error message | ✅ | Generic `except Exception` added |
| `max_running_tasks` respected | ⚠️ | Add pre-flight angle truncation |
| Token usage tracked per task | ✅ | BackgroundAgentRunner handles this |
| `uv run pytest` passes | ✅ | Add tests for new types |

---

## Revised Implementation Order

| Order | Sub-Phase | Effort | Notes |
|-------|-----------|--------|-------|
| 1 | 12.1 — Result collection | 2-3 hours | Fix `response` init; verify `wait()` API |
| 2 | 12.2 — Slash command | 1 hour | Straightforward |
| 3 | 12.4 — Budget verification | 30 min | Read-only + add angle truncation |

**Total: ~3.5-4.5 hours**

---

## Key Files to Read Before Implementing

1. `src/consilium/think/subagent_spawner.py` — Verify `_runtime` structure, find exact LLM access path
2. `src/consilium/background/manager.py` — Verify `wait()`, `read_output()`, `kill()` signatures
3. `src/consilium/background/agent_runner.py` — Verify budget/token tracking
4. `src/consilium/think/slash.py` — Verify slash command registration mechanism

---

## Final Verdict

🟡 **Ready for implementation with 3 minor corrections.** The plan is well-scoped, corrections from the previous review have been applied, and the remaining issues (`response` initialization, `max_running_tasks` enforcement) are trivial fixes.
