# Phase 05: Update Share Directory & Documentation

## Goal
Migrate the user configuration directory to `.consilium` and update user-facing documentation to reflect the new configurations, including instructions for connecting to OpenRouter.

## Tasks
- [ ] In `src/consilium/share.py`, change the user directory resolution from `~/.kimi/` to `~/.consilium/`. (Per user feedback, do not write a migration script; just use the new directory).
- [ ] Update the `README.md` and/or `MODEL_OPTIONS_RESEARCH.md` files:
  - Document the transition to `~/.consilium/config.toml`.
  - Add explicit setup instructions and an example snippet for configuring OpenRouter using the `openai_responses` provider type, highlighting the `custom_headers` usage for `HTTP-Referer` and `X-Title`.
- [ ] Final project audit: Run a codebase-wide grep for any remaining instances of `Kimi` (case-insensitive) that aren't tied to historical changelogs.
