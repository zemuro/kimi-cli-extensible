# Phase 04: Migrate Environment Variables

## Goal
Rename all environment variables used by the system from `KIMI_*` to `CONSILIUM_*`. 
*Note: This is a breaking change for existing environments.*

## Tasks
- [ ] Update environment variable parsing in `src/consilium/config.py` (e.g., `CONSILIUM_BASE_URL`, `CONSILIUM_API_KEY`).
- [ ] Update environment variable parsing and application in `src/consilium/llm.py` (e.g., `CONSILIUM_MODEL_TEMPERATURE`).
- [ ] Search the repository globally for `KIMI_` (e.g., `CONSILIUM_WORK_DIR`, `CONSILIUM_AGENTS_MD`, `CONSILIUM_SKILLS`) and replace all occurrences with `CONSILIUM_`.
- [ ] Update any test mocks or fixtures that set `KIMI_*` environment variables.
