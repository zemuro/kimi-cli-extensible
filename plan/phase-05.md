---
phase_id: phase-05
title: 5: VS Code: Extension — Dual-Tab UI
status: pending
dependencies:
  - phase-04d
files_involved:
  []
---

**Status: DEFERRED to future extension work.**

The extension-side work (dual-tab UI, inline diffs, push service) requires a separate TypeScript development cycle in the `kimi extension_mod` repo. The CLI backend built in Phase 4a provides everything the extension needs:

- Think mode with Python execution (`run_python` tool)
- Think → Do bridge (`/push-to-do`, `--seed-from-think`, `/inject`)
- Do mode with change journal and `ToolFileModifiedEvent` wire events

When extension development resumes, see `scratch/frontend/inline_diff_implementation_plan.md` for the inline diff specification, and the original Phase 5 section in git history for the dual-tab architecture.

---

### 5.1 Instant Cancellation (Stop Button)

**Upstream status:** Issue filed on `MoonshotAI/kimi-cli`. Awaiting maintainer response.

**Fork status:** Implemented in §4.8 via `force_abort()` — a fork-specific enhancement that closes the provider's HTTP client on wire `cancel` for instant stream termination. See §4.8 for full implementation details.

**Problem:** The stock Kimi CLI uses Python asyncio cooperative cancellation (`asyncio.Task.cancel()`). When the user presses the stop button, the cancel signal is only processed at the next `await` boundary. If the LLM is in "analysis paralysis" generating thinking tokens, the next chunk may not arrive for minutes.

**Root cause:** `kosong.generate()` consumes the entire HTTP stream internally before returning. There is no live stream handle exposed for external closure.

**Why Antigravity is instant:** Uses `AbortController` / `AbortSignal` propagated to the HTTP fetch layer. When `.abort()` is called, the browser/runtime immediately closes the TCP connection.

**Why our fork fix works:** Rather than modifying kosong, we close the provider's HTTP client from `_handle_cancel()`. The in-flight request immediately aborts with `httpx.HTTPError`, the provider re-raises as `ChatProviderError`, and the exception propagates through kosong's existing error-handling path. The client is replaced with a fresh one, so future turns are unaffected.

**Path forward (upstream):** Add abort signal support to kosong (`generate()` accepts an abort event, checks it during `async for part in stream:`). When upstream implements this, our fork can remove the `force_abort()` monkey-patch — the `hasattr` gate in `_handle_cancel()` makes the transition trivial.

---

## Upstream Compatibility Checklist

When implementing each phase, verify:

- [ ] Existing tests still pass (`make test`)
- [ ] `kimi --do` still opens upstream agent REPL unchanged
- [ ] `kimi` (Think mode) still works without Do mode
- [ ] Session v1 format untouched (upstream resume works)
- [ ] `system_prompt_overrides` still works
- [ ] `GenerationConfig` + CLI flags still work
- [ ] No changes to `kosong` library (keep it reusable)
- [ ] KimiSoul hook mechanism is additive only (doesn't break upstream)
- [ ] Extension's existing single-session mode still works

---

## Open Questions for Future Resolution

1. **Pre-edit baseline capture:** RESOLVED in Phase 3.

2. **Binary files:** RESOLVED in Phase 4b.

3. **Journal retention:** RESOLVED in Phase 4b.

4. **Concurrent sessions:** If multiple Do sessions run concurrently, their git stashes may conflict. This is unlikely for a single-user CLI but worth documenting.

5. **Think Python sandbox on Windows:** `sandboxed` level falls back to `restricted` on non-macOS. A Windows-specific sandbox (Job Object, AppContainer) could be added later.

6. **Do mode resumption after push:** If Do was idle when Think pushes, it starts executing immediately. Should there be a user confirmation step? (Configurable via `kimi.do.autoExecuteOnPush` setting.)

---
