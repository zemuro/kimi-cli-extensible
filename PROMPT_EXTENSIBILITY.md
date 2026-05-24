# Prompt Extensibility Guide

This fork makes the kimi-cli system prompts fully customizable without requiring code changes. All hardcoded prompts have been extracted into plain `.md` files that can be overridden via configuration.

## What Changed

### 1. Main System Prompt — Decomposed into Sections

The monolithic `src/kimi_cli/agents/default/system.md` (160 lines) has been split into logical sections under `src/kimi_cli/prompts/system/`:

| Section File | Covers |
|---|---|
| `identity.md` | Agent identity, role, `${ROLE_ADDITIONAL}` |
| `prompt_and_tool_use.md` | Message handling, tool use, parallel calls, background tasks, approvals |
| `coding_guidelines.md` | Building from scratch, existing codebases, git rules |
| `research_guidelines.md` | Research tasks, multimedia files |
| `working_environment.md` | OS, shell, date/time, working directory, additional dirs |
| `project_info.md` | `AGENTS.md` conventions and usage |
| `skills.md` | Skills overview, available skills, how to use |
| `ultimate_reminders.md` | Final behavioral rules |

The default `system.md` now contains only an assembly marker:

```markdown
<!-- assembled-from-sections -->
```

When `_load_system_prompt()` sees this marker, it loads the sections in order and joins them with one blank line between each.

### 2. Subagent Prompts — Extracted from YAML

The inline `ROLE_ADDITIONAL` and `when_to_use` text in `coder.yaml`, `explore.yaml`, and `plan.yaml` have been moved to dedicated `.md` files:

- `coder_role.md` / `coder_when_to_use.md`
- `explore_role.md` / `explore_when_to_use.md`
- `plan_role.md` / `plan_when_to_use.md`

The `AgentSpec` loader now supports two new fields:

```yaml
agent:
  system_prompt_args_files:
    ROLE_ADDITIONAL: ./coder_role.md
  when_to_use_file: ./coder_when_to_use.md
```

This keeps YAML specs clean and makes subagent behavior editable without touching Python or YAML syntax.

### 3. Secondary/Special-Mode Prompts — Extracted

All previously hardcoded prompts now live in `src/kimi_cli/prompts/`:

| File | Used By |
|---|---|
| `compaction_system.md` | Context compaction LLM call |
| `compaction_output.md` | Compaction result prefix |
| `side_question.md` | `/btw` side questions |
| `plan_mode_full.md` | Plan mode activation reminder |
| `plan_mode_sparse.md` | Periodic plan mode reminder |
| `plan_mode_reentry.md` | Re-entering plan mode reminder |
| `afk_mode.md` | AFK mode injection |
| `afk_disabled.md` | AFK disabled reminder |
| `init_complete.md` | `/init` slash command |
| `add_dir.md` | `/add-dir` slash command |

## How to Customize Prompts

### Override Individual Main Prompt Sections

Add this to `~/.kimi/config.toml`:

```toml
[system_prompt_overrides]
identity = "~/prompts/my-identity.md"
coding_guidelines = "~/prompts/my-coding.md"
```

Any section not listed continues to use the built-in default. Upstream updates to un-overridden sections still flow through.

### Override an Entire Agent's System Prompt

Custom agents can still provide a complete `system.md` file. Only the default agent (and agents that extend it) use the section assembly. If your custom `system.md` does **not** contain `<!-- assembled-from-sections -->`, it is loaded verbatim as before.

### Override Secondary Prompts

Secondary prompts are loaded at import time from `src/kimi_cli/prompts/`. To override them, fork the repo and edit the `.md` files directly, or (for runtime overrides) contribute a plugin that hooks into the loading mechanism.

### Override Subagent Prompts

Subagent role and `when_to_use` prompts are loaded from files relative to the subagent YAML. You can fork and edit:

- `src/kimi_cli/agents/default/coder_role.md`
- `src/kimi_cli/agents/default/explore_when_to_use.md`
- etc.

Or create a new agent spec that extends the default and points to your own files:

```yaml
version: 1
agent:
  extend: default
  system_prompt_args_files:
    ROLE_ADDITIONAL: ./my-role.md
  when_to_use_file: ./my-when-to-use.md
```

## Architecture Details

### Section Assembly

`src/kimi_cli/prompts/system/__init__.py` exports:

- `DEFAULT_SECTION_ORDER` — list of section names in assembly order
- `load_section(name, overrides)` — load a single section, respecting overrides
- `assemble_system_prompt(overrides)` — join all sections with `\n\n`
- `is_assembled_prompt(text)` — detect the assembly marker

### Config Schema Addition

`src/kimi_cli/config.py` adds:

```python
system_prompt_overrides: dict[str, str]
```

Keys are section names (e.g., `"identity"`, `"coding_guidelines"`). Values are absolute or `~`-prefixed paths to replacement `.md` files.

### AgentSpec Schema Additions

`src/kimi_cli/agentspec.py` adds:

```python
system_prompt_args_files: dict[str, Path]  # key → file path
when_to_use_file: Path | None
```

These are resolved relative to the agent YAML file and loaded at spec-parse time.

## Backward Compatibility

- Existing `system.md` files without the assembly marker work exactly as before
- Inline `system_prompt_args` and `when_to_use` in YAML still work
- All existing tests pass without modification
- The Jinja2 variable syntax (`${KIMI_OS}`, `{% if %}`) continues to work inside sections
