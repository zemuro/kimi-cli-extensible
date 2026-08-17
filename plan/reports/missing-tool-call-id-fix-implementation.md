---
document_type: implementation_report
phase: N/A
title: Missing tool_call_id Fix — Implementation Report
author: plan_editor
completion_date: 2026-08-17
---

# Missing tool_call_id Fix — Implementation Report

## Summary

Fix for the 400 Bad Request error `Failed to deserialize the JSON body into the target type: messages[X]: missing field 'tool_call_id'` seen when routing through strict OpenRouter providers (e.g. GMICloud).

## Root Cause

- Trace of the full data flow showed that in normal operation `tool_result_to_message()` (`c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\soul\message.py`) DOES set `tool_call_id` from `ToolResult.tool_call_id`, and both provider `_convert_message` serializations emit it correctly.
- Two real defects were found:

  1. **`strip_unsupported_media()`** in `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\soul\message.py` rebuilt modified messages as `Message(role=message.role, content=new_content)` — silently **DROPPING** `tool_call_id` (and `tool_calls` for assistant messages). Any tool result containing media parts (screenshots, images from MCP tools) that got stripped on a text-only model lost its `tool_call_id`, producing exactly the "missing field 'tool_call_id'" 400.

  2. Both OpenAI-compatible providers silently coerced a missing ID to an empty string:
     - `openai_responses.py`: `call_id = message.tool_call_id or ""` → emits `"call_id": ""` which strict providers reject
     - `openai_legacy.py`: `model_dump(exclude_none=True)` would simply omit the field

   Neither surfaced a clear error — they just sent malformed payloads and let the API return an opaque 400.

## Changes

1. `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\soul\message.py` — `strip_unsupported_media()` now preserves `tool_call_id` and `tool_calls` when rebuilding a modified message (return value is now a tuple with a `Message` carrying both fields).

2. `c:\Users\zemuro\Antigravity\kimi_cli_mod\packages\kosong\src\kosong\contrib\chat_provider\openai_responses.py` — added `ChatProviderError` import; tool messages with missing `tool_call_id` now raise `ChatProviderError("Tool message is missing \`tool_call_id\`. ...")` instead of emitting `"call_id": ""`.

3. `c:\Users\zemuro\Antigravity\kimi_cli_mod\packages\kosong\src\kosong\contrib\chat_provider\openai_legacy.py` — added `ChatProviderError` import; same defensive validation before `model_dump`.

4. `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_soul_message.py` — added 3 regression tests:
   - `test_strip_unsupported_media_preserves_tool_call_id`: strip preserves tool_call_id
   - `test_strip_unsupported_media_preserves_assistant_tool_calls`: strip preserves assistant tool_calls
   - `test_strip_unsupported_media_fast_path_returns_original`: strip fast-path returns original message

## Test Results

- `tests/core/test_soul_message.py`: **27 passed** (24 existing + 3 new)
- `packages/kosong` tests (`test_message.py`, `test_tool_result.py`, `test_tool_call.py`): **29 passed**
- `packages/kosong` api_snapshot tests (`test_openai_legacy.py`, `test_openai_responses.py`): **15 passed**
- Manual verification script: 5 scenarios all passed (strip preserves ID, strip preserves assistant tool_calls, openai_responses raises on missing ID, valid exchange passes through with call_id, openai_legacy raises on missing ID)

## Delta from Spec

- The spec asked for data-structure/serialization changes. In addition to the defensive validation, the root-cause fix in `strip_unsupported_media` was necessary because that function was the only place where `tool_call_id` could be dropped in the live data path.
- The schema `{"role": "tool", "tool_call_id": "<id>", "content": "<result>"}` is already produced by `tool_result_to_message()`; the fix ensures no downstream transformation can remove the id and that a missing id surfaces as a clear provider error instead of a silent malformed payload.

## Files Modified

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\soul\message.py` | Modified — `strip_unsupported_media()` preserves `tool_call_id` and `tool_calls` |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\packages\kosong\src\kosong\contrib\chat_provider\openai_responses.py` | Modified — raise `ChatProviderError` on missing `tool_call_id` |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\packages\kosong\src\kosong\contrib\chat_provider\openai_legacy.py` | Modified — raise `ChatProviderError` on missing `tool_call_id` |
| `c:\Users\zemuro\Antigravity\kimi_cli_mod\tests\core\test_soul_message.py` | Modified — 3 new regression tests |

## Recommendation

🟢 **Ready** — fixes verified, tests pass. Commit message suggestion: `fix(soul): preserve tool_call_id in media stripping and validate tool messages`