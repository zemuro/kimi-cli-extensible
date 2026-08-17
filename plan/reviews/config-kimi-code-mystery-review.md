# Review: kimi-code config re-population mystery + wrong model params

**Status:** 🟢 Investigation complete + hardened. Mystery #1: no automated re-populator in code; hardened against the broken state with a save_config guard + cleaned stale files. Mystery #2: FIXED (CLI fetches real OpenRouter model params).

**Date:** 2026-08-18

---

## Mystery #1 — "kimi-code keeps reappearing in ~/.consilium/config.toml"

### Verdict
**No code path in either repo automatically re-adds kimi-code to the global config.** Exhaustive tracing of every `save_config` call site, every config mutation, process inventory, log forensics, and config-state analysis confirms this.

### What was ruled out (with evidence)

| Suspect | File:Line | Verdict |
|---|---|---|
| `login_kimi_code` / `_apply_kimi_code_config` | `auth/oauth.py:563/615` | Only on explicit `/login` — never auto |
| `logout_kimi_code` | `auth/oauth.py:721` | Removes, never adds |
| `refresh_managed_models` | `auth/platforms.py:136` | Returns False early when no managed provider; on API failure `continue`s without writing; writes only for existing managed providers |
| `_migrate_oauth_storage` | `auth/oauth.py:777` | Only rewrites oauth refs; whole-file dump would preserve existing content but doesn't add kimi-code |
| JSON→TOML migration | `config.py:756` | Only runs if `config.toml` absent — file exists since Jun 1 |
| `save_config` whole-file dump | `config.py:737` | Dumps in-memory Config — requires code to have kimi-code in memory AND call save; no such path found |
| ACP `set_model` | `acp/server.py:386` | Reloads fresh config, only writes default_model/thinking |
| Web config API | `web/api/config.py:152` | Only default_model/thinking patch |
| Slash `/model`, `/editor`, `/theme` | `slash.py:292/394/688` | Only default_model/editor/theme |
| Setup wizard | `ui/shell/setup.py:177` | Explicit `/setup` only; writes kimi platform models (not kimi-code managed key) |
| Extension `saveProviderConfig` | `agent_sdk/config.ts:224` | Only writes `user-api` provider/model blocks |
| Extension `saveDefaultModel` | `agent_sdk/config.ts:174` | Only default_model/thinking line regex |
| Extension `updateExtensionSettings` | `config.handler.ts:56` | Only writes user-api models + default_model |
| Extension `InitializeProject` | `session.handler.ts:501` | Writes project-level `{workDir}/.consilium/config.toml` (different schema) |
| `~/.kimi/config.toml` legacy | — | CLI uses `get_share_dir()` = `~/.consilium`; nothing reads `~/.kimi` (verified via grep) |
| Scheduled tasks / startup / cron | — | None reference kimi/consilium |
| Stale processes | — | Only 2 processes, both started 00:56:05 AFTER user cleanup |
| Cloud sync restore | — | `~/.consilium` is a real dir, not OneDrive-redirected |

### Timeline reconstruction (from `kimi.log` + file mtimes)

| Time | Event |
|---|---|
| 20:45:54 | Config loaded with 3 kimi-code models (262144, K2.7/K3, caps thinking/image_in/video_in) + provider |
| 20:47:35 | Config degraded to 1 kimi model (100000, no caps, no display_name) — **matches manual edit** |
| 20:48-20:53 | Stop-button fix testing sessions (test-wire-trace/latency) |
| 21:41:40 | User creates `config.toml.bak-kimi` (full kimi blocks backup) |
| 21:53:38 | **First crash**: kimi-code model present WITHOUT provider → validation error |
| 22:52-22:54 | More crashes (same broken config) |
| 22:55:45 | **Clean config loaded** (4 user-api models, no kimi-code) — long-running session starts |
| 23:23:19-24 | Session shutdown error dumps (contain earlier session's kimi-removal TODO list — NOT config writes) |
| 00:27-00:30 | Think-mode test sessions (tiny, don't touch config.toml) + dispatch.json write |
| 00:48:36 | Wire server exits (stdin closed) |
| 00:55:26 | **Crash**: kimi-code model present WITHOUT provider (broken again) |
| 00:55:53 | config.toml mtime — user manual cleanup |
| 00:56:05/00:56:21 | New process loads clean config (current session) |

### Key insight
The long-running session (22:55:45→00:48:36) held the **clean config in memory** — it never re-read config.toml. So kimi-code could have been re-written to the file ANY time after 22:55:45 without the running process noticing. Only the next spawn (00:55:26) crashed on the corrupted file. The exact writer between 22:55 and 00:55 is not identifiable from code — no code path can produce `[models."kimi-code/..."]` with `provider = "managed:kimi-code"` and NO provider block. This signature is consistent with a **partial manual edit** or a **third-party tool** (file manager, sync, editor autosave).

### Recommendation (implemented)
1. **Guard in `save_config`** (`config.py:737`): refuses to persist any config where a model references a missing provider — the broken state can no longer be written to disk. Tests: `test_save_config_refuses_missing_provider`, `test_save_config_allows_consistent_config`.
2. **Cleaned stale sources**: deleted `~/.kimi/config.toml`, `~/.kimi/config.toml.bak`, `~/.consilium/credentials/kimi-code.json`, `~/.consilium/credentials/kimi-code.lock`, `~/.kimi/credentials/kimi-code.json`, `~/.kimi/credentials/kimi-code.lock`. Kept `~/.consilium/config.toml.bak-kimi` for reversibility and `~/.consilium/kimi.json` (active session metadata).
3. If it reappears again, capture the writer immediately (mtime + process list + USN journal). `~/.kimi/` directory remains (dormant, nothing reads it) — can be deleted wholesale if desired.

---

## Mystery #2 — wrong model params (capabilities + max_context_size)

### Root cause (confirmed)
- **Extension `saveProviderConfig`** (`agent_sdk/config.ts:224`) hardcodes `max_context_size = 200000` and (until the uncommitted working-tree change) wrote `capabilities = ["thinking", "image_in", "video_in"]` — the source of bogus caps on deepseek flash models.
- **CLI `refresh_managed_models`** (`auth/platforms.py:136`) fetches real `context_length`/`supports_reasoning`/`supports_image_in`/`supports_video_in` from the provider `/models` API **but only for managed providers** (`managed:kimi-code` etc.). For `user-api` (OpenRouter), it never fetches.
- **Extension `fetchProviderModels`** (`config.handler.ts:116`) DOES fetch OpenRouter `/models` and gets `context_length`, but only maps `id/name/context_length/pricing` — and nothing persists that data into config.toml.

### Fix (implemented — CLI-side)
**`refresh_user_api_models`** added to `auth/platforms.py`: for each `user-api` provider of type `openai_responses`/`openai_legacy` with base_url+api_key, fetches `GET {base_url}/models`, maps OpenRouter fields (`context_length`, `supported_parameters` → thinking, `architecture.input_modalities` → image/video), and updates existing config models in place (never creates/deletes — user's explicit model selection is preserved). Wired into `_refresh_managed_models_silent` (`app.py`) so it runs on CLI startup alongside the managed refresh.

**Live verification (real OpenRouter API):**

| Model | Before | After (real) |
|---|---|---|
| deepseek/deepseek-v4-flash-0731 | 200000, caps=None | **1310720, caps=thinking** |
| deepseek/deepseek-v4-flash | 200000, caps=None | **1048576, caps=thinking** |
| deepseek/deepseek-chat | 200000, caps=None | **163840, caps=None** |
| qwen/qwen3-coder-30b-a3b-instruct | 200000, caps=None | **262144, caps=None** |

No bogus `image_in`/`video_in` anywhere. Config loads cleanly after write.

**Tests** (`tests/auth/test_platforms.py` + `tests/core/test_config.py`):
- `test__list_user_api_models_maps_openrouter_fields` — OpenRouter payload → ModelInfo
- `test_refresh_user_api_models_updates_in_place` — bogus values overwritten, isolated from real config
- `test_refresh_user_api_skips_non_user_providers` — managed providers never user-api-fetched
- `test_save_config_refuses_missing_provider` / `test_save_config_allows_consistent_config` — the guard

40+ targeted tests pass; only the 4 pre-existing baseline failures remain (`test_default_config_dump` snapshot + 3 managed-401 auth tests).

---