# Phase 03: Refactor LLM and Configuration Defaults

## Goal
Generalize the LLM and configuration layers so they do not contain hardcoded assumptions about Kimi LLM or its parent company, Moonshot.

## Tasks
- [x] In `src/consilium/llm.py`:
  - Rename `_kimi_default_headers` to a more generic name (e.g., `_default_headers`).
  - Refactor model capability parsing in `derive_model_capabilities` so it doesn't rely solely on hardcoded string matching for `"kimi-for-coding"`.
  - Ensure the fallback config generation works cleanly for generic OpenAI-compatible providers.
- [x] In `src/consilium/config.py`:
  - Rename `MoonshotSearchConfig` and `MoonshotFetchConfig` classes and their usage in the `Services` block to a more generic naming scheme (e.g. `WebSearchConfig`, `WebFetchConfig`).
- [x] Test LLM initialization to verify it cleanly defaults without these hardcoded values.
