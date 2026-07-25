---
phase_id: phase-04c
title: 4c: Think Subagents & Do Plan Review Gate
status: implemented
dependencies:
  - phase-04b
files_involved:
  - src/consilium/think/subagents.py
  - src/consilium/do/review_gate.py
---

**Status: PLANNED.**

Phase 4c gives Think mode **eyes** (codebase exploration via subagents) and gives Do mode **judgment** (review incoming plans before executing). This closes the loop between reasoning and execution.

---

### 4c.1 Think Mode Subagent Integration

**Problem:** Think mode has mutable history but no tool access. It can reason about what the user says, but it cannot `ReadFile`, `Grep`, or `Shell` to verify assumptions against the actual codebase. It's a brain without hands.

**Solution:** Let Think mode spawn `explore` subagents on demand. Subagents are full `KimiSoul` instances with full tool access. Their findings are injected back into Think's mutable history as evidence.

#### Architecture

```
Think Mode (ThinkSoul)              Subagent (KimiSoul)
--------------------                -------------------
User: "Will asyncio break
       our thread-locals?"
    │
    ├── /explore "Find thread-local usage"
    │       → ForegroundSubagentRunner
    │       → explore subagent with tools
    │       → returns summary text
    │
    ├── /investigate "Compare Kafka vs RabbitMQ"
    │       → BackgroundAgentRunner × 2
    │       → parallel explore subagents
    │       → notifications on completion
    │
    │ ←── Subagent summaries injected
    │     into Think history
    │
Think: "Found 3 thread-local sites.
        Two safe, one risky."
```

#### Subagent API audit (COMPLETED)

**Result: All assumed classes exist.** The subagent API is fully available as standalone imports.

**Verified class locations:**

| Class | File | Status |
|-------|------|--------|
| `SubagentBuilder` | `src/consilium/subagents/builder.py` | ✅ Exists |
| `ForegroundSubagentRunner` | `src/consilium/subagents/runner.py` | ✅ Exists |
| `BackgroundAgentRunner` | `src/consilium/background/agent_runner.py` | ✅ Exists |
| `BackgroundTaskManager` | `src/consilium/background/manager.py` | ✅ Exists |
| `SubagentStore` | `src/consilium/subagents/store.py` | ✅ Exists |
| `ForegroundRunRequest` | `src/consilium/subagents/runner.py` | ✅ Exists |

**Key correction:** `ForegroundRunRequest` field is `requested_type` (not `subagent_type`):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ForegroundRunRequest:
    description: str
    prompt: str
    requested_type: str   # <-- CORRECT field name
    model: str | None
    resume: str | None
```

**Background task entry point:** Background agents are spawned via `BackgroundTaskManager.create_agent_task()`:

```python
from consilium.background.manager import BackgroundTaskManager

view = background_tasks.create_agent_task(
    agent_id=agent_id,
    subagent_type="explore",
    prompt=prompt,
    description=description,
    tool_call_id=tool_call_id,
    model_override=model,
    timeout_s=timeout,
)
```

**"explore" agent spec:** Confirmed at `src/consilium/agents/default/explore.yaml`. Read-only toolset:
- `Shell`, `ReadFile`, `ReadMediaFile`, `Glob`, `Grep`, `SearchWeb`, `FetchURL`
- Excludes: `Agent`, `AskUserQuestion`, `SetTodoList`, `WriteFile`, `StrReplaceFile`

#### New module: `ThinkSubagentSpawner`

**File:** `src/consilium/think/subagent_spawner.py` — new module

```python
"""Thin wrapper for spawning subagents from Think mode.

NOTE: This module must be adapted to the actual subagent API discovered
during the audit (see "Subagent API audit" section above).
"""

class ThinkSubagentSpawner:
    def __init__(self, root_runtime: Runtime):
        self._runtime = root_runtime

    async def explore(
        self,
        prompt: str,
        timeout: int = 300,
        max_tokens: int = 4000,
        max_file_scans: int = 50,
    ) -> str:
        """Foreground deep-dive with hard resource caps.

        Caps prevent runaway exploration, duplicate work, and token budget
        exhaustion on deep research tasks.
        """
        from consilium.subagents.runner import ForegroundSubagentRunner, ForegroundRunRequest

        runner = ForegroundSubagentRunner(self._runtime)
        req = ForegroundRunRequest(
            description="Think explore",
            prompt=prompt,
            requested_type="explore",
            model=None,
            resume=None,
        )
        result = await asyncio.wait_for(runner.run(req), timeout=timeout)
        # Post-hoc truncation check: if subagent exceeded caps, note it
        return result.output  # Subagent's final assistant message text

    async def investigate(
        self,
        question: str,
        angles: list[str],
        max_tokens_per_agent: int = 4000,
        max_file_scans_per_agent: int = 50,
        max_concurrent: int = 3,
    ) -> list[str]:
        """Spawn parallel background subagents, one per angle.

        Hard caps prevent token budget exhaustion when investigating
        multiple angles simultaneously.
        """
        from consilium.subagents.runner import ForegroundSubagentRunner, ForegroundRunRequest
        req = ForegroundRunRequest(
            description="Think explore",
            prompt=prompt,
            requested_type="explore",
            model=None,
            resume=None,
        )
        result = await asyncio.wait_for(runner.run(req), timeout=timeout)
        return result.output  # Subagent's final assistant message text

    async def investigate(self, question: str, angles: list[str]) -> list[str]:
        """Spawn parallel background subagents, one per angle.
        
        NOTE: Background tasks are fire-and-forget with notification delivery.
        Result collection requires polling the background task store or waiting
        for notifications. This is significantly more complex than foreground.
        Consider deferring /investigate until /explore is proven working.
        """
        from consilium.background.manager import BackgroundTaskManager

        views = []
        for angle in angles:
            view = self._runtime.background_tasks.create_agent_task(
                agent_id=f"think-investigate-{uuid.uuid4().hex[:8]}",
                subagent_type="explore",
                prompt=f"{question}\n\nFocus on this angle: {angle}",
                description=f"Investigate: {angle[:40]}",
                tool_call_id="",  # Not spawned from a tool call
                model_override=None,
            )
            views.append(view)

        # TODO: Concrete result collection strategy
        # Option A: Poll view.status until all complete
        # Option B: Subscribe to BackgroundTaskManager notifications
        # Option C: Return view handles to caller, let caller poll
        ...
```

#### ThinkSoul integration

**File:** `src/consilium/think/soul.py` — modifications to `ThinkSoul`

```python
class ThinkSoul:
    def __init__(self, ..., subagent_spawner: ThinkSubagentSpawner | None = None):
        # ... existing ...
        self._spawner = subagent_spawner

    async def run_explore(self, prompt: str) -> str:
        """Spawn a foreground explore subagent and return its summary."""
        if self._spawner is None:
            raise RuntimeError("Subagent spawner not configured")
        return await self._spawner.explore(prompt)

    async def run_investigate(self, question: str, angles: list[str]) -> list[str]:
        """Spawn parallel background subagents and collect summaries."""
        if self._spawner is None:
            raise RuntimeError("Subagent spawner not configured")
        tasks = await self._spawner.investigate(question, angles)
        # Wait for all to complete and collect results
        ...

    async def generate_angles(self, question: str) -> list[str]:
        """Ask the LLM to break a question into investigation angles.
        
        Returns a list like ['security implications', 'performance impact', 'migration path'].
        """
        # Uses kosong.generate() directly with a short prompt
        ...
```

#### New slash commands

**File:** `src/consilium/think/slash.py` — additions

**⚠️ Correction:** Think slash commands receive `(history: HistoryManager, session: ThinkSession, args: str)`, not `(soul: ThinkSoul, args: str)`.

```python
# Think slash commands receive (history, session, args).
# The spawner is stored on ThinkSoul, accessible via a weakref registry
# or by extending the slash command signature.

async def slash_explore(history: HistoryManager, session: ThinkSession, args: str) -> None:
    """/explore <question> — Spawn a foreground explore subagent."""
    if not args.strip():
        print("Usage: /explore <question>")
        return
    print("Exploring... (this may take a moment)")
    # Access spawner via ThinkSoul registry
    soul = _get_think_soul_from_session(session)
    summary = await soul.run_explore(args.strip())
    # Inject as assistant message in Think history
    history.add_message("assistant", f"[Explore result]\n{summary}")
    print(summary)

async def slash_investigate(history: HistoryManager, session: ThinkSession, args: str) -> None:
    """/investigate <question> — Spawn parallel background subagents."""
    if not args.strip():
        print("Usage: /investigate <question>")
        return
    soul = _get_think_soul_from_session(session)
    # Generate angles via LLM (needs implementation on ThinkSoul)
    angles = await soul.generate_angles(args.strip())
    print(f"Investigating {len(angles)} angles in parallel...")
    results = await soul.run_investigate(args.strip(), angles)
    for i, result in enumerate(results):
        history.add_message("assistant", f"[Investigation {i+1}]\n{result}")
    print("All investigations complete. See history for results.")
```

**ThinkSoul registry for slash command access:**

```python
# src/consilium/think/soul_registry.py — new module
import weakref
let's 
_think_souls: dict[str, weakref.ref[ThinkSoul]] = {}

def register_think_soul(session_id: str, soul: ThinkSoul) -> None:
    _think_souls[session_id] = weakref.ref(soul)

def get_think_soul(session_id: str) -> ThinkSoul | None:
    ref = _think_souls.get(session_id)
    return ref() if ref is not None else None

def unregister_think_soul(session_id: str) -> None:
    _think_souls.pop(session_id, None)
```

ThinkSoul registers itself on init and unregisters on cleanup:

```python
class ThinkSoul:
    def __init__(self, session_id: str, ...):
        # ... existing ...
        from consilium.think.soul_registry import register_think_soul
        register_think_soul(session_id, self)
```

Slash commands use the registry:

```python
def _get_think_soul_from_session(session: ThinkSession) -> ThinkSoul:
    from consilium.think.soul_registry import get_think_soul
    soul = get_think_soul(session.id)
    if soul is None:
        raise RuntimeError(f"ThinkSoul not found for session {session.id}")
    return soul
```

**Note on `generate_angles()`:** This method does not exist yet. It uses `kosong.generate()` with a short prompt to break a question into investigation angles. Must be implemented as part of Phase 4c.

#### Config

```toml
[subagents]
enabled = true
timeout_seconds = 300
default_type = "explore"
max_tokens = 4000          # Hard cap per subagent response
max_file_scans = 50        # Max files a subagent may read
max_concurrent = 3         # Max parallel background subagents
max_depth = 2              # Max subagent recursion (subagent spawning subagent)
```

**Note:** `subagents` is a top-level section, not nested under `[think]`. This reflects that subagents are a cross-cutting capability (Think uses them, Do uses them for plan review).

**Cap enforcement:**
- `max_tokens`: Subagent output truncated if exceeded; truncation noted in result
- `max_file_scans`: Enforced by tool policy (read-only tools count accesses)
- `max_concurrent`: BackgroundTaskManager queue limit
- `max_depth`: Prevent recursive subagent explosion (subagent → subagent → subagent)

#### Design decisions

| Decision | Rationale |
|----------|-----------|
| **Thin wrapper, not full KimiSoul port** | ThinkSoul stays lightweight. Only the spawner touches subagent infrastructure. |
| **Foreground = `/explore`, Background = `/investigate`** | Simple mental model: explore goes deep, investigate goes wide. |
| **Results injected as assistant messages** | Natural fit for Think's mutable history. Subagent findings become first-class context. |
| **Subagent type = "explore"** | Reuses existing explore spec (read-only, fast). Must verify spec exists in `src/consilium/agents/`. Can add custom "think_deep" type later. |
| **Audit before implementation** | Subagent API surface is assumed from patterns, not verified. Prevents wasted effort on wrong abstractions. |

---

### 4c.2 Do Mode Plan Review Gate

**Problem:** When Think pushes a plan to Do (via `--seed-from-think` or `/inject`), Do immediately starts executing. If the plan is flawed, Do burns tokens and git history on a bad path.

**Solution:** Do mode spawns a **dedicated review subagent** before executing any tool calls. The review subagent has full read-only tool access (ReadFile, Grep, Shell, etc.) to investigate the codebase and validate the plan. It produces a structured review report. Execution only proceeds after user approval.

#### Why a subagent (not a single turn)

A meaningful plan review must **examine the actual codebase**. A toolless single turn is just an LLM guessing. The review subagent:
- Greps for files/symbols mentioned in the plan
- Reads interfaces to verify assumptions
- Checks for conflicting changes or missing prerequisites
- Runs existing tests to establish baseline

This matches the coding agent's feasibility analysis workflow — and it's exactly what makes the review valuable.

#### Review flow

```
[Think pushes plan to Do]
    ↓
Do seeds context with Think history
    ↓
Do Review Gate (auto-triggered)
    ├─ Spawn foreground subagent: type="plan-reviewer"
    ├─ Subagent investigates codebase with read-only tools
    ├─ Subagent outputs structured review report
    └─ Report parsed into PlanReviewReport
    ↓
User sees report:
    ├─ ✅ Feasible: yes/no
    ├─ ⚠️  Risks: [list]
    ├─ 🔧 Recommendations: [list]
    ├─ ❓ Questions: [list]
    └─ [Approve] [Edit] [Reject]
    ↓
[User approves] → Do proceeds with normal execution
[User edits]    → Modified plan injected, review re-runs
[User rejects]  → Do waits for new instructions
```

#### Externalized agent spec

**File:** `src/consilium/agents/default/plan_reviewer.yaml` — new

```yaml
agent:
  name: "plan-reviewer"
  system_prompt_path: ./plan_review_system.md
  tools:
    - "consilium.tools.read:ReadFile"
    - "consilium.tools.search:Grep"
    - "consilium.tools.search:Glob"
    - "consilium.tools.shell:Shell"
    - "consilium.tools.web:FetchURL"
    - "consilium.tools.web:SearchWeb"
  exclude_tools:
    - "consilium.tools.shell:Bash"
    - "consilium.tools.file:WriteFile"
    - "consilium.tools.file:PatchFile"
    - "consilium.tools.agent:Agent"
    - "consilium.tools.multiagent:Task"
  max_steps_per_turn: 5
```

**File:** `src/consilium/prompts/plan_review_system.md` — new

```markdown
# Plan Review System Prompt

You are a plan reviewer with full read-only tool access. Your job is to investigate the codebase and validate a proposed plan before execution.

## Rules
- Use ReadFile, Grep, Glob, Shell (non-destructive), FetchURL, and SearchWeb to investigate.
- Do NOT write files, patch files, or run destructive commands.
- After investigation, output your review in exactly this format:

Feasible: yes/no
Risks:
- ...
Recommendations:
- ...
Questions:
- ...
Summary: ...

## Investigation strategy
1. Grep for files/symbols mentioned in the plan
2. Read relevant files to verify interfaces and assumptions
3. Check for missing dependencies or prerequisites
4. Verify no conflicting changes exist
```

**File:** `src/consilium/prompts/plan_review_user.md` — template

```markdown
Plan to review:

{{plan_text}}

Current working directory: {{work_dir}}
Git branch: {{git_branch}}
Git status: {{git_status}}
```

#### Implementation

**File:** `src/consilium/do/plan_review.py` — new module

```python
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlanReviewReport:
    feasible: bool
    risks: list[str]
    recommendations: list[str]
    questions: list[str]
    summary: str


class PlanReviewer:
    """Spawns a plan-reviewer subagent to validate plans before execution.
    
    NOTE: Subagent API must be audited before implementation (see §4c.1).
    The runner/spawner below are placeholders for the actual API.
    """

    def __init__(self, root_runtime: Runtime, config: DoConfig):
        self._runtime = root_runtime
        self._config = config

    def _load_system_prompt(self) -> str:
        if self._config.plan_review.system_prompt_path:
            return Path(self._config.plan_review.system_prompt_path).read_text()
        builtin = Path(__file__).parent.parent / "prompts" / "plan_review_system.md"
        return builtin.read_text()

    def _render_user_prompt(self, plan_text: str) -> str:
        template_path = Path(__file__).parent.parent / "prompts" / "plan_review_user.md"
        template = template_path.read_text()
        return (
            template
            .replace("{{plan_text}}", plan_text)
            .replace("{{work_dir}}", str(self._runtime.work_dir))
            .replace("{{git_branch}}", _get_git_branch(self._runtime.work_dir))
            .replace("{{git_status}}", _get_git_status(self._runtime.work_dir))
        )

    async def review(self, plan_text: str) -> PlanReviewReport:
        """Spawn a foreground plan-reviewer subagent and return parsed report."""
        from consilium.subagents.runner import ForegroundSubagentRunner, ForegroundRunRequest

        runner = ForegroundSubagentRunner(self._runtime)
        req = ForegroundRunRequest(
            description="Plan review",
            prompt=self._render_user_prompt(plan_text),
            requested_type="plan-reviewer",
            model=self._config.plan_review.model,
            resume=None,
        )
        result = await asyncio.wait_for(
            runner.run(req),
            timeout=self._config.plan_review.timeout_seconds,
        )
        return self._parse_report(result.output)

    def _parse_report(self, text: str) -> PlanReviewReport:
        """Defensive parsing of structured review text.
        
        Uses regex with sensible defaults if the LLM deviates from the format.
        """
        feasible_match = re.search(r"Feasible:\s*(yes|no)", text, re.IGNORECASE)
        feasible = feasible_match.group(1).lower() == "yes" if feasible_match else False

        risks = self._extract_list(text, "Risks:")
        recommendations = self._extract_list(text, "Recommendations:")
        questions = self._extract_list(text, "Questions:")

        summary_match = re.search(r"Summary:\s*(.+?)(?=\n\n|$)", text, re.DOTALL | re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else text[:500]

        return PlanReviewReport(
            feasible=feasible,
            risks=risks,
            recommendations=recommendations,
            questions=questions,
            summary=summary,
        )

    def _extract_list(self, text: str, header: str) -> list[str]:
        pattern = rf"{re.escape(header)}\s*\n((?:\s*[-*]\s*.+\n?)+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return []
        lines = match.group(1).strip().split("\n")
        return [line.strip().lstrip("-* ").strip() for line in lines if line.strip()]
```

**⚠️ Control flow correction:** The review gate must live in the **execution path**, not `DoSession.start()`.

**File:** `src/consilium/do/session.py` — modifications

```python
class DoSession:
    def __init__(self, ..., config: DoConfig):
        # ... existing ...
        self._seeded_from_think: bool = False  # Set by CLI when --seed-from-think is used
        self._pending_review: PlanReviewReport | None = None

    async def start(self) -> None:
        """Initialize state. Does NOT run execution."""
        # ... existing (git stash, journal init, hooks) ...

    def _extract_plan_from_context(self) -> str:
        """Extract plan text from seeded Think history.
        
        Algorithm: Concatenate all user and assistant messages from the
        seeded context, excluding system messages and tool results.
        """
        messages = []
        for msg in self.soul._context.history:
            if msg.role in ("user", "assistant"):
                text = msg.extract_text() if hasattr(msg, "extract_text") else str(msg.content)
                messages.append(f"[{msg.role}]: {text}")
        return "\n\n".join(messages)

    async def approve_review(self) -> None:
        """Called by /approve slash command or wire approval."""
        if self._state != "awaiting_review":
            raise RuntimeError("No pending review to approve")
        self._state = "running"
        # Continue with execution — the pre-run hook will not fire again
        # because _pending_review is now set

    async def reject_review(self) -> None:
        """Called by /reject slash command or wire rejection."""
        self._state = "idle"
        self._pending_review = None
```

**Pre-run hook on KimiSoul (recommended approach):**

Instead of wrapping `soul.run()` at every call site (shell UI, ACP, wire, print mode), add a hook point inside `KimiSoul.run()`:

```python
# src/consilium/soul/kimisoul.py — additions to KimiSoul

class KimiSoul:
    def __init__(self, ...):
        # ... existing ...
        self._pre_run_hooks: list[Callable[[Message], Awaitable[bool]]] = []

    def register_pre_run_hook(self, hook: Callable[[Message], Awaitable[bool]]) -> None:
        """Register a hook that runs before the first turn.
        
        If the hook returns True, execution is paused. The caller is
        responsible for resuming (e.g., via slash command).
        """
        self._pre_run_hooks.append(hook)

    async def run(self, user_input: Message, ...) -> None:
        # ... existing setup ...

        # Run pre-run hooks before first turn
        for hook in self._pre_run_hooks:
            should_pause = await hook(user_input)
            if should_pause:
                return  # Paused; user will resume via slash command

        # Continue with normal execution
        # ... existing ...
```

**DoSession registers the hook during initialization:**

```python
# src/consilium/do/session.py — in DoSession.__init__() or start()

async def _plan_review_hook(self, user_input: Message) -> bool:
    """Pre-run hook: pause for plan review if seeded from Think."""
    if not self._seeded_from_think:
        return False  # Don't pause
    if not self._config.plan_review.enabled:
        return False  # Don't pause
    if self._pending_review is not None:
        return False  # Already reviewed

    plan_text = self._extract_plan_from_context()
    reviewer = PlanReviewer(self.soul.runtime, self._config)
    self._pending_review = await reviewer.review(plan_text)
    self._state = "awaiting_review"
    await self._emit_plan_review_event(self._pending_review)
    return True  # Pause execution

# Register during DoSession initialization:
self.soul.register_pre_run_hook(self._plan_review_hook)
```

**Why this is better than `run_with_review_gate()`:**
- **Additive, not invasive** — No changes to shell UI, ACP, wire server, or print mode
- **Single point of control** — Hook lives in `KimiSoul.run()`, which every UI mode calls
- **Reversible** — Unregister hook to disable gate; no call site changes needed
- **Composable** — Multiple hooks can be registered (e.g., one for review, one for approval)

**New slash commands for Do mode:**

```python
# src/consilium/soul/slash.py  (Do-mode slash commands)
from consilium.do.registry import get_do_session

async def slash_approve(soul: KimiSoul, args: str) -> None:
    """/approve — Approve pending plan review and proceed with execution."""
    session = get_do_session(soul._runtime.session.id)
    if session is None or session._state != "awaiting_review":
        print("No pending review to approve.")
        return
    await session.approve_review()
    print("Review approved. Proceeding with execution...")
    # IMPORTANT: The caller must re-invoke soul.run() with the same message.
    # The pre-run hook will return False this time (pending_review is set),
    # so execution proceeds normally.
    # In shell mode: the shell loop re-sends the original user message.
    # In wire mode: the extension re-sends the prompt message.

async def slash_reject(soul: KimiSoul, args: str) -> None:
    """/reject — Reject pending plan review and return to idle state."""
    session = get_do_session(soul._runtime.session.id)
    if session is None or session._state != "awaiting_review":
        print("No pending review to reject.")
        return
    await session.reject_review()
    print("Review rejected. Waiting for new instructions.")
```

**Wire event for review report:**

**File:** `src/consilium/wire/types.py` — additions

```python
class PlanReviewEvent(BaseModel):
    type: Literal["plan_review"] = "plan_review"
    session_id: str
    feasible: bool
    risks: list[str]
    recommendations: list[str]
    questions: list[str]
    summary: str

# Add to Event union type
Event = TextPart | ... | ToolFileModifiedEvent | PlanReviewEvent
```

**Note:** Must add `PlanReviewEvent` to the `Event` union and `__all__` in `wire/types.py`.

#### User interaction

In shell mode:
```
[Do Mode] Plan review complete (subagent investigated 7 files):

Feasible: ✅ yes
Risks:
  ⚠️  Plan modifies core/auth.py without tests
  ⚠️  Database migration not mentioned
Recommendations:
  🔧 Add unit tests for new auth flow
  🔧 Include rollback strategy
Questions:
  ❓ Should this be behind a feature flag?

Summary: Plan is sound but needs test coverage and rollback plan.

> /approve    → Proceed with execution
> /edit       → Modify plan text
> /reject     → Discard and wait for new instructions
```

#### Config

```toml
[do]
plan_review_enabled = true
plan_review_timeout_seconds = 300
plan_review_model = null  # Optional: override model for review (e.g., "kimi-for-coding")
plan_review_system_prompt_path = null  # Optional: custom system prompt
```

**File:** `src/consilium/config.py` — additions

```python
class PlanReviewConfig(BaseModel):
    """Nested config for plan review gate."""
    enabled: bool = True
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    model: str | None = None  # Optional model override for review subagent
    system_prompt_path: Path | None = None  # Optional custom system prompt


class DoConfig(BaseModel):
    # ... existing fields ...
    plan_review: PlanReviewConfig = Field(default_factory=PlanReviewConfig)
```

```toml
[do]
# ... existing do config ...

[do.plan_review]
enabled = true
timeout_seconds = 300
model = null
system_prompt_path = null
```

#### Design decisions

| Decision | Rationale |
|----------|-----------|
| **Subagent with read-only tools** | Review must be grounded in actual code. Grep + ReadFile are essential. |
| **Externalized agent spec (YAML)** | Consistent with existing architecture. Review behavior is configurable without code changes. |
| **Externalized prompts** | Users can customize review criteria per-project via `plan_review_system_prompt_path`. |
| **Max 5 steps** | Prevents runaway investigation. Configurable via agent spec. |
| **No git snapshots during review** | Review is purely investigative. No changes to working tree. |
| **No journal recording** | Review is ephemeral. Only the final report matters. |
| **Structured text parsing** | More robust than JSON (LLMs sometimes emit malformed JSON). Simple regex/line parsing. |
| **Wire event for extension** | Extension renders review card with approve/reject buttons. |
| **Configurable model override** | Some users may want a cheaper/faster model for review, or a thinking model for complex plans. |

---

### 4c.3 Combined Think → Do Flow (with 4c features)

```
Think Mode
----------
User: "Refactor auth to use JWT"
    │
    ├── /explore "Find current auth implementation"
    │       → Subagent returns: "Session cookies in core/auth.py, 
    │                             3 middleware files, no JWT anywhere"
    │
    ├── /investigate "JWT libraries vs custom"
    │       → Subagent A: "PyJWT is standard, 2K stars"
    │       → Subagent B: "Custom JWT is 200 lines but risky"
    │
Think synthesizes plan with evidence
    │
User: /push-to-do
    → Export plan + evidence to outbox

Do Mode
-------
--seed-from-think loads plan
    │
Plan Review Gate
    → Analyzes plan against actual codebase
    → Report: "Feasible. Add tests. Use PyJWT."
    │
User: /approve
    │
Do executes with git snapshots + journal
    → ToolFileModifiedEvent streamed to extension
```

---

### 4c.4 Testing Requirements

| Test | File | Description |
|------|------|-------------|
| `test_explore_subagent_returns_summary` | `tests/core/test_think_subagents.py` | `/explore` spawns subagent, injects result |
| `test_investigate_parallel_subagents` | `tests/core/test_think_subagents.py` | `/investigate` spawns N background tasks |
| `test_subagent_result_in_history` | `tests/core/test_think_subagents.py` | Subagent output appears in Think JSONL |
| `test_plan_review_gate_blocks_execution` | `tests/core/test_do_plan_review.py` | Seeded Do session pauses at review |
| `test_plan_review_parses_report` | `tests/core/test_do_plan_review.py` | LLM output parsed into PlanReviewReport |
| `test_plan_review_approve_proceeds` | `tests/core/test_do_plan_review.py` | `/approve` resumes execution |
| `test_plan_review_reject_waits` | `tests/core/test_do_plan_review.py` | `/reject` keeps session idle |
| `test_plan_review_event_emitted` | `tests/core/test_do_plan_review.py` | PlanReviewEvent sent via wire |

---
