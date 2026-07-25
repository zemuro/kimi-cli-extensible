# Phase 02: Rename Core Runtime Classes

## Goal
Remove "Kimi" terminology from core runtime classes, branding, and user-facing CLI defaults to properly reflect the `Consilium` name.

## Tasks
- [ ] In `src/consilium/app.py`, rename the `KimiCLI` class to `ConsiliumCLI`.
- [ ] In `src/consilium/soul/kimisoul.py` (and any related imports), rename the `KimiSoul` class to `AgentSoul` (or `ConsiliumSoul`). Update references to this class across the codebase.
- [ ] Update the internal `USER_AGENT` string and any embedded branding that hardcodes `KimiCLI/x.x` to use `Consilium/x.x`.
- [ ] In `src/consilium/constant.py`, verify and rename any `KIMI_` constants or strings if present.
- [ ] Run `make check` and `make test` to ensure class renames haven't broken imports.
