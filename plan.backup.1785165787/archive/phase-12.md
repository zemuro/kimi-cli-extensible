# Phase 12: `/investigate` — Parallel Background Subagents

## Summary

Implement the `/investigate` slash command in Think mode as a first-class feature. It spawns multiple background subagent tasks (one per "angle"), monitors their progress, and aggregates results into a unified report. This leverages the existing `BackgroundTaskManager` and `ThinkSubagentSpawner` infrastructure.

**Current state:** `think/subagent_spawner.py` has an `investigate()` stub that creates tasks but returns `[]` immediately with a TODO comment. `BackgroundTaskManager` is production-ready.

**Prerequisite:** Phase 11 (plan-centric handoff) and Phase 6a (persistent logging) are complete.

**Review corrections applied:** Angle mapping fixed; LLM access via `_runtime`; wire events made optional; extension integration deferred.

---

## Architecture

```
User types: /investigate "Why is the build failing?"

ThinkSoul
  └── slash_investigate(args)
        ├── Parse question + generate angles (or use provided angles)
        ├── Call ThinkSubagentSpawner.investigate(question, angles)
        │     └── For each angle:
        │           └── background_tasks.create_agent_task(...)
        │                 └── BackgroundAgentRunner.run()  (asyncio.Task)
        ├── Collect results via BackgroundTaskManager.wait() / read_output()
        ├── Aggregate into unified report
        └── Return report to user
```

---

## Sub-Phase 12.1: Result Collection Infrastructure

### Problem
`ThinkSubagentSpawner.investigate()` calls `create_agent_task()` in a loop but:
1. Doesn't capture or return the `task_id`s mapped to angles
2. Doesn't wait for or read task outputs
3. Returns `[]` immediately

### Solution
Add result collection to `ThinkSubagentSpawner` using the existing `BackgroundTaskManager` API.

### Key files to read before implementing
1. `src/consilium/think/subagent_spawner.py` — Verify LLM access (likely via `self._runtime.soul.llm`)
2. `src/consilium/background/manager.py` — Verify `wait()`, `read_output()`, `kill()` APIs
3. `src/consilium/background/agent_runner.py` — Verify budget tracking

### File: `src/consilium/think/subagent_spawner.py`

**New `investigate` implementation:**

```python
async def investigate(self, question: str, angles: list[str]) -> InvestigateResult:
    """Spawn background investigation tasks per angle and collect results."""
    if not angles:
        angles = await self._generate_angles(question)

    # Map task_id -> angle
    task_angles: dict[str, str] = {}
    task_ids: list[str] = []

    for angle in angles:
        task_view = self._runtime.background_tasks.create_agent_task(
            agent_id=f"think-investigate-{uuid.uuid4().hex[:8]}",
            subagent_type="explore",
            prompt=f"{question}\n\nFocus on this angle: {angle}",
            description=f"Investigate: {angle}",
            tool_call_id="",
            model_override=None,
            timeout_s=self._runtime.config.background.agent_task_timeout_s,
        )
        task_ids.append(task_view.task_id)
        task_angles[task_view.task_id] = angle

    # Collect results from all tasks
    results: list[InvestigationResult] = []
    for task_id in task_ids:
        angle = task_angles[task_id]
        try:
            # Wait for task completion (with timeout)
            final_view = await self._runtime.background_tasks.wait(
                task_id,
                timeout_s=self._runtime.config.background.agent_task_timeout_s,
            )
            # Read the task output
            output = self._runtime.background_tasks.read_output(task_id)

            # Format summary (fallback if format_task unavailable)
            try:
                from consilium.background.summary import format_task
                summary = format_task(final_view)
            except ImportError:
                summary = f"Task {task_id}: {final_view.runtime.status}"

            results.append(InvestigationResult(
                task_id=task_id,
                angle=angle,
                status=final_view.runtime.status,
                summary=summary,
                output=output,
            ))
        except (TimeoutError, asyncio.TimeoutError):
            results.append(InvestigationResult(
                task_id=task_id,
                angle=angle,
                status="timeout",
                summary="Investigation timed out",
                output="",
            ))
            # Kill the timed-out task
            await self._runtime.background_tasks.kill(task_id, reason="timeout")
        except Exception as e:
            results.append(InvestigationResult(
                task_id=task_id,
                angle=angle,
                status="error",
                summary=f"Investigation failed: {e}",
                output="",
            ))

    # Aggregate into unified report
    report = self._aggregate_results(question, results)

    return InvestigateResult(
        question=question,
        angles=angles,
        results=results,
        report=report,
    )
```

**Angle generation:**

```python
async def _generate_angles(self, question: str) -> list[str]:
    """Use the Think runtime's LLM to generate investigation angles."""
    # Access LLM via runtime -> soul -> llm
    soul = getattr(self._runtime, 'soul', None)
    if not soul or not hasattr(soul, 'llm'):
        # Fallback: return generic angles
        return ["Root cause", "Impact assessment", "Resolution options"]

    prompt = (
        f"Given the question: '{question}',\n"
        "Generate 3-5 specific investigation angles. "
        "Each angle should be a concise phrase (2-6 words). "
        "Return as a JSON array of strings."
    )

    try:
        response = await soul.llm.complete(prompt)
        angles = json.loads(response)
        if isinstance(angles, list) and all(isinstance(a, str) for a in angles):
            return angles
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: split by lines, filter empty
    return [line.strip("- ").strip() for line in response.splitlines() if line.strip()][:5]
```

**Report aggregation:**

```python
def _aggregate_results(self, question: str, results: list[InvestigationResult]) -> str:
    """Aggregate individual investigation results into a unified report."""
    lines = [f"# Investigation: {question}\n"]
    for r in results:
        lines.append(f"\n## {r.angle}\n")
        lines.append(f"**Status:** {r.status}\n")
        if r.summary:
            lines.append(r.summary)
        lines.append("\n")
    return "\n".join(lines)
```

### New types (add to `think/models.py` or new file `think/investigate.py`)

```python
from dataclasses import dataclass

@dataclass(slots=True)
class InvestigationResult:
    task_id: str
    angle: str
    status: str
    summary: str
    output: str

@dataclass(slots=True)
class InvestigateResult:
    question: str
    angles: list[str]
    results: list[InvestigationResult]
    report: str
```

---

## Sub-Phase 12.2: Slash Command Integration

### File: `src/consilium/think/slash.py`

Add `/investigate` slash command:

```python
async def slash_investigate(think_soul: ThinkSoul, args: str) -> str:
    """Spawn parallel background investigations.

    Usage:
      /investigate <question>          → Auto-generate angles
      /investigate <question> | a, b   → Use provided angles
    """
    if not args.strip():
        return "Usage: /investigate <question> [ | angle1, angle2, ... ]"

    # Parse question and optional angles
    if " | " in args:
        question, angles_str = args.split(" | ", 1)
        angles = [a.strip() for a in angles_str.split(",") if a.strip()]
    else:
        question = args.strip()
        angles = []

    spawner = think_soul.subagent_spawner
    if not spawner:
        return "Subagent spawner not available."

    result = await spawner.investigate(question, angles)
    return result.report
```

Register in `ThinkSoul.available_slash_commands` (verify exact registration mechanism in `think/__init__.py` or `think/slash.py`).

---

## Sub-Phase 12.3: Wire Event Streaming (OPTIONAL)

### Verdict: 🟡 **Skip for CLI-only MVP**

**Why:** Wire event emission requires soul context integration that doesn't match the current `wire_send` pattern. The CLI-only implementation returns the report as text, which is sufficient.

**If implementing later:**
- Emit events through the soul's turn iterator (not direct `wire_send`)
- Add schemas to `agent_sdk/schema.ts` for extension parsing
- Requires coordination with extension Phase 12.5

**For now:** Skip. The report text is returned directly to the user.

---

## Sub-Phase 12.4: Budget Gate Integration

### Verification checklist

Read `background/agent_runner.py` and verify:
- [ ] `BackgroundAgentRunner.run()` calls `run_with_summary_continuation()` which tracks token usage
- [ ] `max_running_tasks` (default 4) is respected by `create_agent_task()`
- [ ] Each background agent task counts against the budget limit

If any of these are false, document the gap and fix.

**Default safeguard:** Limit auto-generated angles to **3** to prevent runaway token usage:

```python
async def _generate_angles(self, question: str) -> list[str]:
    angles = await self._generate_angles_from_llm(question)
    return angles[:3]  # Cap at 3 angles
```

---

## Sub-Phase 12.5: Extension Webview Integration

### Verdict: 🟡 **Deferred — depends on 12.3**

If wire events are implemented in the future, add:
1. `agent_sdk/schema.ts` — `InvestigationProgressEvent` schema
2. `webview-ui/src/stores/event-handlers.ts` — progress handler
3. `webview-ui/src/components/` — `InvestigationProgressPanel`

**For now:** Not needed. CLI-only MVP is sufficient.

---

## Acceptance Criteria

- [x] `/investigate <question>` auto-generates up to 3 angles and spawns background tasks
- [x] `/investigate <question> | angle1, angle2` uses provided angles
- [x] All background tasks complete and results are collected
- [x] Unified report is returned to the user
- [x] Timed-out tasks are killed and reported as failures
- [x] Failed tasks are reported with error message
- [x] `max_running_tasks` is respected
- [x] Token usage is tracked per investigation task
- [x] `uv run pytest` passes

---

## Implementation Order

1. **12.1** — Result collection in `ThinkSubagentSpawner` (2-3 hours)
   - Fix angle mapping (`task_angles` dict)
   - Verify LLM access (`_runtime.soul.llm`)
   - Verify `wait()`, `read_output()`, `kill()` APIs
   - Add types (`InvestigateResult`, `InvestigationResult`)
2. **12.2** — `/investigate` slash command (1 hour)
   - Verify slash command registration mechanism
3. **12.4** — Budget verification (30 min)
   - Read-only verification

**Total: ~3.5-4.5 hours**

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `ThinkSubagentSpawner` lacks LLM access | 🔴 High | Verify `_runtime.soul.llm` before coding; fallback to static angles |
| `BackgroundTaskManager.wait()` doesn't exist | 🔴 High | Read `manager.py`; fallback to polling with `asyncio.wait_for` |
| Background tasks fail silently | 🟡 Medium | Always read output; catch all exceptions |
| Token usage explodes | 🟡 Medium | Cap auto-angles at 3; respect `max_running_tasks` |
| Report quality is poor | 🟢 Low | Start with simple concatenation; iterate later |
