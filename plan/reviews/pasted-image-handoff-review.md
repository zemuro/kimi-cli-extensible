# Review: Option B — pasted-image handoff for text-only models

**Status:** 🟢 Implemented, tested, live-verified. No regressions (full suite failures all pre-existing; passed count +16 from new tests).
**Date:** 2026-08-18

## What was built

When a user **pastes an image** into the chat and the **parent model is text-only** (no `image_in`), the image can't go to the parent. Instead of silently stripping it (previous behavior — the image was lost with only a system note), the new **Option B** flow:

1. Detects `ImageURLPart`(s) in the incoming user message (`_turn` in consiliumsoul.py, before the generic media strip)
2. Saves each pasted image (base64 data URL) to a temp file under `.consilium/media/paste-<ts>-<rand>.<ext>`
3. Spawns the **vision subagent** (`qwen/qwen3.7-flash`) pointing at that file — the subagent reads it via `ReadMediaFile` and returns a text analysis
4. Replaces the `ImageURLPart` with `[Vision analysis of pasted image]\n<analysis>` text — the parent sees only text

## Design notes

- **Subagent sees zero parent history** (by architecture — `prepare_soul` gives it only its own empty context + the prompt). This is fine: the vision model is a focused analyzer; the parent supplies context in the prompt.
- **Only base64 data URLs are handled** (webview sends pasted images as `data:image/...;base64,...`). Remote `http(s)` image URLs are left untouched (a future path could fetch those).
- **Guard**: only runs when parent is text-only. Vision-capable parents see images directly (no handoff).
- **Fallback**: if the vision subagent isn't registered or fails, the message is returned unchanged — the existing `strip_unsupported_media` still strips the image (no regression).
- **Sequential**: multiple pasted images analyzed one at a time (vision calls are costly).

## Files changed

| File | Change |
|---|---|
| `src/consilium/soul/media_handoff.py` (new) | `handle_pasted_images_in_turn`, `_decode_data_url`, `_save_pasted_image`, `_spawn_vision_for_image`, `_is_text_only`, `_extract_image_parts` |
| `src/consilium/soul/consiliumsoul.py` | `_turn`: call `handle_pasted_images_in_turn` before media strip |
| `tests/core/test_media_handoff.py` (new) | 16 tests |

## Verification

- 16/16 new tests pass (decode, extract, save, is_text_only, handoff replaces/skips/falls-back).
- Related suites (soul_message, retry_recovery, chat_provider_ext): 57 passed.
- Full `tests/core`: 1098 passed, 30 failed + 1 error — **all pre-existing** (identical list to baseline; passed count +16).
- Live simulation: pasted image → saved to `.consilium/media/paste-*.png` → vision analysis text replaces the image part in the user message.

## Notes

- The `.consilium/media/` scratch dir is created per-workdir; files are not auto-cleaned (could add TTL cleanup later).
- The webview's existing model auto-switch (InputArea.tsx:72) may switch to a vision model BEFORE this CLI logic runs — in that case the parent sees the image directly and this path is skipped. This handoff is the safety net for when a text-only model is deliberately kept.