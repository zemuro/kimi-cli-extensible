# Phase 02 Walkthrough: Rename Core Runtime Classes

We have renamed all Kimi-specific core runtime classes, constants, exception classes, and syntax/branding elements to their `Consilium` equivalents.

## Changes Made

### Class & Module Renames
- Renamed `KimiCLI` to `ConsiliumCLI` in [app.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/app.py) and across the codebase.
- Renamed `KimiSoul` to `ConsiliumSoul` in [kimisoul.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/soul/kimisoul.py) and across all references.
- Renamed `KimiCLIException` to `ConsiliumCLIException` in [exception.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/exception.py).
- Renamed `KimiSyntax` to `ConsiliumSyntax` and themes `CONSILIUM_ANSI_THEME` / `CONSILIUM_ANSI_THEME_NAME` to `CONSILIUM_ANSI_THEME` / `CONSILIUM_ANSI_THEME_NAME` in [syntax.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/utils/rich/syntax.py).
- Renamed `KimiToolset` to `ConsiliumToolset` in [toolset.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/soul/toolset.py).
- Renamed `KimiCLIRunner` and `KimiCLISession` in the web runner and store modules.

### Constants & Environment Variables
- In [constant.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/constant.py):
  - Updated `NAME` from `"Consilium CLI"` to `"Consilium"`.
  - Updated `get_user_agent()` prefix to `"Consilium/"`.
  - Renamed environment variable `CONSILIUM_BUILD_SHA` to `CONSILIUM_BUILD_SHA`.
- Updated build/injection scripts and the [Makefile](file:///c:/Users/zemuro/Antigravity/consilium_mod/Makefile) to use `CONSILIUM_BUILD_SHA`.
- Updated fallback CLI prog_name in [__main__.py](file:///c:/Users/zemuro/Antigravity/consilium_mod/src/consilium/__main__.py) from `"kimi"` to `"consilium"`.

## Verification Results

### Automated Tests
Ran the renamed and related test modules via pytest. All 40 tests passed:
- `tests/core/test_startup_imports.py` (Passed)
- `tests/core/test_startup_progress.py` (Passed)
- `tests/core/test_plan_flag.py` (Passed)
- `tests/core/test_notifications.py` (Passed)
- `tests/acp/test_session_notifications.py` (Passed)
- Automatically fixed inline snapshots via `--inline-snapshot=fix` for `test_agent_spec.py` and `test_config.py` (Passed).
