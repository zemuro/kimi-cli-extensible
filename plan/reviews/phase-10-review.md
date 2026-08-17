---
document_type: review
phase: 10
title: Review — Phase 10 Model Modality Capability Detection & Graceful Media Degradation
author: Consilium
review_date: 2026-07-27
---

# Review — Phase 10: Model Modality Detection

## Scope

Graceful degradation when non-vision LLM models receive image/video content; /media slash command in both Do and Think modes; improved model capability detection heuristics; extension-side media UI gating.

## Files to Change

| File | Change |
|------|--------|
| `src/consilium/soul/message.py` | Add `strip_unsupported_media()` function |
| `src/consilium/soul/consiliumsoul.py` | Call strip before kosong step |
| `src/consilium/wire/server.py` | Call strip before wire payload |
| `src/consilium/acp/session.py` | Call strip before ACP payload |
| `src/consilium/soul/slash.py` | Add /media command |
| `src/consilium/think/slash.py` | Add /media command |
| `src/consilium/llm.py` | Improve `derive_model_capabilities()` heuristics |
| `kimi_extension_mod/shared/types.ts` | Add `modelCapabilities` to ExtensionConfig |
| `kimi_extension_mod/webview-ui/.../useMediaUpload.ts` | Gate media on model capabilities |
| `kimi_extension_mod/webview-ui/.../InputArea.tsx` | Disable media buttons when unsupported |

## Corrections from Original Spec

| # | Original Spec Said | Actual Design |
|---|-----------|--------|
| 1 | `src/consilium/slash_commands/` directory | Slash commands live in `soul/slash.py` and `think/slash.py` |
| 2 | `_build_messages_payload` function | Payload building is in kosong providers; stripping must happen at the message level before send |
| 3 | OpenRouter API fetching for model metadata | Now included — in-memory cache, fallback on error, resolution order: config > API > heuristic |

## Edge Cases

| Case | Handling |
|------|----------|
| Non-vision model receives image | Media stripped, system note injected, turn succeeds |
| Vision model receives image | No stripping, normal flow |
| `/media off` then send text with image | Image stripped, user informed via system note |
| `/media clear` on empty session | No-op, returns "0 removed" |
| Strip leaves empty message (image-only message to text-only model) | Placeholder text injected: "[System: An unsupported media file was removed from this message]" |
| Capability not in heuristic (unknown model) | User must set `capabilities` in config.toml |
| Extension reload after `/media off` | `_media_enabled` is runtime-only — resets to default on reload |
| OpenRouter API unavailable / timeout | Cache miss falls back to heuristic → graceful degradation |

## Verdict

🟢 Feasible — well-scoped, clear implementation targets, no architectural blockers.

## Implementation Order

1. `src/consilium/soul/message.py` — Add `strip_unsupported_media()`
2. `src/consilium/llm.py` — Improve heuristics
3. `src/consilium/soul/slash.py` + `think/slash.py` — Add /media command
4. `src/consilium/soul/consiliumsoul.py` — Integrate stripping
5. `src/consilium/wire/server.py` — Integrate stripping
6. `src/consilium/acp/session.py` — Integrate stripping
7. Extension side: types, useMediaUpload, InputArea