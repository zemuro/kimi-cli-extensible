---
phase_id: phase-01
title: 1: Token Tracker
status: implemented
dependencies:
  []
files_involved:
  - src/consilium/token_tracker.py
---

**Goal:** Global token usage logging and a `/token-usage` slash command.

### Why This Is First

The infrastructure already exists:
- Every `kosong.step()` returns `StepResult` with `result.usage: TokenUsage | None`
- `KimiSoul._turn()` already captures this in `soul/kimisoul.py:1135`
- We only need to **persist** it and **expose** it via a slash command

### Data Model

```python
# src/consilium/token_tracker.py
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass(slots=True)
class TokenLogEntry:
    timestamp: datetime
    session_id: str
    turn_id: str
    model: str
    tokens_in: int
    tokens_out: int
    active_context: int  # tokens in current message array

class TokenTracker:
    """Append-only CSV logger for token usage across all sessions."""

    CSV_HEADER = "timestamp,session_id,turn_id,model,tokens_in,tokens_out,active_context\n"
    LOG_DIR: Path = Path.home() / ".consilium" / "token_log"

    def __init__(self) -> None:
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._current_file = self.LOG_DIR / f"{datetime.now():%Y-%m-%d}.csv"
        if not self._current_file.exists():
            self._current_file.write_text(self.CSV_HEADER, encoding="utf-8")

    def log(self, entry: TokenLogEntry) -> None:
        """Append a single entry to today's CSV. Thread-safe via atomic write."""
        ...

    def get_session_summary(self, session_id: str) -> dict:
        """Return aggregated stats for a session:
        - burned_tokens (sum of all tokens_in + tokens_out)
        - active_context_max
        - model_breakdown: dict[model, tokens]
        """
        ...

    def get_global_summary(self, since: datetime | None = None) -> dict:
        """Return global aggregated stats across all sessions."""
        ...
```

### Implementation Steps

#### Step 1.1: Create `src/consilium/token_tracker.py`

- Implement `TokenLogEntry` dataclass
- Implement `TokenTracker` with CSV append logic
- Use `fcntl` (Unix) or `msvcrt` (Windows) for file locking if concurrent access is a concern, OR simply open-append-close per write (simpler, sufficient for single-user CLI)
- Method `log()` should format as CSV line and append
- Method `get_session_summary()` should read all CSV files in `LOG_DIR`, filter by `session_id`, aggregate

#### Step 1.2: Hook into `KimiSoul._turn()`

**File:** `src/consilium/soul/kimisoul.py`

Locate the section after `_kosong_step_with_retry()` returns (around line 1119). The code already captures:
```python
result = await _kosong_step_with_retry()
usage = result.usage
```

After this block, add:
```python
if usage and self._runtime.llm:
    from consilium.token_tracker import TokenLogEntry, TokenTracker
    tracker = TokenTracker()
    tracker.log(TokenLogEntry(
        timestamp=datetime.now(timezone.utc),
        session_id=self._runtime.session.id,
        turn_id=str(self._current_turn_id),  # or result.id
        model=self._runtime.llm.model_name,
        tokens_in=usage.input,
        tokens_out=usage.output,
        active_context=self._context.token_count,
    ))
```

**Important:** Use `self._context.token_count` for `active_context`. This property already exists on the context manager.

#### Step 1.3: Add `/token-usage` slash command

**File:** `src/consilium/ui/shell/slash.py`

Register a new slash command handler:
```python
@slash_command("/token-usage")
async def slash_token_usage(soul: KimiSoul, args: str) -> None:
    """Show token usage summary for the current session."""
    from consilium.token_tracker import TokenTracker
    tracker = TokenTracker()
    summary = tracker.get_session_summary(soul._runtime.session.id)
    # Format and print summary via soul's output channel
```

The soul object has access to `soul._runtime.session.id` for the current session ID. Use the existing output methods (look at how `/model` or `/compact` commands print) to display formatted output.

#### Step 1.4: Add `--budget-tokens` CLI flag

**File:** `src/consilium/cli/__init__.py`

Add after the existing `--max-tokens` flag:
```python
budget_tokens: Annotated[
    int | None,
    typer.Option(
        "--budget-tokens",
        help="Maximum tokens budget for this session. Warns at 80%, stops at 100%.",
    ),
] = None,
```

Pass through to `KimiCLI.create()` in the `instance = await KimiCLI.create(...)` call.

**File:** `src/consilium/app.py`

Add `budget_tokens: int | None = None` to `KimiCLI.create()` signature. Store on the `KimiCLI` instance or `Runtime` config.

**File:** `src/consilium/soul/kimisoul.py`

In `_turn()`, before calling the LLM, check if budget is exceeded:
```python
if self._runtime.config.budget_tokens:
    tracker = TokenTracker()
    summary = tracker.get_session_summary(self._runtime.session.id)
    burned = summary["burned_tokens"]
    if burned >= self._runtime.config.budget_tokens:
        raise BudgetExceededError(f"Token budget exceeded: {burned} / {self._runtime.config.budget_tokens}")
    elif burned >= self._runtime.config.budget_tokens * 0.8:
        # Emit warning via UI
        await self._emit_budget_warning(burned, self._runtime.config.budget_tokens)
```

### Testing Requirements

- `test_token_tracker_log_appends_to_csv()` — verify CSV file is created and entry is appended
- `test_token_tracker_session_summary_aggregates_correctly()` — multiple entries, correct sums
- `test_token_tracker_budget_warning_at_80_percent()` — mock burned tokens, verify warning
- `test_token_tracker_budget_stop_at_100_percent()` — verify exception raised

---
