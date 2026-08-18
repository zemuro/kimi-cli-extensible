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