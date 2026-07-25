# Consilium

An AI agent that runs in the terminal, helping you complete software development tasks and terminal operations. It can read and edit code, execute shell commands, search and fetch web pages, and autonomously plan and adjust actions during execution.

Consilium operates in two distinct modes — **Think** for reasoning and planning, **Do** for execution — with a structured plan-driven workflow connecting them.

---

## Table of Contents

- [Think/Do Workflow](#thinkdo-workflow)
- [Prompt Extensibility](#prompt-extensibility)
- [Generation Parameters](#generation-parameters)
- [Getting Started](#getting-started)
- [Key Features](#key-features)
- [Development](#development)

---

## Think/Do Workflow

Consilium's core architecture separates reasoning from execution:

### Think Mode — Research & Planning

A mutable-history REPL for speculative reasoning, prompt engineering, and plan authoring. Think mode has no tool access — it reasons, plans, and writes documentation, but cannot modify your codebase.

```
$ consilium
[Think] Entering Think mode. History is editable.

> Design a new auth system
...
> /edit msg_abc123            # edit any past message
> /delete msg_abc123          # soft-delete a message
> /checkpoint save-name       # save snapshot
> /compact                    # summarize old history
> /explore "Find thread-local usage"   # spawn read-only subagent
> /investigate "Why is the build failing?"  # parallel background subagents
> /plan init                  # scaffold project plan
> /push-to-do                 # send plan to Do mode for execution
```

**Features:** editable history, JSONL storage, checkpoints, manual compaction, Python execution (`/python`), subagent exploration (`/explore`), parallel investigation (`/investigate`), plan synthesis (`/plan`), and push-to-do handoff.

### Do Mode — Execution & Implementation

An immutable, tool-enabled agent loop with full audit trail. Do mode has full tool access — it reads and writes files, executes commands, and performs actual work.

```
$ consilium --do --plan-file plan/index.md --phase phase-02
[Do] Stashed uncommitted changes. Starting Phase 2 audit...
...
> /review                     # manually audit the current plan
> /approve                    # approve and continue
> /reject too risky           # reject with reason
> /commit "checkpoint"        # git commit current state
> /abort                      # revert to initial stash
```

**Features:** git snapshotting, change journal (every file edit recorded), unified diffs, blob storage, plan review gate, subagent budget controls.

### Bidirectional Handoff

- **Think → Do:** `/push-to-do` writes a `dispatch.json` with plan file and target phase. Do mode loads the plan directly (not conversation history).
- **Do → Think:** `/complete` and audit reports are written to Think's inbox. Think mode polls via `/inbox`.

### Plan Decomposition

Large plans are split into per-phase documents:

```
plan/
├── index.md              # dependency graph + status overview
├── phase-01.md           # individual phase
├── phase-02.md
├── decisions/
│   ├── index.md          # ADR master index
│   └── 001-*.md          # individual ADRs
├── findings/             # research outputs from Think mode
│   └── 001-*.md
└── reports/              # Do mode outputs (auto-generated)
    ├── audit-phase-*.md
    └── completion-phase-*.md
```

Do mode loads only the target phase + index, saving tokens on large projects.

---

## Prompt Extensibility

All system prompts are extracted into plain `.md` files and can be overridden via configuration — no code changes required.

### Quick Examples

**Override a main system prompt section** (`~/.consilium/config.toml`):

```toml
[system_prompt_overrides]
identity = "~/prompts/my-identity.md"
coding_guidelines = "~/prompts/my-coding.md"
```

**Load subagent prompts from files** (`coder.yaml`):

```yaml
agent:
  system_prompt_args_files:
    ROLE_ADDITIONAL: ./coder_role.md
  when_to_use_file: ./coder_when_to_use.md
```

### What Changed

| Area | Before | After |
|---|---|---|
| Main system prompt | Single monolithic `system.md` (160 lines) | 8 decomposed sections under `prompts/system/` |
| Subagent prompts | Inline in YAML (`ROLE_ADDITIONAL`, `when_to_use`) | Loaded from `.md` files via `*_file` fields |
| Secondary prompts | Hardcoded Python strings | Plain `.md` files in `prompts/` |
| Customization | Fork + edit Python | Config-only overrides |

### Prompt Files Overview

**Main system prompt sections** (`src/consilium/prompts/system/`):

| File | Content |
|---|---|
| `identity.md` | Agent identity and role |
| `prompt_and_tool_use.md` | Message handling, tool use, approvals |
| `coding_guidelines.md` | Coding from scratch, existing codebases, git rules |
| `research_guidelines.md` | Research tasks, multimedia |
| `working_environment.md` | OS, shell, working directory |
| `project_info.md` | `AGENTS.md` conventions |
| `skills.md` | Available skills and usage |
| `ultimate_reminders.md` | Final behavioral rules |

**Subagent prompts** (`src/consilium/agents/default/`):
- `coder_role.md`, `coder_when_to_use.md`
- `explore_role.md`, `explore_when_to_use.md`
- `plan_role.md`, `plan_when_to_use.md`

**Secondary/special-mode prompts** (`src/consilium/prompts/`):
- `compaction_system.md`, `compaction_output.md`
- `side_question.md`
- `plan_mode_full.md`, `plan_mode_sparse.md`, `plan_mode_reentry.md`
- `afk_mode.md`, `afk_disabled.md`
- `init_complete.md`, `add_dir.md`

See [`PROMPT_EXTENSIBILITY.md`](./PROMPT_EXTENSIBILITY.md) for the full guide.

---

## Generation Parameters

Every model can have its own generation settings in `~/.consilium/config.toml`:

```toml
[models.my-kimi]
provider = "kimi"
model = "kimi-k2-turbo-preview"
max_context_size = 256000

[models.my-kimi.generation]
temperature = 0.7
top_p = 0.9
max_tokens = 32000
```

### Quick override from the CLI

```sh
consilium --temperature 0.7 --top-p 0.9 --max-tokens 4096
```

Precedence: `CLI flags > env vars > config file > defaults`.

### Supported parameters

| Parameter | Providers | Description |
|---|---|---|
| `temperature` | all | Sampling temperature (0–2) |
| `top_p` | all | Nucleus sampling (0–1) |
| `max_tokens` | kimi, openai_legacy, anthropic | Max tokens to generate |
| `max_output_tokens` | openai_responses, gemini | Max output tokens (falls back from `max_tokens`) |
| `presence_penalty` | kimi, openai_legacy | Penalty for repeating present tokens |
| `frequency_penalty` | kimi, openai_legacy | Penalty based on token frequency |
| `stop` | kimi, openai_legacy | Stop sequence(s) |
| `n` | kimi, openai_legacy | Completions per prompt |
| `top_k` | anthropic, gemini | Top-k sampling |
| `max_tool_calls` | openai_responses | Max tool calls per response |
| `top_logprobs` | openai_responses | Logprobs to return |
| `user` | openai_responses | End-user identifier |
| `tool_choice` | anthropic | Tool choice configuration |
| `extra_headers` | anthropic | Extra HTTP headers |

### OpenRouter Configuration

You can configure OpenRouter by defining a custom provider of type `openai_responses` and configuring custom headers for OpenRouter requirement:

```toml
[providers.openrouter]
type = "openai_responses"
base_url = "https://openrouter.ai/api/v1"
api_key = "your-openrouter-api-key"

[providers.openrouter.custom_headers]
"HTTP-Referer" = "https://github.com/zemuro/consilium"
"X-Title" = "Consilium Agent"

[models.openrouter-deepseek]
provider = "openrouter"
model = "deepseek/deepseek-chat"
max_context_size = 64000
```

See [`MODEL_OPTIONS_RESEARCH.md`](./MODEL_OPTIONS_RESEARCH.md) for the full technical breakdown.

---

## Subagent Budget Gate

Subagents (explore, plan-review, investigate) run with token and tool-call budgets to prevent runaway costs:

```toml
[subagents.budget]
max_tokens_per_task = 80_000
max_tool_calls_per_task = 100
warn_tokens_ratio = 0.8
```

Warnings are emitted at 80%; hard limits stop the subagent gracefully and return partial results.

## Per-Subagent Overrides

Tune temperature, token budget, tool-call budget, and timeout independently for each builtin subagent type. Resolution order is the same as global settings:

`CLI flags > env vars > config file > global defaults`.

### Config file (`~/.consilium/config.toml`)

```toml
[subagents.overrides.explore]
temperature = 0.7
max_tokens_per_task = 80_000
max_tool_calls_per_task = 100
timeout_seconds = 900

[subagents.overrides.coder]
temperature = 0.4
max_tokens_per_task = 16_384
max_tool_calls_per_task = 40
timeout_seconds = 600
```

### Environment variables

```sh
export CONSILIUM_SUBAGENT_CODER_TEMPERATURE=0.4
export CONSILIUM_SUBAGENT_EXPLORE_MAX_TOKENS_PER_TASK=4096
export CONSILIUM_SUBAGENT_PLAN_EDITOR_TIMEOUT_SECONDS=120
```

### CLI flags

```sh
consilium --subagent-coder-temperature 0.4 \
          --subagent-explore-max-tool-calls-per-task 50 \
          --subagent-plan-editor-timeout-seconds 120
```

Supported override fields for every builtin type (`coder`, `explore`, `plan`, `plan_editor`, `plan_reviewer`):

| Field | Description | Global default |
|---|---|---|
| `temperature` | Sampling temperature (0–2) | Model's configured temperature |
| `max_tokens_per_task` | Hard token limit per task | `subagents.budget.max_tokens_per_task` |
| `max_tool_calls_per_task` | Hard tool-call limit per task | `subagents.budget.max_tool_calls_per_task` |
| `timeout_seconds` | Adaptive timeout ceiling | `subagents.timeout_seconds` |

---

## Persistent Log Architecture

Two independent append-only logs (Think log, Do log) linked by cross-reference entries:

- **Immutable logs** — append-only, never rewrite, hash-linked
- **Materialized views** — ephemeral slices of the log, cached
- **Cross-references** — pointers between Think and Do logs for traceability
- **Wire protocol queries** — `query_logs`, `fetch_plan`, `trace_entry` for extension integration

Storage layout:
```
~/.consilium/think_logs/{session_id}.jsonl   # Think log
~/.consilium/do_logs/{session_id}.jsonl      # Do log
```

---

## Getting Started

Install from source:

```sh
git clone https://github.com/zemuro/consilium.git
cd consilium

make prepare  # prepare the development environment
uv run consilium   # run Consilium
```

---

## Key Features

### Shell command mode

Consilium is not only a coding agent, but also a shell. You can switch the shell command mode by pressing `Ctrl-X`. In this mode, you can directly run shell commands without leaving Consilium.

> [!NOTE]
> Built-in shell commands like `cd` are not supported yet.

### VS Code: extension

Consilium integrates with Visual Studio Code: via a dedicated extension providing a dual-tab Think/Do interface.

### IDE integration via ACP

Consilium supports Agent Client Protocol out of the box. Use it with any ACP-compatible editor or IDE.

To use Consilium with ACP clients, run Consilium in the terminal and send `/login` to complete the login first. Then configure your ACP client to start Consilium as an ACP agent server with command `consilium acp`.

For example, to use with Zed or JetBrains:

```json
{
  "agent_servers": {
    "Consilium": {
      "type": "custom",
      "command": "consilium",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

### Zsh integration

You can use Consilium together with Zsh via the `zsh-consilium` plugin.

### MCP support

Consilium supports MCP (Model Context Protocol) tools.

**`consilium mcp` sub-command group**

```sh
# Add streamable HTTP server:
consilium mcp add --transport http context7 https://mcp.context7.com/mcp --header "CONTEXT7_API_KEY: ctx7sk-your-key"

# Add stdio server:
consilium mcp add --transport stdio chrome-devtools -- npx chrome-devtools-mcp@latest

# List, remove, authorize:
consilium mcp list
consilium mcp remove chrome-devtools
consilium mcp auth linear
```

**Ad-hoc MCP configuration**

```sh
consilium --mcp-config-file /path/to/mcp.json
```

---

## Development

```sh
git clone https://github.com/zemuro/consilium.git
cd consilium

make prepare  # prepare the development environment
```

Then you can start working on Consilium.

```sh
uv run consilium        # run Consilium

make format             # format code
make check              # run linting and type checking
make test               # run tests
make test-consilium     # run Consilium tests only
make build              # build python packages
make build-bin          # build standalone binary
make help               # show all make targets
```

Note: `make build` and `make build-bin` automatically run `make build-web` to embed the web UI.
