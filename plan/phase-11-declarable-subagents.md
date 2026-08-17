## Implementation summary (done)

- `agentspec.py`: `discover_project_subagent_files()` + `MAIN_AGENT_FILES`.
- `soul/agent.py`: `_parent_has_image_capability()`, `_register_discovered_subagents()`; wired into `load_agent` (explicit subagents loop + vision gate + discovery after).
- `app.py`: vision gate in `_register_subagents_from_spec`; discovery call for workspace `.consilium/agents/`.
- `think/__init__.py`: `_make_spawn_subagent_tool(runtime)` replaces static `_SPAWN_SUBAGENT_TOOL` (dynamic enum incl. registered custom types); dispatch handles custom types via `_spawn_custom_subagent` → `ThinkSubagentSpawner.spawn`.
- New core files: `src/consilium/agents/default/vision.yaml`, `vision_role.md`, `vision_when_to_use.md`; registered in builtin `default/agent.yaml` + workspace `.consilium/agents/agent.yaml`.
- User config: added `qwen/qwen3.7-flash` (1M ctx, image_in/video_in/thinking) to `~/.consilium/config.toml`.
- Tests: `tests/core/test_declarable_subagents.py` (9 tests) + updated `test_agent_spec.py` snapshot.

Full core suite: 1082 passed, 30 failed + 1 error — all failures pre-existing (verified via stash A/B; baseline was 33, now 31).

---
document_type: plan
title: Declarable Project Subagents + Core Vision Subagent
created: 2026-08-18
status: implemented
---

# Plan: Declarable Project Subagents + Core Vision Subagent

## Goal (per user direction)

1. **Auto-discovery**: any `.yaml` in the project `.consilium/agents/` folder (except main-agent files: `agent.yaml`, `do.yaml`, `think.yaml`) becomes an invocable subagent type. Project-specific subagents like a custom translator are declared simply by dropping a YAML file in the override folder.
2. **Core vision subagent**: shipped with the CLI (`src/consilium/agents/default/vision.yaml`), registered as a builtin type, **conditionally available** when the parent model is text-only (no `image_in` capability) — it provides image analysis using a vision model (`qwen/qwen3.7-flash`), so text-only Think/Do agents can still "see".

## Design

### A. Core vision subagent (builtin)

New files under `src/consilium/agents/default/`:
- `vision.yaml` — spec: `extend: ./agent.yaml`, `model: "qwen/qwen3.7-flash"`, allowed_tools = [ReadMediaFile, ReadFile, Glob, Grep], exclude_tools = [Agent, Shell, AskUserQuestion, Todo, ExitPlanMode, EnterPlanMode, WriteFile, StrReplaceFile, SearchWeb, FetchURL, TaskList, TaskOutput, TaskStop].
- `vision_role.md` — system prompt for image analysis.
- `vision_when_to_use.md` — "Use when the user asks to analyze/describe an image, screenshot, diagram, or when visual context is needed."

Register in `src/consilium/agents/default/agent.yaml` under `subagents:`, **but with conditional availability**:

The builtin `agent.yaml` `subagents` block is static YAML — it can't express "only when parent is text-only". Two options:
- **Option 1 (registration-time gate)**: register vision always, but in the `Agent` tool description / `when_to_use`, add a note. Actually the simplest robust gate: register it always, but the **parent's `when_to_use`** for the agent already makes the model decide. However the user explicitly wants it available "when it has text-only modality".
- **Option 2 (runtime gate, recommended)**: register vision as a builtin type unconditionally, but `LaborMarket.add_builtin_type` for vision is skipped when `runtime.llm.capabilities` includes `image_in` (parent already sees images → vision subagent redundant). Implement in the registration loops (`load_agent` in soul/agent.py + `_register_subagents_from_spec` in app.py): `if runtime.llm and "image_in" in runtime.llm.capabilities: skip vision`.

### B. Auto-discovery of project subagent YAMLs

New helper in `agentspec.py`:

```python
MAIN_AGENT_FILES = {"agent.yaml", "do.yaml", "think.yaml", "system.yaml"}

def discover_project_subagent_files(agent_dir: Path) -> dict[str, Path]:
    """Scan agent_dir for *.yaml that are not main-agent files and not
    already referenced by explicit subagents: blocks. Returns {name: path}."""
    result: dict[str, Path] = {}
    if not agent_dir.is_dir():
        return result
    for path in sorted(agent_dir.glob("*.yaml")):
        if path.name in MAIN_AGENT_FILES:
            continue
        if path.name in ("coder.yaml", "explore.yaml", "plan.yaml",
                         "plan_editor.yaml", "plan_reviewer.yaml",
                         "vision.yaml", "translator.yaml", "translation_reviewer.yaml"):
            # Builtin-provided names: only override if project file differs from builtin
            # (handled by explicit subagents: block); auto-discovery covers NEW names.
            continue
        result[path.stem] = path
    return result
```

Hmm — but the user wants translator etc. as project-specific too. Reconsider: the workspace `agent.yaml` already declares translator/translation_reviewer explicitly. Auto-discovery should pick up **anything not already registered by an explicit block or builtin**. Cleaner rule: auto-discover every `*.yaml` except the main-agent files; then in registration, **skip names already registered** (explicit/builtin win). That way a project `vision.yaml` could override the core one, and new names (custom ones) get picked up.

### C. Registration integration

Both registration sites get a shared helper (to avoid duplication):

```python
def _register_discovered_subagents(runtime, agent_dir, *, source) -> None:
    from consilium.agentspec import discover_project_subagent_files
    discovered = discover_project_subagent_files(agent_dir)
    for name, path in discovered.items():
        if runtime.labor_market.has_builtin_type(name):
            continue  # explicit/builtin wins
        try:
            spec = load_agent_spec(path)
            ... add_builtin_type(name=name, agent_file=path, ...)
        except Exception as e:
            logger.warning(...)
```

- `soul/agent.py` `load_agent`: after the explicit `subagents` loop, scan the agent file's parent dir (`agent_file.parent`).
- `app.py` `_register_subagents_from_spec` call sites: after registering builtin + workspace, scan `.consilium/agents/` of the work dir (`session.work_dir`).

### D. Vision gating (text-only parent)

In the explicit-subagents registration loop (both sites), skip `vision` when the parent model already has `image_in`:

```python
def _is_vision_redundant(runtime, name) -> bool:
    return name == "vision" and bool(runtime.llm) and "image_in" in runtime.llm.capabilities
```

For auto-discovered files, no special-casing (project files are user's choice).

### E. Think-mode support

`think/__init__.py`:
1. `_SPAWN_SUBAGENT_TOOL` enum → dynamic (base 3 + registered custom types). Tool definition is module-level; change to a function `_make_spawn_subagent_tool(runtime)` or compute at ThinkSoul init.
2. Dispatch (`483-496`) → generic: look up type in `LaborMarket`, run via `ForegroundSubagentRunner` (share `run_explore`'s runner path). Refactor `run_explore`/`run_plan_edit` to use the generic runner with the requested type.

### F. Model entry

`~/.consilium/config.toml`:
```toml
[models."qwen/qwen3.7-flash"]
provider = "user-api"
model = "qwen/qwen3.7-flash"
max_context_size = 1000000
capabilities = ["image_in", "video_in", "thinking"]
display_name = "Qwen: Qwen3.7 Flash"
```

The `refresh_user_api_models` (from the previous commit) will keep its params fresh automatically.

## Files to change

| File | Change |
|---|---|
| `src/consilium/agentspec.py` | `discover_project_subagent_files()` + `MAIN_AGENT_FILES` |
| `src/consilium/soul/agent.py` | Register discovered subagents from agent_file.parent; vision gate |
| `src/consilium/app.py` | Register discovered subagents from work_dir `.consilium/agents/`; vision gate |
| `src/consilium/think/__init__.py` | Dynamic enum + generic dispatch |
| `src/consilium/agents/default/vision.yaml` (new) | Core vision spec |
| `src/consilium/agents/default/vision_role.md` (new) | Vision system prompt |
| `src/consilium/agents/default/vision_when_to_use.md` (new) | When-to-use |
| `src/consilium/agents/default/agent.yaml` | Add vision to subagents block |
| `~/.consilium/config.toml` | Add `qwen/qwen3.7-flash` model |

## Tests

- `discover_project_subagent_files`: finds custom yamls, excludes agent/do/think/system.yaml, sorts deterministically.
- Registration: discovered file → builtin type; explicit/builtin name wins; vision skipped when parent has image_in.
- Think `spawn_subagent`: custom type accepted, generic dispatch works.
- Vision pathway: ReadMediaFile not skipped for vision subagent (image_in model); parent text-only still skips it.

## Open questions

1. Should `qwen/qwen3.7-flash` be added to the config as part of this, or should the user add it via the extension UI? (Plan assumes adding it directly.)
2. Should the vision subagent be available in the `Agent` tool description even when gated (so the model knows it exists but shouldn't use it), or fully hidden? (Recommend: hidden when redundant, to avoid confusing the model.)