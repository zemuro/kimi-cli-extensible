---
name: consilium-help
description: Answer Consilium CLI usage, configuration, and troubleshooting questions. Use when user asks about Consilium CLI installation, setup, configuration, slash commands, keyboard shortcuts, MCP integration, providers, environment variables, how something works internally, or any questions about Consilium CLI itself.
---

# Consilium CLI Help

Help users with Consilium CLI questions by consulting documentation and source code.

## Strategy

1. **Prefer official documentation** for most questions
2. **Read local source** when in consilium project itself, or when user is developing with consilium as a library (e.g., importing from `consilium` in their code)
3. **Clone and explore source** for complex internals not covered in docs - **ask user for confirmation first**

## Documentation

Base URL: `https://moonshotai.github.io/consilium/`

Fetch documentation index to find relevant pages:

```
https://moonshotai.github.io/consilium/llms.txt
```

### Page URL Pattern

- English: `https://moonshotai.github.io/consilium/en/...`
- Chinese: `https://moonshotai.github.io/consilium/zh/...`

### Topic Mapping

| Topic | Page |
|-------|------|
| Installation, first run | `/en/guides/getting-started.md` |
| Config files | `/en/configuration/config-files.md` |
| Providers, models | `/en/configuration/providers.md` |
| Environment variables | `/en/configuration/env-vars.md` |
| Slash commands | `/en/reference/slash-commands.md` |
| CLI flags | `/en/reference/kimi-command.md` |
| Keyboard shortcuts | `/en/reference/keyboard.md` |
| MCP | `/en/customization/mcp.md` |
| Agents | `/en/customization/agents.md` |
| Skills | `/en/customization/skills.md` |
| FAQ | `/en/faq.md` |

## Source Code

Repository: `https://github.com/MoonshotAI/consilium`

When to read source:

- In consilium project directory (check `pyproject.toml` for `name = "consilium"`)
- User is importing `consilium` as a library in their project
- Question about internals not covered in docs (ask user before cloning)
