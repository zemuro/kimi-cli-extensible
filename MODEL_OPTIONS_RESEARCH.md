# Model Options Research Report

This document maps how LLM parameters flow from user input → config → API request in consilium.

---

## 1. Architecture Overview

```
User Input
    │
    ├── CLI args (--model, --thinking)
    ├── Config file (~/.consilium/config.toml)
    └── Environment variables (CONSILIUM_MODEL_*)
    │
    ▼
App.create_soul()  →  create_llm()  →  ChatProvider (kosong)
    │
    ▼
kosong.step()  →  chat_provider.generate()  →  Provider API call
```

The actual HTTP API call happens inside **kosong** chat provider classes. Each provider wraps a vendor-specific SDK (`openai`, `anthropic`, `google.genai`) and exposes a uniform `ChatProvider` protocol.

---

## 2. Provider Types & Supported Generation Parameters

### 2.1 Kimi (`kosong/chat_provider/kimi.py`)

Uses `AsyncOpenAI` client targeting Moonshot's API.

**GenerationKwargs** (what can be passed via `.with_generation_kwargs()`):

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `max_tokens` | `int \| None` | **32000** (hardcoded in `generate()`) | Output token limit |
| `temperature` | `float \| None` | — | Sampling temperature |
| `top_p` | `float \| None` | — | Nucleus sampling |
| `n` | `int \| None` | — | Number of completions |
| `presence_penalty` | `float \| None` | — | Presence penalty |
| `frequency_penalty` | `float \| None` | — | Frequency penalty |
| `stop` | `str \| list[str] \| None` | — | Stop sequences |
| `prompt_cache_key` | `str \| None` | — | Moonshot prompt caching |
| `reasoning_effort` | `str \| None` | — | Legacy thinking param |
| `extra_body` | `ExtraBody \| None` | — | For `thinking.keep` etc. |

**Special behavior:**
- **Hardcoded default:** `max_tokens=32000` is set inside `generate()` and then overlaid with `_generation_kwargs`.
- **Thinking:** Maps `with_thinking("high")` → `reasoning_effort="high"` + `extra_body.thinking.type="enabled"`.
- **Preserved thinking:** `CONSILIUM_MODEL_THINKING_KEEP=all` adds `extra_body.thinking.keep="all"` via `with_extra_body()`.

### 2.2 OpenAI Legacy (`kosong/contrib/chat_provider/openai_legacy.py`)

For OpenAI-compatible chat completions APIs.

**GenerationKwargs:**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `max_tokens` | `int \| None` | — | No hardcoded default |
| `temperature` | `float \| None` | — | |
| `top_p` | `float \| None` | — | |
| `n` | `int \| None` | — | |
| `presence_penalty` | `float \| None` | — | |
| `frequency_penalty` | `float \| None` | — | |
| `stop` | `str \| list[str] \| None` | — | |
| `prompt_cache_key` | `str \| None` | — | |

**Special behavior:**
- `reasoning_effort` is **not** in GenerationKwargs; it is a separate constructor-level field set via `with_thinking()`.
- Auto-enables `reasoning_effort="medium"` when history contains `ThinkPart` and no explicit reasoning was configured.

### 2.3 OpenAI Responses (`kosong/contrib/chat_provider/openai_responses.py`)

Uses OpenAI's newer Responses API.

**GenerationKwargs:**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `max_output_tokens` | `int \| None` | — | OpenAI Responses uses `max_output_tokens`, not `max_tokens` |
| `max_tool_calls` | `int \| None` | — | |
| `reasoning_effort` | `ReasoningEffort \| None` | — | Converted to `reasoning={effort, summary:"auto"}` + `include=["reasoning.encrypted_content"]` |
| `temperature` | `float \| None` | — | |
| `top_logprobs` | `float \| None` | — | |
| `top_p` | `float \| None` | — | |
| `user` | `str \| None` | — | |

### 2.4 Anthropic (`kosong/contrib/chat_provider/anthropic.py`)

Uses Anthropic's Messages API.

**GenerationKwargs:**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `max_tokens` | `int \| None` | **50000** (from `default_max_tokens` arg) | Required param |
| `temperature` | `float \| None` | — | |
| `top_k` | `int \| None` | — | |
| `top_p` | `float \| None` | — | |
| `thinking` | `ThinkingConfigParam \| None` | — | `{type: "enabled"\|"adaptive", budget_tokens: N}` |
| `output_config` | `OutputConfigParam \| None` | — | `{effort: "low"\|"medium"\|"high"\|"max"}` |
| `tool_choice` | `ToolChoiceParam \| None` | — | |
| `beta_features` | `list[str] \| None` | `["interleaved-thinking-2025-05-14"]` | Always injected unless adaptive thinking |
| `extra_headers` | `Mapping[str,str] \| None` | — | |

**Special behavior:**
- Thinking is **model-version-aware**: adaptive thinking for Opus 4.6+/Sonnet 4.6+/Mythos; legacy budget-based for older models.
- Effort clamping: `xhigh` only on Opus 4.7; `max` on 4.6+ family.
- Prompt caching via `cache_control=ephemeral` on system prompt, last message block, and last tool.

### 2.5 Google GenAI / Gemini (`kosong/contrib/chat_provider/google_genai.py`)

**GenerationKwargs:**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `max_output_tokens` | `int \| None` | — | |
| `temperature` | `float \| None` | — | |
| `top_k` | `int \| None` | — | |
| `top_p` | `float \| None` | — | |
| `thinking_config` | `ThinkingConfig \| None` | — | Gemini-specific thinking config |
| `tool_config` | `ToolConfig \| None` | — | |
| `http_options` | `HttpOptions \| None` | — | |

---

## 3. How Options Flow: The Full Pipeline

### 3.1 CLI Arguments (`src/consilium/cli/__init__.py`)

Only two model-related CLI options exist:

| CLI Flag | Maps To |
|---|---|
| `--model`, `-m` | `model_name` parameter to `App.create_soul()` |
| `--thinking` / `--no-thinking` | `thinking` parameter to `App.create_soul()` |

**There are NO CLI flags for** `temperature`, `top_p`, `max_tokens`, `presence_penalty`, etc.

### 3.2 Config File (`src/consilium/config.py`)

Generation parameters are configured per-model under `[models.X.generation]`:

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

| Config Field | Type | Purpose |
|---|---|---|
| `default_model` | `str` | Alias key into `config.models` |
| `default_thinking` | `bool` | Default thinking mode |
| `models` | `dict[str, LLMModel]` | Model definitions |
| `providers` | `dict[str, LLMProvider]` | Provider definitions |

`LLMModel.generation` (`GenerationConfig`) contains:
- `temperature`, `top_p` — all providers
- `max_tokens` — kimi, openai_legacy, anthropic
- `max_output_tokens` — openai_responses, gemini (with `max_tokens` fallback)
- `presence_penalty`, `frequency_penalty`, `stop`, `n` — kimi, openai_legacy
- `top_k` — anthropic, gemini
- `max_tool_calls`, `top_logprobs`, `user` — openai_responses
- `tool_choice`, `extra_headers` — anthropic

### 3.3 Environment Variables (`src/consilium/llm.py`)

**Only the Kimi provider** reads generation-related env vars. These are applied at LLM creation time in `create_llm()`:

| Env Var | Provider | Parameter | Type |
|---|---|---|---|
| `CONSILIUM_MODEL_NAME` | Kimi | `model.model` | string |
| `CONSILIUM_MODEL_MAX_CONTEXT_SIZE` | Kimi | `model.max_context_size` | int |
| `CONSILIUM_MODEL_CAPABILITIES` | Kimi | `model.capabilities` | comma-separated strings |
| `CONSILIUM_MODEL_TEMPERATURE` | Kimi | `gen_kwargs["temperature"]` | float |
| `CONSILIUM_MODEL_TOP_P` | Kimi | `gen_kwargs["top_p"]` | float |
| `CONSILIUM_MODEL_MAX_TOKENS` | Kimi | `gen_kwargs["max_tokens"]` | int |
| `CONSILIUM_MODEL_THINKING_KEEP` | Kimi | `extra_body.thinking.keep` | string |

**OpenAI, Anthropic, and Gemini providers do NOT read any generation-related environment variables.**

### 3.4 Provider Connection / URL / Auth Env Vars

| Env Var | Provider | Purpose |
|---|---|---|
| `CONSILIUM_BASE_URL` | Kimi | API base URL |
| `CONSILIUM_API_KEY` | Kimi | API key |
| `OPENAI_BASE_URL` | openai_legacy / openai_responses | API base URL |
| `OPENAI_API_KEY` | openai_legacy / openai_responses | API key |

---

## 4. Hardcoded Values

| Value | Location | Provider | Context |
|---|---|---|---|
| `max_tokens=32000` | `kosong/chat_provider/kimi.py:165` | Kimi | Default output token limit in `generate()` |
| `default_max_tokens=50000` | `src/consilium/llm.py:186` | Anthropic | Passed to Anthropic constructor |
| `stream=True` | all providers' `__init__` | all | Streaming is always enabled |
| `stream_options={"include_usage": True}` | `kimi.py:175`, `openai_legacy.py:147` | Kimi, OpenAI Legacy | Always sent when streaming |
| `store=False` | `openai_responses.py:185` | OpenAI Responses | Hardcoded |
| `error_probability=0.8` | `src/consilium/llm.py:235` | `_chaos` | Test provider |
| `thinking.type="enabled"` | `kimi.py:210` | Kimi | When thinking is on |
| `thinking.display="summarized"` | `anthropic.py:391` | Anthropic | For adaptive thinking models |
| `beta_features=["interleaved-thinking-2025-05-14"]` | `anthropic.py:252` | Anthropic | Default beta header |

---

## 5. Model Selection Flow

```
1. CLI: --model <alias>  (optional)
2. App.create_soul():
   a. If model_name given and in config.models → use it
   b. Else if config.default_model set → use it
   c. Else → empty LLMModel (provider="", model="", max_context_size=100_000)
3. create_llm(provider, model):
   a. Look up provider from config.providers[model.provider]
   b. Apply env var overrides (CONSILIUM_MODEL_NAME, etc.)
   c. Instantiate ChatProvider subclass
   d. Apply generation kwargs from config (`model.generation`) + env var overrides
   e. Apply thinking mode
```

---

## 6. Thinking Mode

Thinking is treated as a **first-class concept** across the codebase:

| Source | Value | Applied Where |
|---|---|---|
| `config.default_thinking` | `bool` | Default if CLI doesn't specify |
| CLI `--thinking` / `--no-thinking` | `bool \| None` | Overrides config default |
| Model name heuristic | auto-detected | `derive_model_capabilities()`: `"thinking"` or `"reason"` in model name → `always_thinking` |
| `kimi-for-coding` / `kimi-code` | auto-detected | Gets `thinking`, `image_in`, `video_in` capabilities |

`create_llm()` calls `chat_provider.with_thinking(effort)` where effort is:
- `"high"` if thinking is enabled and model supports it
- `"off"` if thinking is explicitly disabled
- Left untouched if thinking is `None`

Each provider maps `ThinkingEffort` to its native API representation:
- **Kimi:** `reasoning_effort` + `extra_body.thinking.type`
- **OpenAI Legacy:** `reasoning_effort` top-level param
- **OpenAI Responses:** `reasoning_effort` → `reasoning={effort, summary:"auto"}`
- **Anthropic:** adaptive vs legacy budget-based depending on model version
- **Gemini:** `thinking_config.thinking_level` or `thinking_budget`

---

## 7. Streaming

All providers default to `stream=True`. The `generate()` method returns a `StreamedMessage` (async iterator over message parts). Streaming options:

- **Kimi & OpenAI Legacy:** `stream_options={"include_usage": True}` — requests token usage in stream
- **OpenAI Responses:** native streaming via `client.responses.create(stream=True)`
- **Anthropic:** native streaming via `client.messages.create(stream=True)`
- **Gemini:** native streaming

---

## 8. Key Observations

1. **Per-model generation config is supported** via `[models.X.generation]` in `config.toml`. See `src/consilium/config.py` for the full schema.

2. **Env vars are Kimi-only overrides:** `CONSILIUM_MODEL_TEMPERATURE`, `CONSILIUM_MODEL_TOP_P`, `CONSILIUM_MODEL_MAX_TOKENS` still work and override config values for the Kimi provider. OpenAI, Anthropic, and Gemini users must use the config file.

3. **`max_tokens` default varies by provider:**
   - Kimi: 32000 (hardcoded)
   - Anthropic: 50000 (passed at construction)
   - OpenAI Legacy: none (relies on API default)
   - OpenAI Responses: none
   - Gemini: none

4. **`max_context_size` is purely client-side:** It drives compaction and context window management but is **never sent to the API**. The API has its own internal limits.

5. **`reserved_context_size` (default 50000):** A client-side buffer. When `context_tokens + reserved_context_size >= max_context_size`, auto-compaction triggers. This effectively reserves 50K tokens for the model's output.

---

## 9. File Reference Map

| File | Responsibility |
|---|---|
| `src/consilium/llm.py` | `create_llm()`, env var application, thinking logic, provider instantiation |
| `src/consilium/config.py` | `Config`, `LLMModel`, `LLMProvider` Pydantic models |
| `src/consilium/cli/__init__.py` | CLI arg parsing (`--model`, `--thinking`) |
| `src/consilium/app.py` | `App.create_soul()` — wires config + CLI args → `create_llm()` |
| `src/consilium/soul/kimisoul.py` | Agent loop, calls `kosong.step()` with the chat provider |
| `packages/kosong/src/kosong/_generate.py` | `generate()` — orchestrates streaming, tool calls |
| `packages/kosong/src/kosong/__init__.py` | `step()` — single agent step wrapper |
| `packages/kosong/src/kosong/chat_provider/kimi.py` | Kimi API provider |
| `packages/kosong/src/kosong/contrib/chat_provider/openai_legacy.py` | OpenAI Chat Completions provider |
| `packages/kosong/src/kosong/contrib/chat_provider/openai_responses.py` | OpenAI Responses provider |
| `packages/kosong/src/kosong/contrib/chat_provider/anthropic.py` | Anthropic Messages provider |
| `packages/kosong/src/kosong/contrib/chat_provider/google_genai.py` | Google Gemini provider |

---

## 10. OpenRouter Configuration Example

To configure OpenRouter models, define a custom provider using the `openai_responses` provider type in `~/.consilium/config.toml`. Specify the custom base URL and pass the required OpenRouter headers (`HTTP-Referer` and `X-Title`) via `custom_headers`:

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
