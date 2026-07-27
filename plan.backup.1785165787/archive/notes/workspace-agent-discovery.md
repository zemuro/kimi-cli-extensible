# Workspace-Level Agent Discovery

**Date:** 2026-07-17  
**Author:** Do agent (Consilium development session)  
**Status:** Implemented  
**Scope:** CLI (`consilium_mod`)

## Problem

Custom subagent types (e.g., `translator`, `translation_reviewer`) were only available when the user explicitly launched the CLI with:

```bash
consilium --agent-file .consilium/agents/agent.yaml
```

If Do mode was started without that flag, the workspace override under `.consilium/agents/` was ignored, and the custom subagents were unknown to the `LaborMarket`. This contradicts the expectation that a workspace-level `.consilium/agents/agent.yaml` should be discovered automatically, similar to how `.consilium/AGENTS.md` or project skills are discovered.

## Solution

Added automatic discovery of a workspace-level agent spec file:

```
<work_dir>/.consilium/agents/agent.yaml
```

When this file exists, its subagent registry is loaded automatically; when it does not exist, the CLI falls back to the built-in default agent spec.

### Do mode

`KimiCLI.create()` now checks for a workspace agent file before defaulting to `src/consilium/agents/default/agent.yaml`. If one is found, it is used as the main agent spec, so its `subagents:` block is registered by `load_agent()` exactly like an explicitly passed `--agent-file`.

### Think mode

`create_think_soul()` previously always registered only the built-in subagent types. It now:

1. Registers built-in subagent types from `src/consilium/agents/default/agent.yaml`.
2. Discovers the workspace agent file (if any).
3. Registers workspace subagent types, allowing them to override built-ins with the same name.

The Think-mode `agent_file` parameter continues to control only the custom system prompt, preserving existing behavior.

## Files changed

| File | Change |
|------|--------|
| `src/consilium/agentspec.py` | Added `WORKSPACE_AGENT_FILE` constant and `find_workspace_agent_file(work_dir)` helper. |
| `src/consilium/app.py` | Imported `find_workspace_agent_file`; wired workspace discovery into Do-mode agent loading and Think-mode subagent registration. |

## Verification

1. Syntax-checked changed files with:

   ```bash
   python -m py_compile src/consilium/agentspec.py src/consilium/app.py
   ```

2. To test runtime behavior:
   - Create or enter a workspace with `.consilium/agents/agent.yaml` that defines a custom subagent (e.g., `translator`).
   - Start Do mode **without** `--agent-file`.
   - The custom subagent should now be spawnable via the `Agent` tool.
   - Logs should contain: `Using workspace agent file: ...`

## Notes / future work

- The discovery currently looks only at `<work_dir>/.consilium/agents/agent.yaml`. If nested workspaces or monorepo layouts become common, consider walking from project root to `work_dir` (mirroring `load_agents_md()` logic).
- A workspace agent file is currently expected to be a complete spec (tools + subagents). If users want partial workspace overrides that extend the default, they can use `extend: default` in their `agent.yaml`; the existing `_load_agent_spec()` extension logic handles this.
