# Phase 14: Rebrand to Consilium

## Summary

Perform the complete mechanical rename from `consilium-extensible` (package `consilium`) to **Consilium** (package `consilium`). All functional work (Phases 1–13) is now complete. This is a pure refactoring phase — no behavior changes.

**Prerequisite:** All functional phases (1–13) complete.

**Estimated effort:** 2–3 days.

**Rollback:** Single `git revert HEAD`. No migration needed (zero users).

---

## Scope

### In Scope
- Package directory: `src/consilium/` → `src/consilium/`
- All Python imports: `from consilium...` → `from consilium...`
- Config/data paths: `~/.consilium/` → `~/.consilium/`
- CLI entry point: `kimi` → `consilium`
- Core class names: `KimiSoul` → `ConsiliumSoul`, `KimiCLI` → `ConsiliumCLI`, etc.
- `pyproject.toml` package metadata
- Test imports and path assertions
- Example directories and their imports
- `README.md`, `docs/`, `AGENTS.md`
- Plan documents (this repo's `plan/`)

### Out of Scope (intentionally)
- `kosong` package (internal LLM abstraction, separate identity)
- `klips/` archive (historical artifacts; leave as-is or archive)
- Wire protocol type strings (audit separately — may be consumed by extension)
- Session JSONL file contents (no branding strings inside)
- Git history beyond `git mv` (blame preserved by move)

---

## Sub-Phase 14.1: Package & Import Rename

### Files

#### `src/consilium/` → `src/consilium/`

```bash
git mv src/consilium src/consilium
```

#### `src/consilium/soul/kimisoul.py` → `src/consilium/soul/consilium_soul.py`

```bash
git mv src/consilium/soul/kimisoul.py src/consilium/soul/consilium_soul.py
```

#### Bulk import replacement

```bash
# Run from repo root
find src/ tests/ tests_e2e/ tests_ai/ scripts/ examples/ -name "*.py" -exec \
  sed -i 's/^from consilium\./from consilium./g; s/^import consilium/import consilium/g; s/consilium\./consilium./g' {} +
```

#### `pyproject.toml`

| Field | Change |
|-------|--------|
| `[project].name` | `consilium` → `consilium` |
| `[project.scripts].consilium` | remove |
| `[project.scripts].consilium` | `consilium.cli:main` |
| `[tool.hatch.build.targets.wheel].packages` | `["src/consilium"]` |
| `[tool.uv.sources.consilium-cli]` | update key name or remove |

### Acceptance Criteria
- [ ] `src/consilium/` directory exists with full history
- [ ] No `from consilium` or `import consilium` remain in source/tests
- [ ] `uv pip install -e .` succeeds
- [ ] `pytest tests/core/ -q` passes

---

## Sub-Phase 14.2: Config & Data Path Rename

### Files

Search and replace `~/.consilium/` and hardcoded `.consilium` segments:

```bash
grep -rn "\.consilium" src/consilium/ --include="*.py"
```

Key files to update:
- `src/consilium/session.py` — `SESSIONS_DIR = Path.home() / ".consilium" / "sessions"`
- `src/consilium/config.py` — default config path
- `src/consilium/plan/dispatch.py` — `DISPATCH_PATH`
- `src/consilium/token_tracker.py` — log directory
- `src/consilium/think/push.py` — `OUTBOX_DIR`
- `src/consilium/think/inbox.py` — `INBOX_DIR` (from Phase 13)

### Acceptance Criteria
- [ ] No `~/.consilium` or `.consilium/` hardcodes remain in `src/consilium/`
- [ ] First run creates `~/.consilium/` automatically
- [ ] Old `~/.consilium/` is not referenced or auto-deleted

---

## Sub-Phase 14.3: Class & String Rename

### Core Classes

| Old | New | File |
|-----|-----|------|
| `KimiSoul` | `ConsiliumSoul` | `soul/consilium_soul.py` |
| `KimiCLI` | `ConsiliumCLI` | `cli/__init__.py` |
| `KimiRuntime` | `ConsiliumRuntime` | `soul/runtime.py` |

### Variable names

```bash
grep -rn "kimiSoul\|kimiCLI\|kimiRuntime" src/ tests/ --include="*.py"
```

### User-facing strings

Categories:
- Log messages: `"KimiSoul started"` → `"ConsiliumSoul started"`
- Error messages: `"Consilium CLI error"` → `"Consilium error"`
- CLI banner: `"Kimi — AI-assisted software engineering"` → `"Consilium — AI-assisted software engineering"`
- Help text in `cli/__init__.py`
- Prompts in `src/consilium/prompts/`

### Acceptance Criteria
- [ ] `grep -rni "kimiSoul\|kimiCLI\|kimiRuntime" src/ tests/` returns empty
- [ ] `consilium --help` shows "Consilium" branding
- [ ] Log messages use "Consilium" prefix

---

## Sub-Phase 14.4: Test Updates

### Files

All test files need import path updates (handled in 14.1). Additional test-specific changes:

- `test_config.py` — assert default path is `~/.consilium/config.toml`
- `test_think_storage.py` — assert session dirs under `~/.consilium/sessions/`
- `test_dispatch.py` — assert dispatch path is `~/.consilium/dispatch.json`
- Snapshot tests — regenerate if they contain "kimi" strings

### Acceptance Criteria
- [ ] All test imports use `consilium.*`
- [ ] Path assertions match new `~/.consilium/` paths
- [ ] `pytest` passes (1000+ tests)

---

## Sub-Phase 14.5: Documentation & External Updates

### Files

- `README.md` — full rewrite of name/branding
- `docs/AGENTS.md` — update CLI commands, paths
- `docs/BEST_PRACTICES.md` — update references
- `plan/phase-*.md` — update `src/consilium/...` paths to `src/consilium/...`
- `plan/index.md` — update project name
- `examples/` — rename directories, update imports and READMEs:
  - `examples/custom-kimi-soul/` → `examples/custom-consilium-soul/`
  - `examples/consilium-stream-json/` → `examples/consilium-stream-json/`
  - `examples/consilium-wire-messages/` → `examples/consilium-wire-messages/`
  - `examples/kimi-psql/` → `examples/consilium-psql/`
- `.github/workflows/` — package name in install steps, artifact names
- `.gitignore` — update `.consilium/` → `.consilium/`, `kimi_sessions/` → `consilium_sessions/`
- `AGENTS.md` (root) — update paths and command names

### Acceptance Criteria
- [ ] `README.md` says "Consilium" not "Consilium CLI"
- [ ] All plan documents reference `src/consilium/`
- [ ] Example directories renamed and buildable
- [ ] CI workflows reference `consilium`

---

## Sub-Phase 14.6: Extension Repo Coordination

The extension repo (`kimi_extension_mod/`) already uses `consilium` as the CLI command and `consilium` publisher. However, check for:

- Wire protocol type strings that contain `"kimi"` (audit `wire/types.py` separately)
- Any hardcoded references to `consilium` in extension docs or config

**Decision:** Extension rebrand is minimal — it was already created as `consilium`. Only update if the CLI wire protocol changes affect it.

### Acceptance Criteria
- [ ] Extension still connects to renamed CLI over wire
- [ ] No extension code changes needed (or changes are trivial)

---

## Acceptance Criteria (Phase 14 Overall)

- [ ] `src/consilium/` exists with full git history
- [ ] `uv pip install -e .` succeeds
- [ ] `consilium --help` works
- [ ] `consilium --version` works
- [ ] `pytest` passes (all tests)
- [ ] No `consilium` imports remain in source or tests
- [ ] No `~/.consilium` paths remain in source
- [ ] `README.md` fully rebranded
- [ ] Extension connects without changes

---

## Implementation Order

1. **Pre-flight** — `git tag pre-rename` (5 min)
2. **14.1** — `git mv` + bulk import replace + `pyproject.toml` (Day 1, morning)
3. **14.2** — Path constant updates (Day 1, afternoon)
4. **14.3** — Class renames + string updates (Day 2, morning)
5. **14.4** — Test fixes + snapshot regeneration (Day 2, afternoon)
6. **14.5** — Docs + examples + CI (Day 3)
7. **14.6** — Extension verification (Day 3)
8. Final test run + commit

**Total: ~2–3 days**

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Missed references in obscure files | 🟡 Medium | Comprehensive `grep` pass; CI will catch import errors |
| Wire protocol string changes break extension | 🔴 High | Audit `wire/` separately; do not bulk-replace protocol identifiers |
| Test snapshots need regeneration | 🟡 Medium | `pytest --snapshot-update` after import fixes |
| `uv` workspace references break | 🟡 Medium | Check `packages/` and `pyproject.toml` workspace table |
