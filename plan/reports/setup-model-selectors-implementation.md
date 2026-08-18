---
document_type: implementation_report
phase: 10
title: Setup page model selectors — visual (vision subagent) + subagent text model
author: Consilium
completion_date: 2026-08-18
---

# Setup Page Model Selectors — Visual (Vision Subagent) + Subagent Text Model

**Date:** 2026-08-18
**Status:** ✅ Implemented, tested, builds clean, packaging verified.

## Verdict

🟢 **Overall: green.** Both model selectors (Visual Model / Vision Subagent + Subagent Text Model) are implemented, persisted into `~/.consilium/config.toml`, and take real effect in the CLI subagent model resolution. The setup page is renamed to "Provider & Models" and is re-openable from the ⚙ settings menu via a new "API Setup" item. CLI tests (7 new) pass, the full core suite holds its exact pre-existing failure baseline, extension typecheck/build are clean, and the VSIX package contains the new write logic and UI strings.

## Summary

Added two model selectors to the extension's setup page and renamed it from "API Setup" to "Provider & Models". The page is re-openable from the ⚙ settings menu via a new "API Setup" item, so users can return anytime to reassign models. The selectors persist into `~/.consilium/config.toml` and take real effect in the CLI subagent model resolution.

## What Was Built

### Extension repo (`c:\Users\zemuro\Antigravity\kimi_extension_mod`)

1. `webview-ui/src/components/SetupScreen.tsx` — page renamed to "Provider & Models"; subtitle now says users can return anytime to reassign models; two new ModelCombobox selectors: "Visual Model (Vision)" (seeded from `defaultVisualModel`) and "Subagent Text Model" (seeded from `defaultSubagentModel`); submit sends `api.defaultVisualModel` + `api.defaultSubagentModel`.
2. `webview-ui/src/stores/settings.store.ts` — `DEFAULT_EXTENSION_CONFIG` gains `defaultVisualModel`/`defaultSubagentModel`.
3. `webview-ui/src/hooks/useAppInit.ts` — synthetic model augmentation appends the visual model (capabilities `["image_in"]`) and subagent model (capabilities `[]`) to the selector list.
4. `webview-ui/src/components/ActionMenu.tsx` — new "API Setup" menu item under Settings (IconApi) that reopens the setup page via onAuthAction.
5. `shared/types.ts` — `ExtensionConfig` gains `defaultVisualModel`, `defaultSubagentModel`.
6. `src/config/vscode-settings.ts` — getters for `api.defaultVisualModel`/`api.defaultSubagentModel`, included in `getExtensionConfig()`, added to `onSettingsChange` watch list.
7. `package.json` — settings schema entries `consilium.api.defaultVisualModel`, `consilium.api.defaultSubagentModel`.
8. `src/handlers/config.handler.ts` — `updateExtensionSettings` now also writes `saveProviderConfig` entries for the visual + subagent models and calls the new `saveSubagentModelOverrides`.
9. `agent_sdk/config.ts` — new `saveSubagentModelOverrides({ visualModel, subagentModel })` helper (targeted regex): writes `[subagents.overrides.vision] model=` and `[subagents] default_model=`. Critically, it only touches `default_model` INSIDE the `[subagents]` section — the global `default_model` (main session model) is never clobbered.
10. `agent_sdk/index.ts` — exports the new helper + types.

### CLI repo (`c:\Users\zemuro\Antigravity\kimi_cli_mod`)

1. `src/consilium/config.py` — `SubagentOverrideConfig.model` (per-type model override), `SubagentsConfig.default_model` (global subagent default), `ResolvedSubagentConfig.model`.
2. `src/consilium/subagent_config.py` — model resolution with precedence CLI → env → config file.
3. `src/consilium/subagents/builder.py` — `build_builtin_instance` applies the resolution order: launch spec → `[subagents.overrides.<type>].model` → `subagents.default_model` → agent YAML model field.

## Files Changed

| File | Change |
|---|---|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\SetupScreen.tsx` | Renamed page to "Provider & Models"; added Visual Model + Subagent Text Model selectors; submit sends `api.defaultVisualModel` + `api.defaultSubagentModel` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\stores\settings.store.ts` | `DEFAULT_EXTENSION_CONFIG` gains `defaultVisualModel`/`defaultSubagentModel` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\hooks\useAppInit.ts` | Synthetic model augmentation appends visual (`["image_in"]`) + subagent (`[]`) models to the selector list |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\ActionMenu.tsx` | New "API Setup" menu item under Settings (IconApi) reopens setup page via onAuthAction |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\shared\types.ts` | `ExtensionConfig` gains `defaultVisualModel`, `defaultSubagentModel` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\config\vscode-settings.ts` | Getters for `api.defaultVisualModel`/`api.defaultSubagentModel`; included in `getExtensionConfig()`; added to `onSettingsChange` watch list |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\package.json` | Settings schema entries `consilium.api.defaultVisualModel`, `consilium.api.defaultSubagentModel` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\config.handler.ts` | `updateExtensionSettings` writes `saveProviderConfig` entries for visual + subagent models and calls `saveSubagentModelOverrides` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\config.ts` | New `saveSubagentModelOverrides` helper (targeted regex) writing `[subagents.overrides.vision] model=` + `[subagents] default_model=` without clobbering the global `default_model` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\index.ts` | Exports `saveSubagentModelOverrides` + types |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\config.py` | `SubagentOverrideConfig.model`, `SubagentsConfig.default_model`, `ResolvedSubagentConfig.model` |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\subagent_config.py` | Model resolution with precedence CLI → env → config file |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\subagents\builder.py` | `build_builtin_instance` applies resolution order: launch spec → `[subagents.overrides.<type>].model` → `subagents.default_model` → agent YAML model field |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_subagent_model_override.py` | New — 7 tests for subagent model override resolution |

## Tests

- **CLI:** new `tests/core/test_subagent_model_override.py` — 7 tests (per-subagent override wins, no override → None, CLI beats file, env beats file, empty env ignored, builder default fallback, ResolvedSubagentConfig preserves existing fields). All pass.
- **Full core suite:** 30 failed + 1 error (exact pre-existing baseline), **1109 passed** (up from 1102 with the 7 new tests), 7 skipped.
- **Extension:** `npm run typecheck` clean; `webview-ui npm run build` clean (8617 modules).
- **`saveSubagentModelOverrides` behavior** verified via esbuild-bundled node test against temp config.toml: vision override PASS, subagents default_model PASS, coder override preserved PASS, global default_model untouched PASS; idempotent re-write; "no [subagents] section" append path; empty values no-op.
- **CLI config round-trip:** config with `[subagents] default_model` + `[subagents.overrides.vision] model` + corresponding `[models.*]` blocks parses and validates.
- **VSIX** `consilium-win32-x64.vsix` built and verified: `extension/dist/extension.js` contains the `[subagents]`/`subagents.overrides.vision` write logic; `extension/dist/webview.js` contains all new UI strings. (Packaging emits a pre-existing verification warning about `bin/consilium/manifest.json` — the CLI binary is not staged in this checkout; unrelated to this change.)

## Delta from Spec / Notes

- The plan's "per-subagent override wins over agent YAML model field" behavior is implemented in `builder.py` (resolved.model is checked before the effective base model).
- The Visual Model selector is scoped to the vision subagent (`[subagents.overrides.vision]`) per user decision; the `vision.yaml` hardcoded `model:` remains as fallback default.
- The Subagent Text Model is a global `subagents.default_model` applied to any subagent without its own model declaration or launch override.
- Out of scope: per-tab (Think/Do) model routing at runtime; video-only model selector; changing the `_parent_has_image_capability` hide logic.

## Verification Steps

1. CLI: `.venv/Scripts/python.exe -m pytest tests/core/test_subagent_model_override.py -q` → 7 passed.
2. Extension: `npm run typecheck`; `cd webview-ui && npm run build`.
3. Manual: open setup page → pick Visual Model + Subagent Text Model → Connect → verify config.toml has `[subagents.overrides.vision] model=` and `[subagents] default_model=` and `[models."<id>"]` blocks; global `default_model` unchanged; reopen page shows current values.
4. Duplicate-table fix: covered by the new (untracked) repro scripts in the extension repo — `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_provider_dupe.mjs` and `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_handler_flow.mjs` — see the Bugfix section below.

### Bugfix (2026-08-18 19:30): duplicate [providers.user-api] table blocked config parsing

## What happened

After the setup page shipped, a user-submit of the "Connect" form wrote a duplicate provider table into `~/.consilium/config.toml`:
- Log: `Failed to read/parse config.toml: Cannot redefine existing key 'providers,user-api'` (line 126)
- Root cause: `saveProviderConfig` in `agent_sdk/config.ts` searched for the QUOTED header `[providers."user-api"]` with regex `/\[providers\."user-api"\][^\[]*/s`. The user's config.toml (written by an older setup wizard version) contained the BARE header `[providers.user-api]`. The regex missed it → the function APPENDED a second `[providers."user-api"]` table → TOML spec forbids redefining a key → the entire config became unparseable for the extension.
- Second latent bug discovered while reproducing: the section-boundary regex `[^\[]*` stops at the FIRST `[` anywhere, including `[` inside an inline array. Re-saving a model with `capabilities = ["image_in", "thinking", "video_in"]` truncated the match mid-array and left an orphaned `["image_in", ...]` fragment → same TOML parse error class. The visual model (qwen/qwen3.7-flash) is exactly such a model, so re-saving it through the setup page would corrupt the file.

## The fix (commit 26a9640, extension repo)

In `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\config.ts`:
1. Provider section: regex now matches BOTH `[providers.user-api]` and `[providers."user-api"]` (`/\[providers\s*\.\s*(?:"user-api"|user-api)\s*\](?:(?!\n[ \t]*\[)[\s\S])*/g`). A closure counter keeps the FIRST match (canonical quoted block) and drops any stale duplicates, so TOML never sees a redefined key.
2. Section boundaries everywhere (`saveProviderConfig` provider + model, `saveSubagentModelOverrides` vision/subagents/subagentsSection): replaced `[^\[]*` with a negative-lookahead for a NEWLINE + `[` (a real TOML table header) → `(?:(?!\n[ \t]*\[)[\s\S])*`. Inline arrays are no longer misinterpreted as section ends. `subagentsSectionRe` keeps its capturing group for the `default_model` path (and no `/g` flag so `.test()` doesn't advance `lastIndex`).
3. `s` flag dropped, `g` added where replacements iterate all matches.

## Verification

- New repro scripts (kept untracked): `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_provider_dupe.mjs` (minimal: bare provider header → previously DUPLICATE DETECTED: YES, now single canonical block, DUPLICATE DETECTED: no) and `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_handler_flow.mjs` (full handler flow — 4 saveProviderConfig + saveDefaultModel + saveSubagentModelOverrides — against a copy of the user's REAL config.toml: previously produced an unparseable file; now "TOML PARSE: OK — 1 provider(s), models: 6, subagents.default_model correct, vision override correct").
- `tsc --noEmit` clean; `npm run build:extension` rebuilt `dist/extension.js`; confirmed the fixed lookahead regex literal + dedupe closure are present in the minified bundle.
- VSIX re-packaged `c:\Users\zemuro\Antigravity\kimi_extension_mod\consilium-win32-x64.vsix`; verified the packaged `extension/dist/extension.js` contains the fixed regex and dedupe closure.
- User's live `~/.consilium/config.toml` verified healthy (parses OK; 1 provider; 5 models; `subagents.default_model` + vision override intact) — the duplicate was cleaned up by a reload/manual edit before the fix landed; the fix prevents recurrence.

## Files changed

- `c:\Users\zemuro\Antigravity\kimi_extension_mod\agent_sdk\config.ts` (only tracked file changed; commit `26a9640`)
- Diagnostic scripts left untracked (consistent with prior convention): `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_provider_dupe.mjs`, `c:\Users\zemuro\Antigravity\kimi_extension_mod\scripts\repro_handler_flow.mjs`

---

### Bugfix (2026-08-18 20:40): hybrid model 404 fix — image paste with deepseek selected

## What happened

Image paste with the deepseek (text-only) model selected failed with `404 No endpoints found that support image input`.

- **Root cause:** a hybrid `LLMModel` object. The CLI log at `create:490` showed `model='deepseek/deepseek-v4-flash-0731'` with `capabilities={'thinking','video_in','image_in'}` and `display_name='Qwen: Qwen3.7 Flash'` — deepseek's id with qwen's fields. Config on disk was clean (deepseek = text-only `{'thinking'}`, qwen = `{'image_in','video_in','thinking'}`).
- **Chain:** the extension spawns the CLI with `--model <selector model>` AND sets env `CONSILIUM_MODEL_NAME` from the vscode setting `consilium.api.model`. The SetupScreen writes `api.defaultThinkModel`/`api.defaultDoModel` (the selector) but NEVER `api.model` — so `api.model` stayed stale (e.g. qwen when selector=deepseek, or deepseek when selector=qwen). CLI `augment_provider_with_env_vars` (`c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\llm.py:66-94`) unconditionally overwrote `model.model` with `CONSILIUM_MODEL_NAME`, while capabilities/display/max_context stayed from the `--model`-resolved config object → hybrid → image routed to a text-only provider → 404.
- **Reproduced 1:1 in fresh spawns BEFORE fix:** `--model deepseek` + `CONSILIUM_MODEL_NAME=qwen` → `model=qwen max_context=1310720 caps={'thinking'} display='DeepSeek...'` (mirror: model=qwen with deepseek fields). AFTER fix both resolve clean.

## The fix

**CLI** (`c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\llm.py` + `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py`):

1. `augment_provider_with_env_vars(provider, model, *, skip_model_name=False)` — when `True`, `CONSILIUM_MODEL_NAME` no longer overwrites `model.model` (provider/caps/context env overrides still apply).
2. `create` (app.py:465) and `create_think_soul` (app.py:179) pass `skip_model_name=bool(model_name)` — an explicit `--model` always wins over the env var.
3. Both compaction-model paths pass `skip_model_name=True` (config-driven compaction wins).
4. Default (`skip_model_name=False`) preserves env-only fallback behavior (tested).
5. 2 new regression tests in `tests/core/test_create_llm.py`: skip preserves model id; no-skip keeps old behavior.

**Extension** (`c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\config.handler.ts` + `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\SetupScreen.tsx`):

1. `updateExtensionSettings` now syncs `api.model` = doModel when `api.model` is not explicitly provided — a stale `api.model` can no longer persist.
2. `SetupScreen.handleSubmit` also writes `api.model` = doModel so `CONSILIUM_MODEL_NAME` matches the visible selector.

## Verification

- **BEFORE:** `--model deepseek/deepseek-v4-flash-0731` + `CONSILIUM_MODEL_NAME=qwen/qwen3.7-flash` → hybrid at create:490 (20:22 log, `model='qwen' max_context=1310720 caps={'thinking'} display='DeepSeek: DeepSeek V4 Flash 0731'`).
- **AFTER:** same command → clean `model='deepseek/deepseek-v4-flash-0731' max_context=1310720 caps={'thinking'} display='DeepSeek: DeepSeek V4 Flash 0731'` (20:27 log).
- **Mirror:** `--model qwen/qwen3.7-flash` + `CONSILIUM_MODEL_NAME=deepseek` → clean qwen `caps={'thinking','image_in','video_in'}` (20:38 log).
- **CLI tests:** `tests/core/test_create_llm.py` 35 passed (2 new). Full core suite: 1113 passed, 30 failed + 1 error — identical to the pre-existing baseline (30 failed + 1 error, incl. the pre-existing `test_plan_flag` fixture mismatch proven via `git stash`). No new regressions.
- **Extension:** `npx tsc --noEmit` clean (extension + webview). `npm run build` clean. VSIX repackaged `consilium-win32-x64.vsix` 20:34; `api.model` sync verified present in packaged `extension.js` (2 hits) + `webview.js` (1 hit). Installed into `~/.antigravity-ide/extensions/zemuro.consilium-0.5.10-fork.3/dist/`.
- **Current IDE settings:** `api.model` = deepseek/deepseek-v4-flash-0731 (already in sync; no stale value to clean).

## Files changed

- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\llm.py` (`augment_provider_with_env_vars` signature + `skip_model_name`)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py` (4 call sites)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_create_llm.py` (2 new tests)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_plan_flag.py` (monkeypatch lambda → `*a, **k`)
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_startup_progress.py` (2 monkeypatch lambdas → `*a, **k`)
- `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\config.handler.ts` (`api.model` sync)
- `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\SetupScreen.tsx` (`api.model` write)
- VSIX repackaged + installed.

## Delta from spec

- No formal spec existed for this fix; implemented as a root-cause fix with defense in depth on both CLI + extension.
- Deliberately did NOT remove `CONSILIUM_MODEL_NAME` support entirely (env-only setups still need it); the CLI fix makes explicit `--model` authoritative, which is the correct precedence.

**Verdict:** 🟢 Fixed and verified.
