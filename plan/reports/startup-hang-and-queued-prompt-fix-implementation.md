---
document_type: implementation_report
phase: N/A
title: Startup Hang and Queued Prompt Fix — Implementation Report
author: plan_editor
completion_date: 2026-08-17
---

# Startup Hang and Queued Prompt Fix — Implementation Report

## Executive Summary

Fix for three user-reported issues in the Consilium VS Code extension (`kimi_extension_mod`) and the CLI (`kimi_cli_mod`):

1. **Startup hang** — on window reload / opening a folder, the log showed `Initialized: protocol=1.10` → `Stopping process...` → (hang tens of seconds) → `Process exited with code: 0`. Root cause: `CLIManager.verifyWire()` (`c:\Users\zemuro\Antigravity\kimi_extension_mod\src\managers\cli.manager.ts`) spawned a full `--wire` CLI probe at every webview init to learn slash commands, then immediately stopped it. On Windows the CLI is spawned via a 3-level tree (cmd.exe wrapper → uvx → python); `ProtocolClient.stop()` only killed the cmd.exe wrapper with SIGTERM, leaving the orphaned uvx/python holding the stdio pipe, so the stop "hang" was the pipe drain.

2. **Queued prompts never run** — prompts returned timeouts. Log: `>>> prompt` → (26s gap) → `Parsed config` → `Queued prompt, pending: 1` → `Turn completed, state: idle` in 1ms with no TurnBegin. Root cause: the real session's CLI client was broken/dead (orphaned by the failed probe stop, or uv-cache contention from two concurrent uvx spawns). The turn's `processOne` → `getClientWithConfigCheck` could not cleanly respawn, so the prompt completed silently with no events. Only touching the model selector (which changed `default_model` → `needsRestart` in `getOrCreateSession` → brand-new SessionImpl) healed it.

3. **Model selector fix symptom** — re-selecting the same model forced `needsRestart` because `model !== existing.model` after `saveConfig` wrote a different default.

## Root Causes

- **Startup hang:** the `--wire` probe spawned a full CLI (and on Windows the cmd.exe wrapper only, never the uvx/python children) at every webview init. Stopping it killed only the wrapper; the orphaned children held the stdio pipe open, so `stop()` blocked draining the pipe for tens of seconds.
- **Queued prompts never run:** the probe's orphaned children (or uv-cache contention from two concurrent uvx spawns) left the real session's CLI client dead. `getClientWithConfigCheck` could not cleanly respawn the client, so the turn completed with no events and no TurnBegin — a silent failure.
- **Model selector heal was accidental:** the selector's `saveConfig` wrote a different `default_model`, which tripped `needsRestart` in `getOrCreateSession`, forcing a brand-new SessionImpl (and therefore a fresh client). Re-selecting the same model kept triggering the same `model !== existing.model` path.

## Fixes Implemented

### Extension repo (`c:\Users\zemuro\Antigravity\kimi_extension_mod`)

1. **`agent_sdk/protocol.ts`** — `ProtocolClient.stop()` now kills the whole process tree: SIGTERM, 3s grace, then `taskkill /pid <pid> /T /F` on Windows (new `killProcessTree` private method; POSIX uses negative-pid SIGKILL). Added a post-kill 500ms pipe-drain wait. This eliminates the orphaned uvx/python zombie and the tens-of-seconds stop hang.

2. **`src/managers/cli.manager.ts`** — removed the `verifyWire()` full-CLI wire probe. `verify()` now runs `getInfo()` (`info --json`) and `getSlashCommands()` (`slash-commands --json`) concurrently via `Promise.allSettled`. Slash commands are best-effort (fall back to undefined/empty on failure). Imports changed from `ProtocolClient`/`InitializeResult` to `SlashCommandInfo`.

3. **`agent_sdk/session.ts`** — added `isHealthy()` to the Session interface + SessionImpl (returns `this.client?.isRunning ?? false`); added logging when discarding a non-running client in `getClientWithConfigCheck`.

4. **`src/bridge-handler.ts`** — `getOrCreateSession()` restart check now includes `!existing.isHealthy()` (dead-client health check), so a broken session is recreated deterministically instead of only when the model selector is touched.

5. **`src/handlers/chat.handler.ts`** — after the first turn completes, broadcasts a `slash_commands_updated` StreamEvent with `session.slashCommands` so runtime/skill-derived commands reach the webview menu.

6. **`shared/types.ts`** — added `slash_commands_updated` to the `UIStreamEvent` union.

7. **`webview-ui/src/stores/event-handlers.ts`** — added `slash_commands_updated` handler that calls `useSettingsStore.setWireSlashCommands`.

### CLI repo (`c:\Users\zemuro\Antigravity\kimi_cli_mod`)

1. **`src/consilium/cli/slash_commands.py`** (NEW) — lightweight `slash-commands [--json]` subcommand that reads the static think + soul slash registries without building a soul (avoids the expensive soul/agent/MCP build the old wire probe triggered).

2. **`src/consilium/cli/_lazy_group.py`** — registered `slash-commands` in `lazy_subcommands` + `lazy_command_order`.

## Files Changed

### Extension repo (`c:\Users\zemuro\Antigravity\kimi_extension_mod`)

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\protocol.ts` | Modified — `ProtocolClient.stop()` kills the whole process tree (SIGTERM → 3s grace → `taskkill /T /F` on Windows; negative-pid SIGKILL on POSIX); added 500ms pipe-drain wait |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\managers\cli.manager.ts` | Modified — removed `verifyWire()` full-CLI wire probe; `verify()` uses `getInfo()` + `getSlashCommands()` via `Promise.allSettled`; imports switched to `SlashCommandInfo` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\session.ts` | Modified — added `isHealthy()` to Session interface + SessionImpl; log when discarding non-running client in `getClientWithConfigCheck` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\bridge-handler.ts` | Modified — `getOrCreateSession()` restart check includes `!existing.isHealthy()` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\chat.handler.ts` | Modified — broadcasts `slash_commands_updated` StreamEvent with `session.slashCommands` after first turn |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\shared\types.ts` | Modified — added `slash_commands_updated` to `UIStreamEvent` union |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\stores\event-handlers.ts` | Modified — added `slash_commands_updated` handler → `useSettingsStore.setWireSlashCommands` |

### CLI repo (`c:\Users\zemuro\Antigravity\kimi_cli_mod`)

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\cli\slash_commands.py` | Added (NEW) — lightweight `slash-commands [--json]` subcommand reading static think + soul slash registries (no soul build) |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\cli\_lazy_group.py` | Modified — registered `slash-commands` in `lazy_subcommands` + `lazy_command_order` |

## Verification

| Check | Result |
|-------|--------|
| Extension type check (`npm run typecheck`) | ✅ Passed |
| Webview build (`webview-ui` `npm run build`, vite, 8617 modules) | ✅ Passed |
| Extension bundle (`node esbuild.js --production`) | ✅ Passed |
| Extension package (`npx @vscode/vsce package --no-dependencies`) | ✅ `consilium-0.5.10-fork.3.vsix` (176 files, 3.06 MB) |
| SDK tests (`vitest run tests/session.test.ts tests/protocol.test.ts`) | ✅ 102 passed |
| CLI `slash-commands --json` (`.venv/Scripts/consilium.exe`) | ✅ 29 commands, ~3.4s (uv cold start; no soul build) |
| CLI tests `tests/cli/test_mcp_oauth.py` | ✅ 5 passed |
| CLI tests `tests/wire/` | ✅ 2 passed |
| CLI slash command tests | ✅ 25 passed + 1 pre-existing failure (`tests/core/test_think_slash_split_plan.py::test_splits_monolithic_plan` — verified pre-existing on clean main via `git stash`) |
| Live VS Code window manual check | ⏳ Pending — requires extension reload + rebuild |

## Verdict

🟢 **Green — all automated checks pass; manual UI verification pending.**

All automated checks (typecheck, webview build, esbuild bundle, vsce package, SDK vitest suite, CLI subcommand + test suites) pass. The fix addresses the root causes directly: the `--wire` probe is gone, process-tree kill eliminates the orphaned uvx/python zombies, and the dead-client health check makes broken sessions recreate deterministically. The only outstanding item is a live-window manual verification (extension reload + rebuild), which is required before declaring the user-facing symptoms fully resolved.

## Expected Behavior After Fix (pending live verification)

- No `Stopping process...` hang on reload (probe removed; `stop()` kills the whole tree).
- Prompts run on first try without touching the model selector (dead client detected via `isHealthy()` → deterministic recreate).
- Slash menu populated at init (lightweight `slash-commands --json` probe + `slash_commands_updated` event after first turn).

## Notes

- The user's VS Code has `consilium.executablePath` = `C:\Users\zemuro\Antigravity\kimi_cli_mod\.venv\Scripts\consilium.exe`, so the extension picks up the new `slash-commands` subcommand immediately.
- The extension repo has pre-existing uncommitted changes (project setup wizard, explicit_caching model capability, plan skeleton) from earlier sessions — those were **not** touched by this fix.
- Not yet manually verified in a live VS Code window (requires reload + rebuild).

## Delta from Spec

| Item | Actual Implementation | Notes |
|------|----------------------|-------|
| Eliminate startup hang from `--wire` probe | `verifyWire()` removed; `verify()` uses `getInfo()` + `getSlashCommands()` concurrently (`Promise.allSettled`) | No full CLI spawn at webview init; slash commands best-effort |
| Fix orphaned process tree on Windows | `ProtocolClient.stop()` kills whole tree: SIGTERM → 3s grace → `taskkill /pid <pid> /T /F`; POSIX negative-pid SIGKILL; +500ms pipe drain | No more tens-of-seconds `Stopping process...` hang |
| Fix queued prompts never running | `isHealthy()` on Session + `!existing.isHealthy()` in `getOrCreateSession()` restart check | Dead clients recreated deterministically without touching the model selector |
| Model selector `needsRestart` symptom | Root cause (client death) fixed; `needsRestart` on model change remains as intended behavior | The `saveConfig` default-model write still changes config but no longer needs to be the only heal path |
| Slash menu at init | New `slash-commands --json` CLI subcommand + `slash_commands_updated` event broadcast after first turn | Lightweight; no soul/agent/MCP build |

## Recommendation

Commit the CLI repo changes as `feat(cli): add slash-commands subcommand for lightweight runtime discovery`. The extension repo changes should be committed separately in `kimi_extension_mod`; the pre-existing uncommitted work from earlier sessions should be committed/handled independently.
