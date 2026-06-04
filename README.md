# Consilium — Prompt-Extensible Fork

> This is a community fork of [MoonshotAI/consilium](https://github.com/MoonshotAI/consilium) with two focus areas:
> 1. **Prompt extensibility** — every system prompt is editable via config, without code changes.
> 2. **Generation parameters** — per-model `temperature`, `top_p`, `max_tokens`, etc. via config file or CLI flags (`--temperature`, `--top-p`, `--max-tokens`).

[![Commit Activity](https://img.shields.io/github/commit-activity/w/zemuro/consilium-extensible)](https://github.com/zemuro/consilium-extensible/graphs/commit-activity)
[![Version](https://img.shields.io/pypi/v/consilium)](https://pypi.org/project/consilium/)
[![Downloads](https://img.shields.io/pypi/dw/consilium)](https://pypistats.org/packages/consilium)

[Kimi Code](https://www.kimi.com/code/) | [Upstream Docs](https://moonshotai.github.io/consilium/en/) | [Upstream 文档](https://moonshotai.github.io/consilium/zh/)

Consilium is an AI agent that runs in the terminal, helping you complete software development tasks and terminal operations. It can read and edit code, execute shell commands, search and fetch web pages, and autonomously plan and adjust actions during execution.

---

## Table of Contents

- [Prompt Extensibility](#prompt-extensibility) — what's different in this fork
- [Generation Parameters](#generation-parameters) — per-model config
- [Getting Started](#getting-started)
- [Key Features](#key-features)
- [Development](#development)

---

## Prompt Extensibility

This fork extracts **all hardcoded system prompts** into plain `.md` files and lets you override them via configuration — no Python changes required.

### Quick Examples

**Override a main system prompt section** (`~/.kimi/config.toml`):

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

| Area | Before (upstream) | After (this fork) |
|---|---|---|
| Main system prompt | Single monolithic `system.md` (160 lines) | 8 decomposed sections under `prompts/system/` |
| Subagent prompts | Inline in YAML (`ROLE_ADDITIONAL`, `when_to_use`) | Loaded from `.md` files via `*_file` fields |
| Secondary prompts | Hardcoded Python strings | Plain `.md` files in `prompts/` |
| Customization | Fork + edit Python | Config-only overrides |

### Prompt Files Overview

**Main system prompt sections** (`src/kimi_cli/prompts/system/`):

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

**Subagent prompts** (`src/kimi_cli/agents/default/`):
- `coder_role.md`, `coder_when_to_use.md`
- `explore_role.md`, `explore_when_to_use.md`
- `plan_role.md`, `plan_when_to_use.md`

**Secondary/special-mode prompts** (`src/kimi_cli/prompts/`):
- `compaction_system.md`, `compaction_output.md`
- `side_question.md`
- `plan_mode_full.md`, `plan_mode_sparse.md`, `plan_mode_reentry.md`
- `afk_mode.md`, `afk_disabled.md`
- `init_complete.md`, `add_dir.md`

See [`PROMPT_EXTENSIBILITY.md`](./PROMPT_EXTENSIBILITY.md) for the full guide (architecture details, backward compatibility notes, and advanced customization).

---

## Generation Parameters

Every model can have its own generation settings in `~/.kimi/config.toml`:

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
kimi --temperature 0.7 --top-p 0.9 --max-tokens 4096
```

Precedence: `CLI flags > env vars > config file > defaults`.

### Supported parameters
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

Kimi-specific environment variables (`KIMI_MODEL_TEMPERATURE`, `KIMI_MODEL_TOP_P`, `KIMI_MODEL_MAX_TOKENS`) still work and override config values.

See [`MODEL_OPTIONS_RESEARCH.md`](./MODEL_OPTIONS_RESEARCH.md) for the full technical breakdown.

---

## Fork Features

This fork adds a **Think/Do workflow**, **plan-driven orchestration**, and **subagent budget controls** on top of the upstream agent.

### Think Mode — Research & Planning

A mutable-history REPL for speculative reasoning, prompt engineering, and plan authoring.

```
[kimi]$ /think
[Think] Entering Think mode. History is editable.

> Design a new auth system
...
> /edit msg_abc123            # edit any past message
> /delete msg_abc123          # soft-delete a message
> /checkpoint save-name       # save snapshot
> /compact                    # summarize old history
> /push-to-do                 # send conclusion to Do mode
```

Features: editable history, JSONL storage, checkpoints, manual compaction, Python execution (`/python`), subagent exploration (`/explore`).

### Do Mode — Execution & Implementation

An immutable, tool-enabled agent loop with full audit trail.

```
[kimi]$ consilium --do --plan-file docs/plan.md --phase phase-02
[Do] Stashed uncommitted changes. Starting Phase 2 audit...
...
> /review                     # manually audit the current plan
> /approve                    # approve and continue
> /reject too risky           # reject with reason
> /commit "checkpoint"        # git commit current state
> /abort                      # revert to initial stash
```

Features: git snapshotting, change journal (every file edit recorded), unified diffs, blob storage, plan review gate.

### Plan Decomposition

Large plans are split into per-phase documents instead of a single monolithic file:

```
docs/plan/
├── index.md              # dependency graph + status overview
├── phase-01.md           # individual phase
├── phase-02.md
└── ...
```

Do mode loads only the target phase + index, saving tokens on large projects. Think mode can generate and edit individual phases.

### Subagent Budget Gate

Subagents (explore, plan-review) run with token and tool-call budgets to prevent runaway costs:

```toml
[subagents.budget]
max_tokens_per_task = 20_000
max_tool_calls_per_task = 20
warn_tokens_ratio = 0.8
```

Warnings are emitted at 80%; hard limits stop the subagent gracefully and return partial results.

See [`docs/BEST_PRACTICES.md`](./docs/BEST_PRACTICES.md) for workflow guidance and [`ROADMAP.md`](./ROADMAP.md) for what's planned next.

---

## Getting Started

See the [upstream Getting Started guide](https://moonshotai.github.io/consilium/en/guides/getting-started.html) for how to install and start using Consilium.

To install this fork directly from source:

```sh
git clone https://github.com/zemuro/consilium-extensible.git
cd consilium-extensible

make prepare  # prepare the development environment
uv run kimi   # run Consilium
```

## Key Features

> All features below are inherited from the upstream project.

### Shell command mode

Consilium is not only a coding agent, but also a shell. You can switch the shell command mode by pressing `Ctrl-X`. In this mode, you can directly run shell commands without leaving Consilium.

![](./docs/media/shell-mode.gif)

> [!NOTE]
> Built-in shell commands like `cd` are not supported yet.

### VS Code extension

Consilium can be integrated with [Visual Studio Code](https://code.visualstudio.com/) via the [Kimi Code VS Code Extension](https://marketplace.visualstudio.com/items?itemName=moonshot-ai.kimi-code).

![VS Code Extension](./docs/media/vscode.png)

### IDE integration via ACP

Consilium supports [Agent Client Protocol] out of the box. You can use it together with any ACP-compatible editor or IDE.

[Agent Client Protocol]: https://github.com/agentclientprotocol/agent-client-protocol

To use Consilium with ACP clients, make sure to run Consilium in the terminal and send `/login` to complete the login first. Then, you can configure your ACP client to start Consilium as an ACP agent server with command `kimi acp`.

For example, to use Consilium with [Zed](https://zed.dev/) or [JetBrains](https://blog.jetbrains.com/ai/2025/12/bring-your-own-ai-agent-to-jetbrains-ides/), add the following configuration to your `~/.config/zed/settings.json` or `~/.jetbrains/acp.json` file:

```json
{
  "agent_servers": {
    "Consilium": {
      "type": "custom",
      "command": "kimi",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Then you can create Consilium threads in IDE's agent panel.

![](./docs/media/acp-integration.gif)

### Zsh integration

You can use Consilium together with Zsh, to empower your shell experience with AI agent capabilities.

Install the [zsh-consilium](https://github.com/MoonshotAI/zsh-consilium) plugin via:

```sh
git clone https://github.com/MoonshotAI/zsh-consilium.git \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/consilium
```

> [!NOTE]
> If you are using a plugin manager other than Oh My Zsh, you may need to refer to the plugin's README for installation instructions.

Then add `consilium` to your Zsh plugin list in `~/.zshrc`:

```sh
plugins=(... consilium)
```

After restarting Zsh, you can switch to agent mode by pressing `Ctrl-X`.

### MCP support

Consilium supports MCP (Model Context Protocol) tools.

**`kimi mcp` sub-command group**

You can manage MCP servers with `kimi mcp` sub-command group. For example:

```sh
# Add streamable HTTP server:
kimi mcp add --transport http context7 https://mcp.context7.com/mcp --header "CONTEXT7_API_KEY: ctx7sk-your-key"

# Add streamable HTTP server with OAuth authorization:
kimi mcp add --transport http --auth oauth linear https://mcp.linear.app/mcp

# Add stdio server:
kimi mcp add --transport stdio chrome-devtools -- npx chrome-devtools-mcp@latest

# List added MCP servers:
kimi mcp list

# Remove an MCP server:
kimi mcp remove chrome-devtools

# Authorize an MCP server:
kimi mcp auth linear
```

**Ad-hoc MCP configuration**

Consilium also supports ad-hoc MCP server configuration via CLI option.

Given an MCP config file in the well-known MCP config format like the following:

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp",
      "headers": {
        "CONTEXT7_API_KEY": "YOUR_API_KEY"
      }
    },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

Run `consilium` with `--mcp-config-file` option to connect to the specified MCP servers:

```sh
kimi --mcp-config-file /path/to/mcp.json
```

### More

See more features in the [upstream documentation](https://moonshotai.github.io/consilium/en/).

## Development

```sh
git clone https://github.com/zemuro/consilium-extensible.git
cd consilium-extensible

make prepare  # prepare the development environment
```

Then you can start working on Consilium.

Refer to the following commands after you make changes:

```sh
uv run kimi  # run Consilium

make format  # format code
make check  # run linting and type checking
make test  # run tests
make test-consilium  # run Consilium tests only
make test-kosong  # run kosong tests only
make test-pykaos  # run pykaos tests only
make build-web  # build the web UI and sync it into the package (requires Node.js/npm)
make build  # build python packages
make build-bin  # build standalone binary
make help  # show all make targets
```

Note: `make build` and `make build-bin` automatically run `make build-web` to embed the web UI.
