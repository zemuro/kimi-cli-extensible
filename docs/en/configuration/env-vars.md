# Environment Variables

Consilium CLI supports overriding configuration or controlling runtime behavior through environment variables. This page lists all supported environment variables.

For detailed information on how environment variables override configuration files, see [Config Overrides](./overrides.md).

## Kimi environment variables

The following environment variables take effect when using `kimi` type providers, used to override provider and model configuration.

| Environment Variable | Description |
| --- | --- |
| `CONSILIUM_BASE_URL` | API base URL |
| `CONSILIUM_API_KEY` | API key |
| `CONSILIUM_MODEL_NAME` | Model identifier |
| `CONSILIUM_MODEL_MAX_CONTEXT_SIZE` | Maximum context length (in tokens) |
| `CONSILIUM_MODEL_CAPABILITIES` | Model capabilities, comma-separated (e.g., `thinking,image_in`) |
| `CONSILIUM_MODEL_TEMPERATURE` | Generation parameter `temperature` |
| `CONSILIUM_MODEL_TOP_P` | Generation parameter `top_p` |
| `CONSILIUM_MODEL_MAX_TOKENS` | Generation parameter `max_tokens` |
| `CONSILIUM_MODEL_THINKING_KEEP` | Moonshot `thinking.keep` switch for preserved thinking (only applied when thinking mode is active) |

### `CONSILIUM_BASE_URL`

Overrides the provider's `base_url` field in the configuration file.

```sh
export CONSILIUM_BASE_URL="https://api.moonshot.cn/v1"
```

### `CONSILIUM_API_KEY`

Overrides the provider's `api_key` field in the configuration file. Used to inject API keys without modifying the configuration file, suitable for CI/CD environments.

```sh
export CONSILIUM_API_KEY="sk-xxx"
```

### `CONSILIUM_MODEL_NAME`

Overrides the model's `model` field in the configuration file (the model identifier used in API calls).

```sh
export CONSILIUM_MODEL_NAME="kimi-k2-thinking-turbo"
```

### `CONSILIUM_MODEL_MAX_CONTEXT_SIZE`

Overrides the model's `max_context_size` field in the configuration file. Must be a positive integer.

```sh
export CONSILIUM_MODEL_MAX_CONTEXT_SIZE="262144"
```

### `CONSILIUM_MODEL_CAPABILITIES`

Overrides the model's `capabilities` field in the configuration file. Multiple capabilities are comma-separated, supported values are `thinking`, `always_thinking`, `image_in`, and `video_in`.

```sh
export CONSILIUM_MODEL_CAPABILITIES="thinking,image_in"
```

### `CONSILIUM_MODEL_TEMPERATURE`

Sets the generation parameter `temperature`, controlling output randomness. Higher values produce more random output, lower values produce more deterministic output.

```sh
export CONSILIUM_MODEL_TEMPERATURE="0.7"
```

### `CONSILIUM_MODEL_TOP_P`

Sets the generation parameter `top_p` (nucleus sampling), controlling output diversity.

```sh
export CONSILIUM_MODEL_TOP_P="0.9"
```

### `CONSILIUM_MODEL_MAX_TOKENS`

Sets the generation parameter `max_tokens`, limiting the maximum tokens per response.

```sh
export CONSILIUM_MODEL_MAX_TOKENS="4096"
```

### `CONSILIUM_MODEL_THINKING_KEEP`

Forwards the value verbatim to the Moonshot API as `thinking.keep`, enabling Preserved Thinking (see the [Moonshot docs](https://platform.consilium.com/docs/guide/use-kimi-k2-thinking-model#preserved-thinking)). Setting it to `all` causes the provider to preserve the reasoning content of previous assistant turns across requests. The value is passed through unchanged, no validation or case normalization is performed.

```sh
export CONSILIUM_MODEL_THINKING_KEEP="all"
```

Empty string or unset means the field is omitted from the request (current default behavior). The override only applies when the model is actually in thinking mode; it is ignored for non-thinking runs so the API never receives a `thinking.keep` without the companion `thinking.type`.

This parameter only takes effect on Moonshot models that support Preserved Thinking (e.g., `kimi-k2.6` / `kimi-k2-thinking`). Passing it to other models has no effect or may be rejected by the API; the CLI does not validate the model.

::: warning Cost
`thinking.keep=all` instructs the API to retain historical reasoning content across turns, which increases input tokens and therefore API cost. Only enable it when the preserved thinking behavior is required.
:::

## OpenAI-compatible environment variables

The following environment variables take effect when using `openai_legacy` or `openai_responses` type providers.

| Environment Variable | Description |
| --- | --- |
| `OPENAI_BASE_URL` | API base URL |
| `OPENAI_API_KEY` | API key |

### `OPENAI_BASE_URL`

Overrides the provider's `base_url` field in the configuration file.

```sh
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

### `OPENAI_API_KEY`

Overrides the provider's `api_key` field in the configuration file.

```sh
export OPENAI_API_KEY="sk-xxx"
```

## Other environment variables

| Environment Variable | Description |
| --- | --- |
| `CONSILIUM_SHARE_DIR` | Customize the share directory path (default: `~/.consilium`) |
| `CONSILIUM_CLI_NO_AUTO_UPDATE` | Disable all update-related features |
| `CONSILIUM_CLI_PASTE_CHAR_THRESHOLD` | Character threshold for folding pasted text (default: `1000`) |
| `CONSILIUM_CLI_PASTE_LINE_THRESHOLD` | Line threshold for folding pasted text (default: `15`) |

### `CONSILIUM_SHARE_DIR`

Customize the share directory path for Consilium CLI. The default path is `~/.consilium`, where configuration, sessions, logs, and other runtime data are stored.

```sh
export CONSILIUM_SHARE_DIR="/path/to/custom/kimi"
```

See [Data Locations](./data-locations.md) for details.

::: warning Note
`CONSILIUM_SHARE_DIR` does not affect [Agent Skills](../customization/skills.md) search paths. Skills are cross-tool shared capability extensions (compatible with Claude, Codex, etc.), which is a different type of data from application runtime data. To override Skills paths, use the `--skills-dir` flag.
:::

### `CONSILIUM_CLI_NO_AUTO_UPDATE`

When set to `1`, `true`, `t`, `yes`, or `y` (case-insensitive), disables all update-related features, including background auto-update check, the blocking update gate on startup, and the version hint in the welcome panel.

```sh
export CONSILIUM_CLI_NO_AUTO_UPDATE="1"
```

::: tip
If you installed Consilium CLI via Nix or other package managers, this environment variable is typically set automatically since updates are handled by the package manager.
:::

### `CONSILIUM_CLI_PASTE_CHAR_THRESHOLD`

In Agent mode, when pasted text exceeds this character count, it is folded into a placeholder (e.g., `[Pasted text #1 +10 lines]`) and expanded to full content on submit. Default: `1000`.

```sh
export CONSILIUM_CLI_PASTE_CHAR_THRESHOLD="1000"
```

### `CONSILIUM_CLI_PASTE_LINE_THRESHOLD`

In Agent mode, when pasted text reaches this line count, it is folded into a placeholder. Default: `15`.

```sh
export CONSILIUM_CLI_PASTE_LINE_THRESHOLD="15"
```

::: tip
Some terminals (e.g., XShell over SSH) may break CJK input methods (Chinese/Japanese/Korean IME) after pasting multiline text. Symptoms include the IME candidate window not appearing or input becoming unresponsive until Ctrl+C is pressed.

This happens because multiline text in the input buffer can confuse the terminal's cursor position tracking, which affects IME composition window placement. You can work around this by lowering the line threshold to fold multiline pastes into single-line placeholders:

```sh
export CONSILIUM_CLI_PASTE_LINE_THRESHOLD="2"
```

With this setting, any paste containing a newline will be automatically folded, preventing multiline text from entering the input buffer. Single-line pastes (URLs, short commands, etc.) are not affected.

Note: The two thresholds use OR logic (character count **or** line count), so lowering only the line threshold is sufficient. Avoid setting the character threshold to a very small value (e.g., `1`), as that would fold all non-empty pastes including single-line short text.
:::
