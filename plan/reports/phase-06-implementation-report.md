# Phase 06 Implementation Report: Fix the explore Subagent Type in Think Mode

## Summary

Fixed the root cause of `'Builtin subagent type not found: explore'` errors when spawning subagents from Think mode.

## Root Cause

The `create_think_soul()` function in `src/consilium/app.py` had a **blanket `try/except Exception`** wrapped around the entire subagent registration block (lines 283-292). If ANY subagent spec failed to load (file not found, YAML error, tool import failure, etc.), **ALL subagents were silently dropped** — the `LaborMarket` remained empty, and every `spawn_subagent` call failed.

This is why:
- **Think mode**: Could not spawn `explore`, `plan_editor`, or `investigate` subagents — all failed with "not found"
- **Do mode**: Worked correctly, because it registers subagents through `load_agent()` in `soul/agent.py` which does NOT have this blanket catch

## Changes Made

### 1. `src/consilium/app.py`

**Removed the blanket `try/except`** that was catching ALL registration errors and silently discarding ALL subagents:

```python
# BEFORE (lines 283-292):
try:
    builtin_agent_file = Path(__file__).parent / "agents" / "default" / "agent.yaml"
    _register_subagents_from_spec(builtin_agent_file, "builtin")
    workspace_agent_file = find_workspace_agent_file(Path(session.work_dir))
    if workspace_agent_file is not None:
        _register_subagents_from_spec(workspace_agent_file, "workspace")
except Exception as e:
    from consilium.utils.logging import logger
    logger.warning(f"Failed to load builtin/workspace subagents for Think mode: {e}")

# AFTER:
# Register built-in subagent types.
builtin_agent_file = Path(__file__).parent / "agents" / "default" / "agent.yaml"
_register_subagents_from_spec(builtin_agent_file, "builtin")
# Register workspace-level overrides if they exist.
workspace_agent_file = find_workspace_agent_file(Path(session.work_dir))
if workspace_agent_file is not None:
    _register_subagents_from_spec(workspace_agent_file, "workspace")
```

**Added per-subagent error handling** inside `_register_subagents_from_spec`: each subagent registration is wrapped in its own `try/except`, so one bad subagent (e.g., missing role file) won't prevent others from being registered:

```python
def _register_subagents_from_spec(agent_spec_path: Path, source: str) -> None:
    spec = load_agent_spec(agent_spec_path)
    for subagent_name, subagent_spec in spec.subagents.items():
        try:
            # ... register this subagent ...
        except Exception as e:
            logger.warning(
                "Failed to register {source} subagent type {subagent_name} from {path}: {e}",
                source=source,
                subagent_name=subagent_name,
                path=subagent_spec.path,
                e=e,
            )
```

## Verification

- ✅ **explore** subagent type now registers successfully in Think mode
- ✅ **plan_editor** and **plan** subagent types also register (same fix)
- ✅ One misconfigured subagent no longer blocks all others
- ✅ Registration failures are still logged as warnings for debugging
- ✅ Do mode continues to work unchanged