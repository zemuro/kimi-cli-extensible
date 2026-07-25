# Rebasing from Upstream

This fork (`consilium-extensible`) tracks [MoonshotAI/consilium](https://github.com/MoonshotAI/consilium). Every upstream release requires manual merge resolution in a small set of files.

## Files That Will Conflict Every Time

### `src/consilium/agents/default/system.md`
**Upstream:** Monolithic 160-line system prompt.  
**Ours:** Single-line assembly marker (`<!-- assembled-from-sections -->`).

**Resolution:** Always keep our marker. If upstream adds new content to `system.md`, port it to the appropriate section under `src/consilium/prompts/system/`.

### `src/consilium/soul/agent.py`
**Upstream:** `_load_system_prompt()` loads `system.md` verbatim.  
**Ours:** Detects assembly marker and dispatches to `assemble_system_prompt()`.

**Resolution:** Keep our loader logic. Merge upstream changes to the surrounding `Runtime` creation or agent dataclass code.

### `src/consilium/agentspec.py`
**Upstream:** YAML spec loader without file-based prompt fields.  
**Ours:** Added `system_prompt_args_files` and `when_to_use_file`.

**Resolution:** Keep our fields. Upstream schema additions usually merge cleanly because we only appended new optional fields.

### `src/consilium/config.py`
**Upstream:** `Config` and `LLMModel` Pydantic models.  
**Ours:** Added `system_prompt_overrides`, `GenerationConfig`, and `LLMModel.generation`.

**Resolution:** Keep our fields. Merge upstream validators into `validate_model()`.

### `src/consilium/llm.py`
**Upstream:** `create_llm()` with Kimi env vars and thinking logic.  
**Ours:** Added `_generation_kwargs_for_provider()`, `_map_cli_override()`, and `generation_overrides` parameter.

**Resolution:** Keep our generation-kwargs pipeline. Merge upstream provider additions (new `case` branches) into the match block.

## Procedure

```sh
# 1. Fetch upstream
git fetch upstream

# 2. Start rebase
git rebase upstream/main

# 3. Resolve conflicts
# For each conflict:
#   - system.md → keep our marker
#   - agent.py → keep our _load_system_prompt() logic
#   - agentspec.py → keep our new fields
#   - config.py → keep our new fields + merge validators
#   - llm.py → keep our generation kwargs pipeline + merge new providers

# 4. Run tests
make test

# 5. If tests pass, continue rebase
git rebase --continue
```

## Porting Upstream System Prompt Changes

If upstream modifies `system.md`, diff their new version against the old one, then apply the delta to the correct section file:

| If upstream changed... | Apply to... |
|---|---|
| Agent identity / role | `src/consilium/prompts/system/identity.md` |
| Tool use / message handling | `src/consilium/prompts/system/prompt_and_tool_use.md` |
| Coding guidelines | `src/consilium/prompts/system/coding_guidelines.md` |
| Research / multimedia | `src/consilium/prompts/system/research_guidelines.md` |
| Shell / OS / environment | `src/consilium/prompts/system/working_environment.md` |
| AGENTS.md conventions | `src/consilium/prompts/system/project_info.md` |
| Skills | `src/consilium/prompts/system/skills.md` |
| Final reminders | `src/consilium/prompts/system/ultimate_reminders.md` |

If upstream added an entirely new topic, create a new section file and add it to `DEFAULT_SECTION_ORDER` in `src/consilium/prompts/system/__init__.py`.
