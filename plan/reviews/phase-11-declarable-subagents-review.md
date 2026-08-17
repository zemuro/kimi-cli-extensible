# Review: Declarable Project Subagents + Core Vision Subagent

**Status:** 🟢 Implemented, tested, live-verified. No regressions (full suite failures are all pre-existing; count actually dropped 33 → 31).
**Date:** 2026-08-18

## What was built

1. **Auto-discovery of project subagents**: any `*.yaml` in `.consilium/agents/` (except main-agent files `agent.yaml`/`do.yaml`/`think.yaml`/`system.yaml`/`system.md`) becomes an invocable subagent type named after the file stem. Explicit `subagents:` entries and builtin types win on name conflicts.
2. **Core `vision` subagent** (ships with the CLI): uses `qwen/qwen3.7-flash` (1M context, image_in/video_in/thinking) to analyze images/screenshots/diagrams for text-only models. Registered in the builtin default agent + the repo workspace agent. **Hidden when redundant** — if the parent model already supports `image_in`, vision is not registered.
3. **Think-mode support**: `spawn_subagent`'s enum is now dynamic (core 3 + registered custom types), and custom types dispatch through the generic foreground runner.

## Files changed

| File | Change |
|---|---|
| `src/consilium/agentspec.py` | `discover_project_subagent_files()` + `MAIN_AGENT_FILES` |
| `src/consilium/soul/agent.py` | `_parent_has_image_capability()`, `_register_discovered_subagents()`, wired into `load_agent` |
| `src/consilium/app.py` | vision gate in `_register_subagents_from_spec`; workspace discovery |
| `src/consilium/think/__init__.py` | `_make_spawn_subagent_tool(runtime)` + `_spawn_custom_subagent` |
| `src/consilium/agents/default/vision.yaml` (new) | Vision spec (model qwen/qwen3.7-flash, read-only media tools) |
| `src/consilium/agents/default/vision_role.md` (new) | Vision system prompt |
| `src/consilium/agents/default/vision_when_to_use.md` (new) | When-to-use guidance |
| `src/consilium/agents/default/agent.yaml` | Added vision to subagents block |
| `.consilium/agents/agent.yaml` | Added vision reference (repo workspace override) |
| `tests/core/test_declarable_subagents.py` (new) | 9 tests: discovery, exclusion, vision spec, think enum, gating |
| `tests/core/test_agent_spec.py` | Updated snapshot for vision entry |
| `~/.consilium/config.toml` | Added `qwen/qwen3.7-flash` model |

## Verification

- Discovery finds vision in builtin dir + all workspace custom YAMLs, excludes main-agent files.
- Vision registers with model override for text-only parent; skipped for image-capable parent.
- Think tool enum includes custom types dynamically.
- `test_declarable_subagents.py`: 9 passed. Related suites: 68 passed, 7 skipped.
- Full `tests/core`: 1082 passed, 30 failed + 1 error — **all pre-existing** (stash A/B on these files confirmed identical failures without my changes).

## Notes

- The repo's `.consilium/agents/agent.yaml` references vision via `../../src/consilium/agents/default/vision.yaml` — works for this repo, but other projects using the builtin default agent get vision automatically (builtin `default/agent.yaml` lists it).
- `qwen/qwen3.7-flash` config entry will be kept fresh by the existing `refresh_user_api_models` startup refresh.