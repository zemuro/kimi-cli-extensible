# Phase 10 — Model Modality Capability Detection & `/media` Slash Command

## 1. Executive Summary

This phase implements automatic model modality capability detection (parsing `image_in` / `image->text` support from OpenAI/OpenRouter model metadata APIs) and provides an explicit `/media` slash command in Consilium CLI.

### Problem Statement
When using text-only LLM models (such as `deepseek/deepseek-v4-flash`), any historical or incoming `{"type": "image_url", ...}` content blocks in session messages cause OpenRouter / OpenAI endpoints to reject API calls with HTTP 404:
`No endpoints found that support image input`.

### Solution
1. **Automatic Modality Detection**: Automatically query and parse model metadata capabilities (`image_in`, `video_in`, modality fields). If the active model does not support image input, dynamically strip `image_url` content blocks from prompt payloads before sending.
2. **Slash Command Control**: Provide a `/media` (and `/vision`) slash command allowing users to manually view capability status (`/media status`), force toggle media input (`/media on|off`), or strip accumulated image attachments from the active session transcript (`/media clear`).

---

## 2. Proposed Implementation Details

### 2.1 Capability Detection & Model Metadata Parsing
- **Location**: `src/consilium/llm/` (provider registry & model options).
- **Behavior**:
  - Fetch model capability metadata from OpenRouter (`/api/v1/models`) or OpenAI model endpoints.
  - Set `supports_image_input: bool` on the active model configuration object.
  - In message payload builder (`_build_messages_payload`):
    - If `supports_image_input == False`, sanitize content arrays by filtering out items of type `image_url`.

### 2.2 `/media` Slash Command Registry
- **Location**: `src/consilium/slash_commands/`
- **Command Syntax**:
  - `/media status` — Display active model capability and media filter status.
  - `/media off` / `/media disable` — Explicitly disable image/media sending for all prompt turns.
  - `/media on` / `/media enable` — Enable image/media payload sending (for vision-capable models).
  - `/media clear` — Purge all historical `image_url` elements from active session memory.

---

## 3. Verification & Test Plan

1. **Unit Tests**: Add tests verifying `image_url` content blocks are stripped when `supports_image_input=False`.
2. **Slash Command Tests**: Verify `/media status`, `/media off`, `/media on`, and `/media clear` execute cleanly.
3. **E2E Test**: Test prompt execution with `deepseek/deepseek-v4-flash` to ensure zero 404 image routing errors occur.
