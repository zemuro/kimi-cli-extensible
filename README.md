# Kimi Code CLI — Prompt-Extensible Fork

> This is a community fork of [MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli) focused on **making every system prompt editable without code changes**.
>
> All upstream features are preserved. The additions are: decomposed system prompts, config-driven overrides, and file-based subagent prompt loading.

[![Commit Activity](https://img.shields.io/github/commit-activity/w/zemuro/kimi-cli-extensible)](https://github.com/zemuro/kimi-cli-extensible/graphs/commit-activity)
[![Version](https://img.shields.io/pypi/v/kimi-cli)](https://pypi.org/project/kimi-cli/)
[![Downloads](https://img.shields.io/pypi/dw/kimi-cli)](https://pypistats.org/packages/kimi-cli)

[Kimi Code](https://www.kimi.com/code/) | [Upstream Docs](https://moonshotai.github.io/kimi-cli/en/) | [Upstream 文档](https://moonshotai.github.io/kimi-cli/zh/)

Kimi Code CLI is an AI agent that runs in the terminal, helping you complete software development tasks and terminal operations. It can read and edit code, execute shell commands, search and fetch web pages, and autonomously plan and adjust actions during execution.

---

## Table of Contents

- [Prompt Extensibility](#prompt-extensibility) — what's different in this fork
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

## Getting Started

See the [upstream Getting Started guide](https://moonshotai.github.io/kimi-cli/en/guides/getting-started.html) for how to install and start using Kimi Code CLI.

To install this fork directly from source:

```sh
git clone https://github.com/zemuro/kimi-cli-extensible.git
cd kimi-cli-extensible

make prepare  # prepare the development environment
uv run kimi   # run Kimi Code CLI
```

## Key Features

> All features below are inherited from the upstream project.

### Shell command mode

Kimi Code CLI is not only a coding agent, but also a shell. You can switch the shell command mode by pressing `Ctrl-X`. In this mode, you can directly run shell commands without leaving Kimi Code CLI.

![](./docs/media/shell-mode.gif)

> [!NOTE]
> Built-in shell commands like `cd` are not supported yet.

### VS Code extension

Kimi Code CLI can be integrated with [Visual Studio Code](https://code.visualstudio.com/) via the [Kimi Code VS Code Extension](https://marketplace.visualstudio.com/items?itemName=moonshot-ai.kimi-code).

![VS Code Extension](./docs/media/vscode.png)

### IDE integration via ACP

Kimi Code CLI supports [Agent Client Protocol] out of the box. You can use it together with any ACP-compatible editor or IDE.

[Agent Client Protocol]: https://github.com/agentclientprotocol/agent-client-protocol

To use Kimi Code CLI with ACP clients, make sure to run Kimi Code CLI in the terminal and send `/login` to complete the login first. Then, you can configure your ACP client to start Kimi Code CLI as an ACP agent server with command `kimi acp`.

For example, to use Kimi Code CLI with [Zed](https://zed.dev/) or [JetBrains](https://blog.jetbrains.com/ai/2025/12/bring-your-own-ai-agent-to-jetbrains-ides/), add the following configuration to your `~/.config/zed/settings.json` or `~/.jetbrains/acp.json` file:

```json
{
  "agent_servers": {
    "Kimi Code CLI": {
      "type": "custom",
      "command": "kimi",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Then you can create Kimi Code CLI threads in IDE's agent panel.

![](./docs/media/acp-integration.gif)

### Zsh integration

You can use Kimi Code CLI together with Zsh, to empower your shell experience with AI agent capabilities.

Install the [zsh-kimi-cli](https://github.com/MoonshotAI/zsh-kimi-cli) plugin via:

```sh
git clone https://github.com/MoonshotAI/zsh-kimi-cli.git \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/kimi-cli
```

> [!NOTE]
> If you are using a plugin manager other than Oh My Zsh, you may need to refer to the plugin's README for installation instructions.

Then add `kimi-cli` to your Zsh plugin list in `~/.zshrc`:

```sh
plugins=(... kimi-cli)
```

After restarting Zsh, you can switch to agent mode by pressing `Ctrl-X`.

### MCP support

Kimi Code CLI supports MCP (Model Context Protocol) tools.

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

Kimi Code CLI also supports ad-hoc MCP server configuration via CLI option.

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

Run `kimi` with `--mcp-config-file` option to connect to the specified MCP servers:

```sh
kimi --mcp-config-file /path/to/mcp.json
```

### More

See more features in the [upstream documentation](https://moonshotai.github.io/kimi-cli/en/).

## Development

```sh
git clone https://github.com/zemuro/kimi-cli-extensible.git
cd kimi-cli-extensible

make prepare  # prepare the development environment
```

Then you can start working on Kimi Code CLI.

Refer to the following commands after you make changes:

```sh
uv run kimi  # run Kimi Code CLI

make format  # format code
make check  # run linting and type checking
make test  # run tests
make test-kimi-cli  # run Kimi Code CLI tests only
make test-kosong  # run kosong tests only
make test-pykaos  # run pykaos tests only
make build-web  # build the web UI and sync it into the package (requires Node.js/npm)
make build  # build python packages
make build-bin  # build standalone binary
make help  # show all make targets
```

Note: `make build` and `make build-bin` automatically run `make build-web` to embed the web UI.
