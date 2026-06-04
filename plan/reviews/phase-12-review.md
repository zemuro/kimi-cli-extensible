# Phase 12 Review: `/investigate` — Parallel Background Subagents

**Reviewer:** Kimi Code CLI  
**Date:** 2026-06-01  
**Verdict:** 🟡 **Approved with 7 corrections**

---

## Sub-Phase 12.1: Result Collection Infrastructure

**Verdict:** 🟡 **Approved with 4 corrections**

### What's Good
- Leverages existing `BackgroundTaskManager` — no new infrastructure needed
- Timeout handling with task kill is robust
- `InvestigateResult` / `InvestigationResult` types are well-designed

### Issues

#### 1. `angle` variable is out of scope in result loop (🔴)

```python
for angle in angles:
    task_view = self._runtime.background_tasks.create_agent_task(...)
    task_ids.append(task_view.task_id)

# Later:
for task_id in task_ids:
    # angle is undefined here!
    results.append(InvestigationResult(angle=angle, ...))
```

**Fix:** Store a `task_id → angle` mapping:
```python
task_angles: dict[str, str] = {}
for angle in angles:
    task_view = self._runtime.background_tasks.create_agent_task(...)
    task_ids.append(task_view.task_id)
    task_angles[task_view.task_id] = angle

# Later:
for task_id in task_ids:
    angle = task_angles[task_id]
    ...
```

#### 2. `self._llm` may not exist on `ThinkSubagentSpawner` (🔴)

The plan uses `self._llm.complete()` in `_generate_angles()` but `ThinkSubagentSpawner` likely doesn't have an `_llm` attribute. It has `_runtime` which has a soul/LLM.

**Fix:** Use the runtime's LLM:
```python
async def _generate_angles(self, question: str) -> list[str]:
    soul = self._runtime.soul  # or however the soul is accessed
    response = await soul.llm.complete(prompt)
    ...
```

**Need to verify:** What LLM interface does `ThinkSubagentSpawner` have access to? Read `src/consilium/think/subagent_spawner.py` before implementing.

#### 3. `format_task()` import path unverified (🟡)

The plan imports `from consilium.background.summary import format_task`. This module may not exist.

**Fix:** Verify the import before coding. If missing, inline a simple formatter:
```python
def format_task(task_view) -> str:
    return f"Task {task_view.task_id}: {task_view.runtime.status}"
```

#### 4. `BackgroundTaskManager.wait()` semantics unverified (🟡)

The plan assumes `wait(task_id, timeout_s=...)` returns a task view and raises `TimeoutError`. Need to verify:
- Does `wait()` exist?
- Does it take a `timeout_s` parameter?
- Does it raise `TimeoutError` or return `None`?

**Fix:** Read `src/consilium/background/manager.py` before implementing. If `wait()` doesn't exist, use `asyncio.wait_for()` around `read_output()` polling.

---

## Sub-Phase 12.2: Slash Command Integration

**Verdict:** 🟢 **Approved as-is**

No issues. Straightforward, well-specified.

**Minor note:** The `ThinkSoul.available_slash_commands` reference should be verified. If slash commands are registered differently, adjust accordingly.

---

## Sub-Phase 12.3: Wire Event Streaming

**Verdict:** 🟡 **Approved with 2 corrections**

### Issues

#### 5. `wire_send` import path doesn't exist (🔴)

The plan uses:
```python
from consilium.soul import wire_send
wire_send(InvestigationProgressEvent(...))
```

But the CLI's wire system doesn't work this way. Wire events are emitted by the soul's turn iterator, not sent directly.

**Fix:** If wire events are needed, emit them through the soul's context:
```python
self._runtime.soul.context.add_event({
    "type": "investigation_progress",
    "task_id": task_id,
    "angle": angle,
    "status": status,
})
```

**Or simpler:** Skip wire events for the CLI-only MVP. Just return the report as text. Wire events can be added in 12.5 (extension integration).

#### 6. Wire event types need schema registration (🟡)

If wire events are implemented, they need Zod schemas in `agent_sdk/schema.ts` for the extension to parse them. Otherwise the extension will emit `ParseError` for unknown event types.

**Fix:** If doing 12.3, also add:
```typescript
// agent_sdk/schema.ts
export const InvestigationProgressEventSchema = z.object({
  type: z.literal("investigation_progress"),
  task_id: z.string(),
  angle: z.string(),
  status: z.string(),
  progress: z.string(),
});
```

---

## Sub-Phase 12.4: Budget Gate Integration

**Verdict:** 🟢 **Approved as-is (verification only)**

No implementation needed if `BackgroundAgentRunner` already tracks tokens. Just verify and document.

---

## Sub-Phase 12.5: Extension Webview Integration

**Verdict:** 🟡 **Approved with 1 correction**

### Issues

#### 7. Mark as deferred unless wire events are done (🟡)

This sub-phase depends on 12.3 (wire events). If 12.3 is skipped, 12.5 is moot.

**Fix:** Make 12.5 conditional on 12.3. If doing CLI-only MVP, skip both.

---

## Revised Implementation Order

| Order | Sub-Phase | Effort | Notes |
|-------|-----------|--------|-------|
| 1 | 12.1 — Result collection | 2-3 hours | Fix angle mapping, verify LLM access |
| 2 | 12.2 — Slash command | 1 hour | Straightforward |
| 3 | 12.4 — Budget verification | 30 min | Read-only verification |
| — | 12.3 — Wire events | **Optional** | Skip for CLI-only MVP |
| — | 12.5 — Extension integration | **Deferred** | Depends on 12.3 |

**Total: ~3.5-4.5 hours** (down from 5-10 by making 12.3/12.5 optional)

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `ThinkSubagentSpawner` lacks LLM access | 🔴 High | Verify class interface before coding |
| `BackgroundTaskManager.wait()` doesn't exist | 🔴 High | Read manager.py; fallback to polling |
| Background tasks fail silently | 🟡 Medium | Always read output, even on failure |
| Token usage explodes | 🟡 Medium | Respect `max_running_tasks`; default to 3 angles max |
| Report quality is poor | 🟢 Low | Start with simple concat; iterate later |

---

## Key Files to Read Before Implementing

1. `src/consilium/think/subagent_spawner.py` — Verify `_llm` or equivalent
2. `src/consilium/background/manager.py` — Verify `wait()`, `read_output()`, `kill()` APIs
3. `src/consilium/background/agent_runner.py` — Verify budget tracking
4. `src/consilium/think/slash.py` — Verify slash command registration
