# Rename Plan: kimi-cli-extensible → Consilium

**Status:** DEFERRED — per `plan/reports/rename-consilium-review.md`  
**Estimated effort:** 2–3 days (review says Phase A alone is a full day due to 2,977 references)  
**Risk:** Medium — touches every file in the project  
**Rollback:** Revert single commit  
**When to execute:** After Phase 11+ functional work is complete

---

## Executive Summary

Rename the project from `kimi-cli-extensible` (package `kimi_cli`) to **Consilium** (package `consilium`). The upstream `kimi-cli` branding no longer reflects the fork's scope. This plan covers package names, imports, CLI commands, config paths, class names, user-facing strings, and migration strategy.

**Principle:** Clean break. Zero users means zero backward compatibility obligations. Rename everything in one commit.

**Review:** `plan/reports/rename-consilium-review.md` identifies 2,977 references, 12 gaps, and 5 risks. Key recommendation: **defer until Phase 11+ functional work is complete.**

---

## 1. Package & Module Rename

### 1.1 Directory structure

```
src/kimi_cli/              → src/consilium/
src/kimi_cli/cli/          → src/consilium/cli/
src/kimi_cli/do/           → src/consilium/do/
src/kimi_cli/plan/         → src/consilium/plan/
src/kimi_cli/soul/         → src/consilium/soul/
src/kimi_cli/subagents/    → src/consilium/subagents/
src/kimi_cli/think/        → src/consilium/think/
src/kimi_cli/ui/           → src/consilium/ui/
src/kimi_cli/utils/        → src/consilium/utils/
src/kimi_cli/web/          → src/consilium/web/
src/kimi_cli/wire/         → src/consilium/wire/
src/kimi_cli/prompts/      → src/consilium/prompts/
```

**Command:** `git mv src/kimi_cli src/consilium`

**Note:** `git mv` preserves history. Do NOT `rm` + `mkdir` + `cp`.

**Also rename:** `src/kimi_cli/__main__.py` → `src/consilium/__main__.py` (entry point).

### 1.2 Internal package references

All `from kimi_cli...` and `import kimi_cli...` statements across:
- `src/consilium/**/*.py`
- `tests/**/*.py`
- `tests_e2e/**/*.py`
- `tests_ai/**/*.py`
- `scripts/*.py`
- `examples/**/*.py`
- `web/` (if any Python files)

**Regex replacements:**
```
^from kimi_cli\.          → from consilium.
^import kimi_cli           → import consilium
kimi_cli\.                 → consilium.
```

**Files to scan:**
```bash
grep -rl "kimi_cli" src/ tests/ tests_e2e/ tests_ai/ scripts/ examples/ --include="*.py"
```

**Scale:** 2,977 references (per review). Not a quick task.

---

## 2. Build System & Packaging

### 2.1 `pyproject.toml`

| Field | Current | New |
|-------|---------|-----|
| `[project].name` | `kimi-cli` | `consilium` |
| `[project.scripts].kimi` | `kimi_cli.cli:main` | `consilium.cli:main` |
| `[project.scripts].consilium` | *(none)* | `consilium.cli:main` |
| `[project.urls].Homepage` | `github.com/zemuro/kimi-cli-extensible` | `github.com/zemuro/consilium` |
| `[tool.hatch.build.targets.wheel].packages` | `["src/kimi_cli"]` | `["src/consilium"]` |
| `[tool.uv.sources.kimi-cli]` | path = "packages/kosong" | remove or rename |

### 2.2 `packages/kosong/` dependency

The `kosong` package is an internal dependency specified as:
```toml
[tool.uv.sources]
kimi-cli = { path = "packages/kosong" }
```

**Decision needed:** Is `kosong` still sourced as a path dependency under the old name? Update the source key if uv references it by package name.

### 2.3 `README.md` and `docs/`

Update all references:
- "Kimi CLI" → "Consilium"
- "kimi-cli" → "consilium"
- "kimi_cli" → "consilium"
- GitHub URLs

---

## 3. CLI Entry Point

### 3.1 CLI command

```toml
[project.scripts]
consilium = "consilium.cli:main"
```

No `kimi` alias. No deprecation shim. Clean break.

### 3.2 Help text & banner

Update `src/consilium/cli/__init__.py`:
- Program name in Typer app: `"consilium"`
- Banner text: "Consilium — AI-assisted software engineering"
- Version string

---

## 4. Config & Data Paths

### 4.1 New default paths

| Purpose | Old | New |
|---------|-----|-----|
| Config dir | `~/.kimi/` | `~/.consilium/` |
| Session storage | `~/.kimi/sessions/` | `~/.consilium/sessions/` |
| Plans (upstream) | `~/.kimi/plans/` | `~/.consilium/plans/` |
| Think outbox | `~/.kimi/think_outbox/` | `~/.consilium/think_outbox/` |
| Dispatch | `~/.kimi/dispatch.json` | `~/.consilium/dispatch.json` |
| Token logs | `~/.kimi/token_usage/` | `~/.consilium/token_usage/` |

### 4.2 Path constants to update

Search for hardcoded path segments:
```bash
grep -rn "\.kimi" src/consilium/ --include="*.py"
```

Key files:
- `src/consilium/session.py` — `SESSIONS_DIR`
- `src/consilium/think/storage.py` — think session paths
- `src/consilium/think/push.py` — `OUTBOX_DIR`
- `src/consilium/plan/dispatch.py` — `DISPATCH_PATH`
- `src/consilium/token_tracker.py` — log directory
- `src/consilium/config.py` — default config path

### 4.3 Migration strategy

**Decision:** No migration. Zero users means no data to migrate.

`~/.consilium/` is created fresh on first run. If a developer (you) has old `~/.kimi/` data, manually copy it once if needed.

---

## 5. Class & Variable Rename

### 5.1 Core classes

| Current | New | File |
|---------|-----|------|
| `KimiSoul` | `ConsiliumSoul` | `soul/kimisoul.py` → `soul/consilium_soul.py` |
| `KimiCLI` | `ConsiliumCLI` | `cli/__init__.py` or app factory |
| `KimiRuntime` | `ConsiliumRuntime` | `soul/runtime.py` if exists |

**Note:** `git mv` preserves blame history, so rename `kimisoul.py` to `consilium_soul.py` (or `soul.py`). Do not keep the old filename with the new class name — that's confusing.

### 5.2 Variable names

Search for camelCase variables:
```bash
grep -rn "kimiSoul\|kimiCLI\|kimiRuntime" src/ tests/ --include="*.py"
```

### 5.3 String literals

Search for user-facing strings:
```bash
grep -rni "kimi" src/consilium/ --include="*.py" | grep -v "# kimi" | grep -v "kosong" | head -50
```

Categories:
- Log messages: `"KimiSoul started"` → `"ConsiliumSoul started"`
- Error messages: `"Kimi CLI error"` → `"Consilium error"`
- Wire events: Status text, UI labels
- Prompts: `src/consilium/prompts/think_system.md` — check for "Kimi" references

---

## 6. Test Updates

### 6.1 Import paths

All test files need import updates:
```python
# Before
from kimi_cli.token_tracker import TokenTracker
from kimi_cli.think.models import ThinkSession

# After
from consilium.token_tracker import TokenTracker
from consilium.think.models import ThinkSession
```

### 6.2 Test fixtures & paths

Tests that assert on paths or config locations:
- `test_config.py` — default config path assertions
- `test_think_storage.py` — session directory paths
- `test_dispatch.py` — dispatch file path

### 6.3 Snapshot tests

Any tests using `pytest-snapshot` or file-based golden masters that contain "kimi" strings may need regeneration.

---

## 7. Documentation Updates

### 7.1 `plan/` documents

All `plan/phase-*.md` and `plan/index.md` contain references to `kimi-cli`, `kimi_cli`, `KimiSoul`, etc. Update:
- Project name in frontmatter
- File path references (`src/kimi_cli/...` → `src/consilium/...`)
- Class names in implementation details

### 7.2 `docs/` (human-facing)

- `docs/AGENTS.md` — update project name, CLI commands
- `docs/BEST_PRACTICES.md` — update references
- `README.md` — full rewrite of name/branding
- `ROADMAP.md` — update

### 7.3 `scratch/` (ephemeral)

Not tracked in git. Can be updated lazily or left as historical artifacts.

---

## 8. Additional Directories (from review)

### 8.1 `examples/`

Directory renames needed:
- `examples/custom-kimi-soul/` → `examples/custom-consilium-soul/`
- `examples/kimi-cli-stream-json/` → `examples/consilium-stream-json/`
- `examples/kimi-cli-wire-messages/` → `examples/consilium-wire-messages/`
- `examples/kimi-psql/` → `examples/consilium-psql/`

Plus import updates and README updates inside each example.

### 8.2 `packages/`

- `packages/kimi-code/` → `packages/consilium-code/` (directory rename)
- Check `packages/*/pyproject.toml` for cross-references
- Check root `pyproject.toml` workspace table for member names

### 8.3 `sdks/`

- `sdks/kimi-sdk/` → `sdks/consilium-sdk/` (directory rename)
- Check internal references in SDK source

### 8.4 `vis/` frontend

- Check `vis/package.json` for name field and build scripts
- Check source for wire protocol type strings, API paths, branding
- Check `vis/` README for project name references

### 8.5 `klips/`

Kimi CLI Improvement Proposals contain the project name on every page. **Decision:** Archive as historical artifacts (do not update) or bulk-replace "Kimi CLI" → "Consilium". Recommend archive — they document upstream-era decisions.

### 8.6 `.agents/skills/`

- `.agents/skills/kimi-cli-help/` → `.agents/skills/consilium-help/`
- Check `skill-creator` skill for kimi-specific guidance
- Update `SKILL.md` files that reference CLI commands or paths

### 8.7 `.gitignore`

Root `.gitignore` and nested `.gitignore` files may contain:
- `.kimi/`
- `kimi_sessions/`
- `kimi_*/`

Audit all `.gitignore` files and update patterns.

### 8.8 `AGENTS.md` files

Root `AGENTS.md` and any nested `.agents/**/AGENTS.md` files contain:
- `kimi_cli` paths
- `KimiSoul` references
- CLI command names

Scan all `AGENTS.md` files recursively.

---

## 9. External Integrations

### 9.1 Wire protocol (audit separately)

`src/consilium/wire/types.py` and `wire/server.py` may contain protocol identifiers like `"kimi"`. **Do not bulk-replace inside `wire/` without understanding the protocol contract** — these identifiers may be consumed by the VS Code: extension or other wire consumers.

**Action:** Audit `wire/` in isolation. List every string literal containing `"kimi"` and decide per-case.

### 8.2 GitHub Actions / CI

Check `.github/workflows/` for:
- Package name in `uv pip install -e .` steps
- PyPI publish target name
- Artifact names and cache keys referencing `kimi`
- Job IDs and step names

### 8.3 `scripts/`, `Makefile`, `.pre-commit-config.yaml`

Any helper scripts that invoke `kimi` or reference `kimi_cli`:
```bash
grep -rn "kimi" scripts/ --include="*.py" --include="*.sh"
grep -rn "kimi" Makefile .pre-commit-config.yaml 2>/dev/null
```

---

## 10. Implementation Order

**Pre-flight:**
0. `git tag pre-rename` at current `main` HEAD
0. Ensure all tests pass, no open feature branches

**Phase A — Mechanical (Day 1)**
1. `git mv src/kimi_cli src/consilium`
2. Rename `src/consilium/soul/kimisoul.py` → `consilium_soul.py`
3. Bulk replace imports (`kimi_cli` → `consilium`)
4. Update `pyproject.toml` (package name, scripts, workspace members)
5. Update `examples/`, `packages/kimi-code/`, `sdks/kimi-sdk/` names
6. Run tests, fix import errors

**Phase B — Paths & Config (Day 1–2)**
7. Update `~/.kimi/` → `~/.consilium/` in all path constants
8. Update `.gitignore` entries
9. Update test fixtures and path assertions
10. Run tests

**Phase C — Classes & Strings (Day 2)**
11. Rename core classes (`KimiSoul` → `ConsiliumSoul`)
12. Update variable names
13. Update user-facing strings (logs, errors, help text, prompts)
14. Run tests

**Phase D — Docs & Polish (Day 2–3)**
15. Update `plan/` documents
16. Update `docs/AGENTS.md`, `README.md`, `ROADMAP.md`
17. Update `klips/`, `.agents/skills/`
18. Update CLI banner and version strings
19. Final test run
20. Commit
21. Archive this document to `plan/archive/rename-consilium.md`

---

## 11. Rollback Plan

If something breaks:
```bash
git revert HEAD  # Reverts the rename commit
git clean -fd     # Removes untracked files created by rename
```

No migration helper to worry about. Rollback is a pure code revert.

---

## 12. Post-Rename Checklist

| Check | Command |
|-------|---------|
| Installable? | `uv pip install -e .` |
| CLI works? | `consilium --help` |
| Tests pass? | `pytest tests/core/ -q` |
| Config loads? | `consilium --version` |
| Migration ran? | Check `~/.consilium/` exists |
| No `kimi_cli` imports remain? | `grep -r "kimi_cli" src/ tests/` |
| No `~/.kimi` hardcodes remain? | `grep -r "\.kimi" src/consilium/` |

---

## Open Questions

1. **Repo rename:** Should the GitHub repo be renamed from `kimi-cli-extensible` to `consilium`? This affects remote URLs and `pyproject.toml` homepage links. *(No users → rename freely.)*

2. **PyPI package:** Not published. No action needed.

3. **`kosong` package:** Leave it — internal LLM abstraction, separate identity.

4. **Session format:** Think session JSONL files contain the string `"kimi_cli"` nowhere (they store messages). Safe to leave as-is.
