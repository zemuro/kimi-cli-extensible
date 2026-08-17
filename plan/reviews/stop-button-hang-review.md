# Stop Button Hang — Fix Review

**Date:** 2026-08-17 (post-unplug, `f1d0df31` + working tree)
**Scope:** Stop-button leaves extension "irresponsive for minutes" until window reload.
**Status:** ✅ REAL-NETWORK VALIDATED — user confirmed stop button "worked pretty immediately" on a long generation.

## 🟢 Verdict: APPROVED — root causes confirmed, fixes implemented, unit-tested, and validated live.

---

## Root Cause Analysis (two independent bugs)

### Bug A — Extension: `stream_aborted` has NO webview handler (CONFIRMED)

- `abortChat` (chat.handler.ts) broadcasts `stream_aborted` **immediately** on stop.
- `event-handlers.ts` `eventHandlers` map had **no `stream_aborted` entry**; `processEvent` silently no-ops unknown types.
- Net effect: the UI never reset `isStreaming` from the abort event itself — only a later terminal `stream_complete`/`error` from the CLI could. When the CLI is wedged (Bug B), the UI stays frozen indefinitely.
- `chat.store.ts` `abort()` also never set `isStreaming = false` — it relied entirely on events.

### Bug B — CLI: cancel-induced connection errors resurrect the turn via recovery-retry (CONFIRMED in code + log evidence)

- `_handle_cancel` sets `_cancel_event` and awaits `force_abort()`, which **closes the HTTP client** (`_close_client_sync`).
- The in-flight SSE stream then raises `httpx.NetworkError`/`RemoteProtocolError` → `convert_httpx_error` → **`APIConnectionError`** (classified retryable).
- `_run_with_connection_recovery` catches `APIConnectionError`, and since the provider implements `RetryableChatProvider`, `on_retryable_error()` (openai_responses.py:193) **always returns True and recreates the client** → the ENTIRE LLM step is re-entered with a fresh call.
- `_cancel_event` is never re-checked mid-retry; tenacity keeps the new call alive until it completes/fails on its own.
- **Log evidence** (`kimi.log` 23:22–23:24): repeated cycles
  `Recovered chat provider during step after APIConnectionError; retrying once.` →
  `Chat provider recovery exhausted for step: APIConnectionError: Connection error.` →
  `Agent step {n} failed: APIConnectionError` — the turn repeatedly restarts for minutes, matching "irresponsive for minutes".

### Design constraints discovered

- The `_aborted` marker must be set **synchronously** (before any await) inside `force_abort`, because `_handle_cancel` runs in a separate dispatch task and the connection error may surface in the soul task a moment later.
- The marker must be **reset per turn** or a past abort would suppress recovery/retry of genuinely transient errors forever.
- Must not break: genuine `APIConnectionError` retries (OpenRouter flakiness), the 401→OAuth-refresh path, compaction retries, or `RunCancelled` semantics.

---

## Changes

### CLI (kimi_cli_mod)

| File | Change |
|---|---|
| `src/consilium/chat_provider_ext.py` | New `_make_force_abort(provider, close_and_recreate)` bound callable; sets `provider._aborted = True` synchronously before scheduling the close/recreate task. |
| `src/consilium/soul/consiliumsoul.py` | `_run_with_connection_recovery`: in `except (APIConnectionError, APITimeoutError)`, if `getattr(chat_provider, "_aborted", False)` → tag exception `_kimi_provider_aborted=True` and `raise` (no recovery). `_is_retryable_error`: if `exception._kimi_provider_aborted` → `False` (no tenacity retry). |
| `src/consilium/wire/server.py` | `_handle_prompt` resets `provider._aborted = False` at the start of every turn (fresh `_cancel_event`). |
| `src/consilium/soul/__init__.py` | `run_soul`: in the cancel branch, after `soul_task.cancel()`/await, if the task completed (not just CancelledError), still raise `RunCancelled` — prevents a cancel-induced `APIConnectionError` from surfacing as CHAT_PROVIDER_ERROR. |

### Extension (kimi-extension-mod)

| File | Change |
|---|---|
| `webview-ui/src/stores/event-handlers.ts` | Added `stream_aborted` handler mirroring `stream_complete`: rollup usage, `isStreaming=false`, `isCompacting=false`, `pendingInput=null`, `clearRequests()`, `finishAllTextItems()`, `markPendingToolsAsCancelled()` when `result.status === "interrupted"`. |
| `webview-ui/src/stores/chat.store.ts` | `abort()` now also sets `isStreaming=false` and `isCompacting=false` synchronously (defense-in-depth if `stream_aborted` is ever delayed/dropped). |

### Tests

- `tests/core/test_chat_provider_ext.py`: `_aborted is True` asserted synchronously after `force_abort()` (both openai-like and anthropic).
- `tests/core/test_kimisoul_retry_recovery.py`: new `AbortedConnectionProvider` + 2 tests:
  - `test_step_aborted_provider_never_recovers_or_retries` (marmerd provider → single attempt, zero recovery)
  - `test_step_aborted_provider_cleared_flag_recovers_normally` (flag cleared → recovery resumes)

---

## Verification

- New tests: 14 passed (retry-recovery + chat_provider_ext).
- Soul/approval/agent-tool/background/frenric: 60 + 30 + 104 passed.
- Wire tests: 2 passed.
- Full `tests/core tests/cli`: failure set **identical** before/after (`git stash` comparison) → 33 pre-existing failures/errors (auth/OAuth/env), 0 new.
- Extension typecheck (webview + root): clean.
- `event-handlers.test.ts` / webview unit tests: removed — tooling (node --test + TS path-alias) can't run webview store tests; behavior validated via typecheck + mirror of existing `stream_complete` handler + CLI unit tests.

## Open risks / next steps

1. ~~Real-network validation still pending~~ ✅ **PASSED 2026-08-17**: user generated a long response, clicked stop, and reported the button "worked pretty immediately" — UI reset instantly and the CLI returned to idle (no minutes-long wedge).
2. `sendCancel()` in protocol.ts has **no timeout** — if the CLI's `_handle_cancel` awaits `force_abort()` and the close hangs, the promise never resolves. Current UI is unblocked (fire-and-forget), but a defensive timeout on pending RPC requests is a reasonable follow-up.
3. The `config.toml.bak-kimi` + stale `~/.consilium/credentials/kimi-code.json` remain for reversibility; dormant.

---
**Reviewer notes:** The fix is two independent layers (CLI must not resurrect; webview must not freeze). Both are minimum-surface, no behavioral change for genuine network retries (the `_aborted` flag is cleared each turn). Approval recommended with the real-network validation step as the gate.