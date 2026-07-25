# Phase Rename: Minimal Rebrand to Consilium

**Status:** PLANNED — execute before Phase 5B extension work.

**Principle:** Rename only user-facing surfaces. Leave internal class names, wire protocol strings, and upstream API endpoints untouched.

**Why now:** Extension code (5B–5E) is unwritten. Renaming before writing it means zero TypeScript renames later.

---

## Scope

### IN scope (user-facing)

| Surface | Current | New |
|---------|---------|-----|
| Package name | `kimi-cli` | `consilium` |
| Python module | `kimi_cli` | `consilium` |
| CLI command | `kimi` | `consilium` |
| Config directory | `~/.kimi` | `~/.consilium` |
| Description | "Kimi Code CLI" | "Consilium CLI" |

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
| `[project].name` | `kimi-cli` | `consilium` |
| `[project].description` | `Kimi Code CLI...` | `Consilium CLI agent` |
| `[tool.uv.build-backend].module-name` | `kimi_cli` | `consilium` |
| `[project.scripts].kimi` | `kimi_cli.__main__:main` | `consilium.cli:main` |
| `[project.scripts].kimi-cli` | `kimi_cli.__main__:main` | *(remove)* |
| `[tool.pyright].strict` | `src/kimi_cli/**/*.py` | `src/consilium/**/*.py` |

### 2. Directory rename

```bash
git mv src/kimi_cli src/consilium
```

### 3. Import renames

Only rename `kimi_cli` → `consilium` in Python imports. Use targeted regex:

```bash
sed -i 's/^from kimi_cli\./from consilium./g' ...
sed -i 's/^import kimi_cli/import consilium/g' ...
sed -i 's/kimi_cli\./consilium./g' ...
```

**Do NOT** bulk-replace `"kimi"` as a bare word.

### 4. Config path renames (19 references)

Replace `~/.kimi` → `~/.consilium` in path constants:
- `src/consilium/cli/__init__.py`
- `src/consilium/think/storage.py`
- `src/consilium/do/journal.py`
- `src/consilium/do/blob_store.py`
- `src/consilium/plan/persistent_log.py` (via `for_session()`)
- And others

**Leave alone:** OAuth hosts, upstream API URLs.

### 5. `README.md`

Replace "Kimi CLI" / "kimi-cli" with "Consilium" in headings and usage examples.

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

Single commit revert. `~/.kimi/` and `~/.consilium/` are separate directories.

---

## Estimated Effort

1 day.
