# Phase Rename: Minimal Rebrand to Consilium

**Status:** PLANNED — execute before Phase 5B extension work.

**Principle:** Rename only user-facing surfaces. Leave internal class names, wire protocol strings, and upstream API endpoints untouched.

**Why now:** Extension code (5B–5E) is unwritten. Renaming before writing it means zero TypeScript renames later.

---

## Scope

### IN scope (user-facing)

| Surface | Current | New |
|---------|---------|-----|
| Package name | `consilium` | `consilium` |
| Python module | `consilium` | `consilium` |
| CLI command | `kimi` | `consilium` |
| Config directory | `~/.consilium` | `~/.consilium` |
| Description | "Consilium CLI" | "Consilium CLI" |

### OUT of scope (internal)

| Surface | Reason |
|---------|--------|
| `KimiSoul` class | Internal detail |
| `kosong` package | External dependency |
| Wire protocol strings | Protocol compatibility |
| OAuth/API hosts | Upstream endpoints |
| Docstrings, KLIPs, skills | Mechanical noise; defer |

---

## CLI Repo Changes

### 1. `pyproject.toml`

| Field | Current | New |
|-------|---------|-----|
| `[project].name` | `consilium` | `consilium` |
| `[project].description` | `Consilium CLI...` | `Consilium CLI agent` |
| `[tool.uv.build-backend].module-name` | `consilium` | `consilium` |
| `[project.scripts].consilium` | `consilium.__main__:main` | `consilium.cli:main` |
| `[project.scripts].consilium-cli` | `consilium.__main__:main` | *(remove)* |
| `[tool.pyright].strict` | `src/consilium/**/*.py` | `src/consilium/**/*.py` |

### 2. Directory rename

```bash
git mv src/consilium src/consilium
```

### 3. Import renames

Only rename `consilium` → `consilium` in Python imports. Use targeted regex:

```bash
sed -i 's/^from consilium\./from consilium./g' ...
sed -i 's/^import consilium/import consilium/g' ...
sed -i 's/consilium\./consilium./g' ...
```

**Do NOT** bulk-replace `"kimi"` as a bare word.

### 4. Config path renames (19 references)

Replace `~/.consilium` → `~/.consilium` in path constants:
- `src/consilium/cli/__init__.py`
- `src/consilium/think/storage.py`
- `src/consilium/do/journal.py`
- `src/consilium/do/blob_store.py`
- `src/consilium/plan/persistent_log.py` (via `for_session()`)
- And others

**Leave alone:** OAuth hosts, upstream API URLs.

### 5. `README.md`

Replace "Consilium CLI" / "consilium" with "Consilium" in headings and usage examples.

---

## Extension Repo Changes

See `../kimi_extension_mod/plan/phase-rename.md` for extension-specific renames (extension ID, display name, settings prefix, commands, view IDs).

---

## Testing

| Test | What |
|------|------|
| `consilium --version` | CLI runs with new name |
| `consilium --help` | Help text shows "Consilium" |
| `~/.consilium/` created | Config dir uses new name |
| `uv run pytest` | Full test suite passes |

---

## Rollback

Single commit revert. `~/.consilium/` and `~/.consilium/` are separate directories.

---

## Estimated Effort

1 day.
