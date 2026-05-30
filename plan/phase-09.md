---
phase_id: phase-09
title: 9: Budget Gate (Subagent Limits)
status: implemented
dependencies:
  - phase-08
files_involved:
  - src/kimi_cli/config.py
  - src/kimi_cli/think/subagents.py
---

**Status: STAGED — ready for implementation.**

**Decision driver:** User requested in `scratch/discussion_features_next.md`.

### Problem

Subagent tasks (explore, plan-review, investigate) are not easily observable by the user. They can spin out of control:
- A subagent might burn 50k tokens on a trivial grep task
- A plan reviewer might make 30 tool calls investigating a simple change
- The user only sees "Plan review in progress..." with no visibility into cost

### Solution

Add token and tool-call budgets **specifically for subagent operations**. The main Think/Do loop is not gated — only subagent spawning is.

#### 9.1 Budget model

```toml
[subagents]
enabled = true
timeout_seconds = 300
default_type = "explore"

[subagents.budget]
max_tokens_per_task = 20_000      # Hard limit per subagent task
max_tool_calls_per_task = 20      # Hard limit per subagent task
warn_tokens_ratio = 0.8           # Warn at 80% of token limit
warn_tool_calls_ratio = 0.8       # Warn at 80% of tool call limit
```

These settings are stored in the external config file (`~/.kimi/config.toml`) alongside all other options.

#### 9.2 Enforcement points

**Token budget:** Add `register_usage_hook(callback: Callable[[TokenUsage], None])` to `KimiSoul`. The hook is called right after the existing `TokenTracker.log()` block in `_step()`. The subagent runner registers a callback that feeds `TokenUsage` into `SubagentBudgetTracker` after each LLM call.

**Tool-call budget:** Hook into `KimiSoul.register_post_tool_hook()`. Count tool calls made by the subagent. If exceeded, stop the turn and return a "Tool call budget exceeded" message.

#### 9.3 User experience

**Warning (informational only):**
- **Foreground subagents:** Emit `SubagentBudgetWarningEvent` on the wire. Parent UI shows it. Subagent continues.
- **Background subagents:** Warning is logged only. User checks task status later.

```
[Budget warning] Subagent "explore-auth-module" has used
16,000 / 20,000 tokens (80%) and 16 / 20 tool calls (80%).
```

**Hard limit (unconditional stop):**
- **Graceful stop:** Current turn completes, no new turns started. Budget notice appended to returned output.
- Never interrupt an in-flight `kosong.step()` call — risk of losing the current turn's output.

```
[Budget exceeded] Subagent "explore-auth-module" stopped:
- Tokens: 20,004 / 20,000 limit
- Tool calls: 20 / 20 limit

Partial results available. Use /explore again with a narrower query,
or increase limits in config: [subagents.budget]
```

#### 9.4 Config management

The user specifically asked to look at how existing options are managed. All config lives in:
- `src/kimi_cli/config.py` — Pydantic models
- `~/.kimi/config.toml` — User-facing TOML file
- Loaded via `load_config()` at app startup

Budget settings should follow the same pattern:
1. Add `SubagentBudgetConfig` to `config.py`
2. Nest it under `SubagentsConfig`
3. Document in the config TOML comments

### Implementation

#### 9.1 Config additions

In `src/kimi_cli/config.py`, add to `SubagentsConfig`:

```python
class SubagentBudgetConfig(BaseModel):
    max_tokens_per_task: int = Field(default=20_000, ge=1_000)
    max_tool_calls_per_task: int = Field(default=20, ge=1)
    warn_tokens_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    warn_tool_calls_ratio: float = Field(default=0.8, ge=0.1, le=1.0)

class SubagentsConfig(BaseModel):
    enabled: bool = Field(default=True)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    default_type: str = Field(default="explore")
    budget: SubagentBudgetConfig = Field(default_factory=SubagentBudgetConfig)
```

#### 9.2 KimiSoul usage hook

In `src/kimi_cli/soul/kimisoul.py`, add to `KimiSoul`:

```python
def register_usage_hook(self, callback: Callable[[TokenUsage], None]) -> None:
    """Register a callback that receives TokenUsage after each step."""
    self._usage_hooks.append(callback)
```

Call all registered hooks immediately after `TokenTracker.log()` in `_step()`:

```python
# Inside _step(), after TokenTracker.log()
for hook in self._usage_hooks:
    try:
        hook(usage)
    except Exception:
        logger.exception("Usage hook failed")
```

#### 9.3 Budget tracker

Create `src/kimi_cli/subagents/budget_tracker.py`:

```python
class BudgetStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"

class SubagentBudgetTracker:
    def __init__(self, config: SubagentBudgetConfig, task_name: str = ""):
        self._config = config
        self._task_name = task_name
        self._tokens_burned = 0
        self._tool_calls_made = 0
        self._warned_tokens = False
        self._warned_tools = False
        self._exceeded = False

    def record_turn(self, token_count: int) -> BudgetStatus:
        self._tokens_burned += token_count
        return self._check()

    def record_tool_call(self) -> BudgetStatus:
        self._tool_calls_made += 1
        return self._check()

    def _check(self) -> BudgetStatus:
        if self._exceeded:
            return BudgetStatus.EXCEEDED

        max_tokens = self._config.max_tokens_per_task
        max_tools = self._config.max_tool_calls_per_task

        if self._tokens_burned >= max_tokens or self._tool_calls_made >= max_tools:
            self._exceeded = True
            return BudgetStatus.EXCEEDED

        warn_tokens = int(max_tokens * self._config.warn_tokens_ratio)
        warn_tools = int(max_tools * self._config.warn_tool_calls_ratio)

        token_warn = self._tokens_burned >= warn_tokens and not self._warned_tokens
        tool_warn = self._tool_calls_made >= warn_tools and not self._warned_tools

        if token_warn or tool_warn:
            if token_warn:
                self._warned_tokens = True
            if tool_warn:
                self._warned_tools = True
            return BudgetStatus.WARNING

        return BudgetStatus.OK

    @property
    def exceeded(self) -> bool:
        return self._exceeded
```

#### 9.4 Wire event for foreground warnings

In `src/kimi_cli/wire/types.py`, add:

```python
class SubagentBudgetWarningEvent(BaseModel):
    type: Literal["subagent_budget_warning"] = "subagent_budget_warning"
    task_name: str
    tokens_burned: int
    tokens_limit: int
    tool_calls_made: int
    tool_calls_limit: int
```

#### 9.5 Integration with foreground subagent runner

In `src/kimi_cli/subagents/runner.py` (`ForegroundSubagentRunner.run()`):

```python
async def run(self, req: ForegroundRunRequest) -> SubagentRunResult:
    config = self._runtime.config.subagents.budget
    tracker = SubagentBudgetTracker(config, task_name=req.description)

    soul = self.prepare_soul(...)

    # Register hooks on the subagent's KimiSoul
    soul.register_post_tool_hook(lambda tc, tr: tracker.record_tool_call())
    soul.register_usage_hook(lambda usage: tracker.record_turn(usage.total_tokens))

    # Run with budget-aware loop
    result = await self._run_with_budget(soul, tracker, req)
    return result

async def _run_with_budget(self, soul, tracker, req):
    # Use existing run_with_summary_continuation() but check budget between turns
    while not tracker.exceeded:
        # ... existing turn logic ...
        if tracker.exceeded:
            break
    # Append budget notice to output if exceeded
```

#### 9.6 Integration with background agent runner

In `src/kimi_cli/background/agent_runner.py` (`BackgroundAgentRunner._run_core()`):

Apply the same pattern as 9.5:
1. Create `SubagentBudgetTracker` before `prepare_soul()`
2. Register usage hook and post-tool hook on the subagent soul
3. Check `tracker.exceeded` between turns
4. If exceeded, gracefully stop and log budget notice

### Testing Requirements

| Test | Description |
|------|-------------|
| `test_budget_tracker_warns_at_80_percent` | Warning returned at threshold |
| `test_budget_tracker_warns_once` | Same threshold does not warn twice |
| `test_budget_tracker_stops_at_100_percent` | Exceeded returned at limit |
| `test_budget_tracker_exceeded_sticky` | Once exceeded, stays exceeded |
| `test_subagent_runner_respects_token_budget` | Foreground subagent stops when token limit hit |
| `test_subagent_runner_respects_tool_budget` | Foreground subagent stops when tool limit hit |
| `test_background_runner_respects_budget` | Background subagent stops when limit hit |
| `test_budget_config_validates` | Pydantic rejects invalid ratios |
| `test_main_loop_not_gated` | Main Think/Do loop unaffected by subagent budgets |
| `test_usage_hook_called_after_step` | `register_usage_hook` callback fires with TokenUsage |

**Estimated effort:** 2-3 days.

---
