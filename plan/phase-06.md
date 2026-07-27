---
document_type: phase_spec
phase: 06
title: Fix the explore Subagent Type in Think Mode
status: implemented
created: 2025-07-26
author: Consilium
dependencies:
  - Phase 04 (Subagent system)
  - Phase 05 (Agent spec loading)
acceptance_criteria_summary:
  - explore subagent type registers successfully in Think mode
  - plan_editor and plan subagent types also register in Think mode
  - One misconfigured subagent does not block others from registering
  - Registration failures are logged as warnings for debugging
  - Do mode subagent registration continues to work unchanged
---

# Phase 06: Fix the explore Subagent Type in Think Mode

## Summary

Fixed the root cause of `'Builtin subagent type not found: explore'` errors when spawning subagents from Think mode. The issue was a blanket `try/except Exception` in `create_think_soul()` that silently discarded ALL subagent registrations if any single one failed.

## 1. Overview

### 1.1 Problem Statement

When running in Think mode, spawning any subagent (e.g., `explore`, `plan_editor`, `plan`, `plan_reviewer`) resulted in the error:

```
KeyError("Builtin subagent type not found: explore")
```

This made Think mode completely unable to use subagents, which blocked all investigation, planning, and review workflows. Do mode was unaffected.

### 1.2 Goal

- All builtin subagent types registered in Think mode are available for spawning.
- A single misconfigured or missing subagent spec does not silently prevent all other subagents from being registered.
- Registration failures are logged with sufficient detail to diagnose the root cause.
- Do mode subagent registration remains unchanged.

### 1.3 Scope Boundaries

**In scope:**
- `create_think_soul()` in `src/consilium/app.py`
- The `_register_subagents_from_spec()` helper function
- Error handling around subagent registration in Think mode

**Out of scope:**
- Do mode subagent registration (works correctly)
- Changes to the subagent loading/registration logic in `soul/agent.py`
- Changes to individual subagent spec files or role prompts
- The `create_think_soul()` function's other responsibilities

## 2. Architecture

The subagent registration flow in `create_think_soul()`:

1. Load a builtin agent spec YAML (`agents/default/agent.yaml`).
2. Iterate over its `subagents` entries and register each one with the `LaborMarket`.
3. If a workspace agent spec exists, repeat the process for workspace-level overrides.
4. The `LaborMarket` is then used by the `Agent` tool to spawn subagents by type name.

The bug was that steps 1-3 were wrapped in a single `try/except Exception`. If any step failed, all registrations were discarded.

## 3. Detailed Design

### Task 0: Remove the blanket try/except in `create_think_soul()`

**Effort:** 1 hour

**Files:**
- `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\app.py`

**Description:**
Remove the catch-all `try/except Exception` block around the subagent registration calls in `create_think_soul()`. Move error handling inside the registration loop so each subagent is registered independently.

**Before (lines 283-292):**
```python
try:
    builtin_agent_file = Path(__file__).parent / "agents" / "default" / "agent.yaml"
    _register_subagents_from_spec(builtin_agent_file, "builtin")
    workspace_agent_file = find_workspace_agent_file(Path(session.work_dir))
    if workspace_agent_file is not None:
        _register_subagents_from_spec(workspace_agent_file, "workspace")
except Exception as e:
    from consilium.utils.logging import logger
    logger.warning(f"Failed to load builtin/workspace subagents for Think mode: {e}")
```

**After:**
```python
# Register built-in subagent types.
builtin_agent_file = Path(__file__).parent / "agents" / "default" / "agent.yaml"
_register_subagents_from_spec(builtin_agent_file, "builtin")
# Register workspace-level overrides if they exist.
workspace_agent_file = find_workspace_agent_file(Path(session.work_dir))
if workspace_agent_file is not None:
    _register_subagents_from_spec(workspace_agent_file, "workspace")
```

**Changes to `_register_subagents_from_spec()`:**
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

## 4. Acceptance Criteria

- [x] `explore` subagent type registers successfully in Think mode
- [x] `plan_editor`, `plan`, and `plan_reviewer` subagent types also register in Think mode
- [x] A single misconfigured subagent (e.g., missing role file) does not prevent others from registering
- [x] Registration failures are logged as individual warnings with sufficient detail
- [x] Do mode subagent registration continues to work unchanged

## 5. Test Plan

### 5.1 Functional verification

1. Start Think mode and verify that `explore` subagent can be spawned successfully.
2. Start Think mode and verify that `plan_editor`, `plan`, and `plan_reviewer` subagents can be spawned.
3. Introduce a transient error in one subagent spec and verify that other subagents still register.
4. Verify that Do mode subagent registration is unaffected.

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Removing the try/except could expose unhandled errors during registration | L | M | Per-subagent error handling inside the loop catches individual failures |
| A workspace agent spec with a critical error could crash Think mode startup | L | M | The per-subagent try/except catches individual failures, not the entire spec loading |
| The fix might not cover all edge cases | L | L | Matches the same pattern used in `load_agent()` for Do mode, which is proven working |

## 7. Effort Estimate

| Sub-task | Hours | Notes |
|----------|-------|-------|
| Root cause analysis | 1 | Identified the blanket try/except in `create_think_soul()` |
| Code fix | 0.5 | Remove try/except, add per-subagent error handling |
| Verification | 0.5 | Test all subagent types in Think mode |
| **Total** | **2** | |

## 8. Deferred Items

| Item | Reason |
|------|--------|
| Refactoring `create_think_soul()` to share registration logic with `load_agent()` | Not needed — the fix aligns the patterns already |
| Adding automated tests for subagent registration error handling | Could be added in a future phase focused on test coverage |
| Workspace agent spec validation improvements | Separate concern; not required for this fix |