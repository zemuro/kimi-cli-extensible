# Subagent Timeout Debug — Translator Subagent

**Date:** 2026-07-18  
**Author:** Do agent  
**Status:** Fixed (pending window reload)

## Problem

The `translator` subagent repeatedly timed out while translating `front_matter` segments. The error was always:

```
Subagent stopped because no progress was detected for 40 consecutive checkpoints (1200s).
```

Observations:
- Simple test translations succeeded.
- Larger translation tasks timed out after the user perceived only 3–5 minutes of work.
- The wire file showed the subagent was **writing incrementally** (many `WriteFile` tool calls), yet the run still died.

## Root causes

### 1. Mandatory two-pass workflow in translator role

`SusanYoung2/.consilium/agents/translator_role.md` required a **mandatory** Pass 1 (draft) followed by a full Pass 2 (readability revision). For segments of even a few hundred words, Pass 2 became a large rewrite that stopped emitting frequent tool calls, causing the adaptive timer to conclude no progress.

### 2. Adaptive timer checkpoint loop spins when deadline passes

In `kimi_cli_mod/src/consilium/subagents/runner.py`, `_checkpoint_loop` computed:

```python
wait_for = min(timer.checkpoint_interval, timer.remaining_wait())
if wait_for > 0:
    await asyncio.sleep(wait_for)
```

When `remaining_wait()` dropped to 0 (because no progress had extended the deadline), the loop stopped sleeping and checkpointed continuously. This made the 40-strike no-progress limit accumulate in seconds rather than the intended ~20 minutes, which matched the user's 3–5 minute experience.

### 3. Per-type timeout override was ignored

`runner.py` created the timer with:

```python
AdaptiveTimer(max_wait=float(self._runtime.config.subagents.timeout_seconds))
```

It did **not** use `resolve_subagent_config(...)`, so `[subagents.overrides.translator].timeout_seconds` was never applied. Only the global timeout mattered.

## Fixes applied

| File | Change |
|------|--------|
| `SusanYoung2/.consilium/agents/translator_role.md` | Replaced mandatory two-pass workflow with a single high-quality pass. Made a second pass optional **only** for very short segments. Added explicit instruction to write incrementally. |
| `kimi_cli_mod/src/consilium/subagents/runner.py` | (a) Uses `resolve_subagent_config(actual_type, ...)` so per-type timeout overrides apply. (b) `_checkpoint_loop` now sleeps at least one `checkpoint_interval` even when the deadline has passed, preventing rapid strike accumulation. |
| `~/.consilium/config.toml` | Raised global `[subagents] timeout_seconds` to `1800` as a fallback; kept per-type overrides for `translator` and `translation_reviewer` at `1800`. |

## Verification

- `python -m py_compile src/consilium/subagents/runner.py` succeeds.
- Affected output file `front_matter_part_c1.ru.md` was found to be complete despite the timeout; the subagent had finished the single pass and was then killed during post-processing/revision.

## Action required

Reload the VS Code: / Consilium window so the updated `translator_role.md` and patched `runner.py` take effect.
