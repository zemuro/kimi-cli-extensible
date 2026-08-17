---
document_type: phase_spec
phase: 10
title: Model Modality Capability Detection & Graceful Media Degradation
status: planning
created: 2026-07-27
author: Consilium
dependencies: []
acceptance_criteria_summary:
  - Graceful degradation: non-vision models strip image_url instead of crashing with LLMNotSupported
  - /media slash command registered in both Do and Think mode registries
  - Model capabilities heuristically inferred from provider metadata when available
  - User can explicitly enable/disable media via /media on|off
  - User can view current model capabilities via /media status
  - User can strip accumulated media from session via /media clear
  - Extension side auto-disables media upload UI when model lacks image_in
---

# Phase 10: Model Modality Capability Detection & Graceful Media Degradation

## 1. Executive Summary

### Problem Statement

When using text-only LLM models (such as `deepseek/deepseek-v4-flash` or `deepseek/deepseek-r1`), any `{"type": "image_url", ...}` content blocks in messages cause the API to reject the request. Currently, the system detects this via `check_message()` → `LLMNotSupported` exception, which **crashes the turn** rather than gracefully degrading.

Additionally, model capability detection (`image_in`, `video_in`, `thinking`) is purely heuristic (name-based matching), with no API-driven metadata fetching for OpenRouter or custom providers.

### Solution

1. **Graceful degradation in message payload building**: Instead of raising `LLMNotSupported` when a model lacks `image_in`, strip `ImageURLPart` and `VideoURLPart` content blocks from the message before sending, and inject a system note explaining that media was removed.

2. **`/media` slash command in both Do and Think modes**: Allow users to inspect capabilities, toggle media on/off, and clear accumulated media from session history.

3. **Improved capability detection**: Extend `derive_model_capabilities()` to use provider metadata where available, and improve heuristic coverage.

---

## 2. Detailed Design

### 2.1 Task 1: Graceful Degradation in `check_message()` or Payload Builder

**Effort:** 2 hours

**Files:**
- `src/consilium/soul/message.py` — `check_message()`
- `packages/kosong/src/kosong/message.py` — `Message` class, `_serialize_content()`

**Current behavior:**

```python
# src/consilium/soul/message.py (approx line 80-92)
def check_message(message: Message, capabilities: set[ModelCapability]) -> set[ModelCapability]:
    missing: set[ModelCapability] = set()
    for part in message.content:
        if isinstance(part, ImageURLPart) and "image_in" not in capabilities:
            missing.add("image_in")
        if isinstance(part, VideoURLPart) and "video_in" not in capabilities:
            missing.add("video_in")
    return missing  # caller raises LLMNotSupported
```

**Desired behavior:**

```python
def strip_unsupported_media(
    message: Message,
    capabilities: set[ModelCapability],
) -> tuple[Message, bool]:
    """Strip media parts not supported by the model. Returns (stripped_message, was_modified)."""
    if "image_in" in capabilities and "video_in" in capabilities:
        return message, False  # fast path: no stripping needed

    new_content: list[ContentPart] = []
    stripped_count = 0
    for part in message.content:
        if isinstance(part, ImageURLPart) and "image_in" not in capabilities:
            stripped_count += 1
            continue
        if isinstance(part, VideoURLPart) and "video_in" not in capabilities:
            stripped_count += 1
            continue
        new_content.append(part)

    if stripped_count == 0:
        return message, False

    # If stripping leaves an empty content array, inject a placeholder
    # so the API doesn't reject with a 400 Bad Request.
    if not new_content:
        new_content = [TextPart(text="[System: An unsupported media file was removed from this message]")]
    else:
        # Prepend a system note about the stripping
        note = TextPart(text=f"[System: Removed {stripped_count} media attachment(s) — current model does not support {', '.join(
            cap for cap in ['image_in', 'video_in'] if cap not in capabilities
        ).replace('_in', '')} input.]")
        new_content.insert(0, note)

    return Message(role=message.role, content=new_content), True
```

**Integration points:**
- `src/consilium/soul/consiliumsoul.py` — before calling `kosong.step()`, strip the messages
- `src/consilium/wire/server.py` — same for wire mode
- `src/consilium/acp/session.py` — same for ACP mode

The `LLMNotSupported` exception is still raised only when the model lacks a capability that is **required** for the task (e.g., user explicitly asks to analyze an image and the model can't do it). Stripping is for cases where media is incidental (e.g., from history).

### 2.2 Task 2: `/media` Slash Command

**Effort:** 3 hours

**Files:**
- `src/consilium/soul/slash.py` — register in Do mode registry
- `src/consilium/think/slash.py` — register in Think mode registry

**Do mode implementation** (in `soul/slash.py`):

```python
@registry.command(name="media", aliases=["vision"])
async def media(soul: ConsiliumSoul, args: str):
    """Control media/image handling. Usage: /media status|on|off|clear"""
    subcmd = args.strip().lower()

    if subcmd == "status":
        caps = soul._llm.capabilities if soul._llm else set()
        media_enabled = getattr(soul._runtime, "_media_enabled", True)
        lines = [
            f"Model: {soul._llm.model_name if soul._llm else 'N/A'}",
            f"Image input: {'✅' if 'image_in' in caps else '❌'}",
            f"Video input: {'✅' if 'video_in' in caps else '❌'}",
            f"Media sending: {'✅ Enabled' if media_enabled else '❌ Disabled'}",
        ]
        wire_send(TextPart(text="\n".join(lines)))
        return

    if subcmd in ("off", "disable"):
        soul._runtime._media_enabled = False
        wire_send(TextPart(text="Media sending disabled. Images will be stripped from all turns."))
        return

    if subcmd in ("on", "enable"):
        soul._runtime._media_enabled = True
        wire_send(TextPart(text="Media sending enabled."))
        return

    if subcmd == "clear":
        # Strip all ImageURLPart/VideoURLPart from session history
        removed = 0
        new_history = []
        for msg in soul.context.history:
            if hasattr(msg, 'content') and isinstance(msg.content, list):
                old_len = len(msg.content)
                msg.content = [p for p in msg.content if not isinstance(p, (ImageURLPart, VideoURLPart))]
                removed += old_len - len(msg.content)
            new_history.append(msg)
        soul.context.history = new_history
        wire_send(TextPart(text=f"Cleared {removed} media attachment(s) from session history."))
        return

    wire_send(TextPart(text="Usage: /media [status|on|off|clear]"))
```

**Think mode implementation** (in `think/slash.py`):

```python
@think_registry.command(name="media", aliases=["vision"])
async def slash_media(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Control media/image handling. Usage: /media status|on|off|clear"""
    from consilium.think import get_think_soul

    soul = get_think_soul(session.id)
    if soul is None:
        return "ThinkSoul not found in registry."

    subcmd = args.strip().lower()

    if subcmd == "status":
        caps = soul._llm.capabilities if soul._llm else set()
        media_enabled = getattr(soul._runtime, "_media_enabled", True)
        return (
            f"Model: {soul._llm.model_name if soul._llm else 'N/A'}\n"
            f"Image input: {'✅' if 'image_in' in caps else '❌'}\n"
            f"Video input: {'✅' if 'video_in' in caps else '❌'}\n"
            f"Media sending: {'✅ Enabled' if media_enabled else '❌ Disabled'}"
        )

    if subcmd in ("off", "disable"):
        soul._runtime._media_enabled = False
        return "Media sending disabled."

    if subcmd in ("on", "enable"):
        soul._runtime._media_enabled = True
        return "Media sending enabled."

    if subcmd == "clear":
        from kosong.message import ImageURLPart, VideoURLPart
        removed = 0
        for msg in session.messages:
            if hasattr(msg, 'content') and isinstance(msg.content, list):
                old_len = len(msg.content)
                msg.content = [p for p in msg.content if not isinstance(p, (ImageURLPart, VideoURLPart))]
                removed += old_len - len(msg.content)
        return f"Cleared {removed} media attachment(s) from session history."

    return "Usage: /media [status|on|off|clear]"
```

### 2.3 Task 3: Improved Capability Detection

**Effort:** 3 hours

**Files:**
- `src/consilium/llm.py` — `derive_model_capabilities()`
- `src/consilium/llm.py` — new `fetch_openrouter_capabilities()` function

**Current behavior:**
- Only name-based heuristics: "thinking" → thinking, "code" → image_in+video_in, etc.
- No API metadata fetching for OpenRouter

**Improvements:**

#### 3a. OpenRouter API Metadata Fetching

OpenRouter's `/api/v1/models` endpoint returns rich `architecture` metadata per model:

```json
{
  "id": "openai/gpt-4o",
  "architecture": {
    "modality": "text+image->text",
    "input_modalities": ["text", "image"],
    "output_modalities": ["text"]
  }
}
```

Add a function that fetches and caches this data:

```python
import requests

_MODALITY_CACHE: dict[str, set[str]] = {}

def fetch_openrouter_modalities(model_id: str, base_url: str | None) -> set[str] | None:
    """Return capabilities from OpenRouter metadata, or None if not available."""
    if not base_url or "openrouter" not in base_url.lower():
        return None
    if not _MODALITY_CACHE:
        try:
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            resp.raise_for_status()
            for model in resp.json().get("data", []):
                arch = model.get("architecture", {})
                mods = arch.get("input_modalities", ["text"])
                caps: set[str] = set()
                if "image" in mods:
                    caps.add("image_in")
                if "video" in mods:
                    caps.add("video_in")
                _MODALITY_CACHE[model["id"]] = caps
        except Exception:
            return None
    return _MODALITY_CACHE.get(model_id)
```

**Key design decisions:**
- Cache is in-memory, fetched once per CLI session (not per-call)
- Falls back gracefully to `None` on any error → heuristic or explicit config takes over
- Maps `input_modalities: ["image"]` → `image_in`, `["video"]` → `video_in`

#### 3b. Enhanced Heuristic Expansion

Expand `derive_model_capabilities()` to cover more common patterns, used as fallback when API fetch is unavailable:

| Pattern | Capability |
|---------|-----------|
| "vision" | image_in |
| "claude" + "3" | image_in (Claude 3+) |
| "gemini" | image_in |
| "gpt-4" | image_in (GPT-4-turbo+) |
| "gpt-4o" | image_in |
| "llama-3.2" | image_in |
| "pixtral" | image_in |
| "qwen" + "vl" | image_in |

#### 3c. Explicit Config.toml Capabilities

The `capabilities` field already exists in `LLMModel` — just document and use it. Explicit config overrides both API fetch and heuristic:

```toml
[models."deepseek/deepseek-v4-flash"]
capabilities = []  # explicitly no media support

[models."openai/gpt-4o"]
capabilities = ["image_in"]  # explicitly vision-capable
```

**Resolution order:**
1. Explicit `capabilities` in config.toml → highest priority
2. OpenRouter API metadata fetch → cached, session-scoped
3. Name-based heuristic → lowest priority

### 2.4 Task 4: Extension-Side Media UI Gating

**Effort:** 1.5 hours

**Files:**
- `kimi_extension_mod/webview-ui/src/components/inputarea/hooks/useMediaUpload.ts`
- `kimi_extension_mod/webview-ui/src/components/inputarea/InputArea.tsx`
- `kimi_extension_mod/shared/types.ts` — ExtensionConfig

**Changes:**
1. Add `modelCapabilities: string[]` to the `ExtensionConfig` interface (or derive from the model info sent during handshake)
2. In `useMediaUpload.ts`, check if the current model supports `image_in`/`video_in` before allowing media upload:
   ```typescript
   const canAddMedia = modelCapabilities.includes("image_in") || modelCapabilities.includes("video_in");
   const { canAddMedia: canAddMediaRaw, handlePaste, handlePickMedia } = useMediaUpload();
   // Override: if model doesn't support media, disable the button and paste handler
   ```
3. In `InputArea.tsx`, disable the `@` file mention for media files when the model lacks capability
4. Show a tooltip explaining why media upload is disabled

---

## 3. Files Modified

| File | Change |
|------|--------|
| `src/consilium/soul/message.py` | Add `strip_unsupported_media()` function; modify `check_message()` |
| `src/consilium/soul/consiliumsoul.py` | Call `strip_unsupported_media()` before kosong step |
| `src/consilium/wire/server.py` | Same stripping before wire payload |
| `src/consilium/acp/session.py` | Same stripping before ACP payload |
| `src/consilium/soul/slash.py` | Add `/media` command (Do mode) |
| `src/consilium/think/slash.py` | Add `/media` command (Think mode) |
| `src/consilium/llm.py` | Improve `derive_model_capabilities()` heuristics |
| `kimi_extension_mod/shared/types.ts` | Add `modelCapabilities` to ExtensionConfig |
| `kimi_extension_mod/webview-ui/src/components/inputarea/hooks/useMediaUpload.ts` | Gate media upload on model capabilities |
| `kimi_extension_mod/webview-ui/src/components/inputarea/InputArea.tsx` | Disable media buttons when model lacks support |

---

## 4. Verification

| Check | Method |
|-------|--------|
| Non-vision model receives image | `strip_unsupported_media()` strips it, injects system note, turn succeeds |
| `/media status` in Do mode | Shows model name, capabilities, enabled state |
| `/media status` in Think mode | Same |
| `/media off` | Subsequent turns strip all media |
| `/media clear` | Removes all media from session history |
| `/media on` | Restores media sending |
| Vision model receives image | No stripping, turn proceeds normally |
| Extension media button disabled for non-vision model | Tooltip explains why |
| `capabilities` in config.toml overrides heuristics | Manually tested |

---

## 5. Effort Estimate

| Task | Hours | Notes |
|------|-------|-------|
| Task 1: Graceful degradation | 2.0 | `strip_unsupported_media()` + integration points + empty-message placeholder |
| Task 2: `/media` slash command | 3.0 | Two registries, both implementations |
| Task 3: Improved capability detection | 3.0 | OpenRouter API fetch + cache, heuristic expansion, config.toml docs |
| Task 4: Extension media UI gating | 1.5 | `useMediaUpload.ts` + `InputArea.tsx` |
| **Total** | **9.5** | |

---

## 6. Deferred Items

| Item | Reason |
|------|--------|
| Per-message-type stripping (strip only from user messages, keep assistant tool results) | Current approach strips all media; refinement can be added later. |
| Visual indicator in webview header showing model capabilities | Nice-to-have; not required for functional fix. |
| ReadMediaFile tool fallback for non-vision models | Currently returns ToolError; could be changed to return text description. |
| OpenRouter server-side filtering (output_modalities param) | OpenRouter only supports `output_modalities` filtering server-side; `input_modalities` (image_in/video_in) still requires local parsing. Deferred as an optimization. |