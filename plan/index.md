---
document_type: master_index
title: Consilium CLI — Plan Master Index
created: 2026-07-26
last_updated: 2026-07-26
author: Consilium
current_phase: 09
overall_status: 5 completed, 1 implemented, 1 research, 2 planning, 0 failed
---

# Consilium CLI — Plan Master Index

## Project Overview

This plan describes the systematic decoupling of the Consilium CLI project from legacy Kimi/Moonshot branding, configuration, and assumptions. The effort is organized into a phased sequence covering:

- **Phases 01–03**: Archival, class renames, and LLM/config refactoring (completed)
- **Phase 04**: Environment variable migration from `KIMI_*` to `CONSILIUM_*` (completed)
- **Phase 05**: Share directory migration and documentation update (completed)
- **Phase 06**: Fix explore subagent type in Think mode (implemented)

The overarching goal is a clean, self-contained `Consilium` codebase with no hardcoded dependencies on the Kimi brand, the Moonshot API, or any single LLM provider.

---

## Supplementary Plans

These two unnumbered plan documents cover cross-cutting concerns that were addressed alongside the main phased work:

| Document | Status | Description |
|----------|--------|-------------|
| [`project-agnostic-prompts-plan.md`](project-agnostic-prompts-plan.md) | ✅ completed | Making system prompts project-agnostic (generalize env/OS/SHELL refs) |
| [`refactor-system-prompts-plan.md`](refactor-system-prompts-plan.md) | ✅ completed | KIMI→CONSILIUM variable migration in system prompts |

---

## Glossary

| Term | Definition |
|------|------------|
| **Consilium** | The project name after the Kimi → Consilium rebranding. Also the CLI command name. |
| **Kimi** | Legacy brand name inherited from the original fork. All references are being systematically replaced. |
| **Moonshot** | Legacy parent company / API provider. References are being generalized to support any OpenAI-compatible provider. |
| **LLM** | Large Language Model — the AI backend that powers the agent. |
| **MCP** | Model Context Protocol — used for loading external tools. |
| **ACP** | Agent Communication Protocol — server mode for IDE integrations. |
| **Think mode** | A research/planning mode with mutable history, checkpoints, and Python exec. |
| **Do mode** | An immutable execution mode with git snapshots, change journaling, and plan review gates. |
| **Subagent** | A child agent instance spawned by the main agent to perform a focused subtask. |
| **LaborMarket** | The registry where builtin subagent types are registered. |
| **OpenRouter** | A third-party LLM provider aggregator; the project includes example configurations for it. |
| **Share directory** | The user configuration directory (`~/.consilium/`) containing `config.toml`, session data, logs, and MCP configurations. |

---

## Phase Status Table

| Phase | Title | Status | Locked | Dependencies | Description |
|-------|-------|--------|--------|--------------|-------------|
| [01](phase-01.md) | Archive & Setup | completed | ✅ | — | Archive old 26-phase plan; create new phased plan structure |
| [02](phase-02.md) | Rename Core Runtime Classes | completed | ✅ | Phase 01 | Rename `KimiCLI` → `ConsiliumCLI`, `KimiSoul` → `ConsiliumSoul`, and all related class/constant renames |
| [03](phase-03.md) | Refactor LLM & Configuration Defaults | completed | ✅ | Phase 02 | Generalize LLM layer and config classes; remove hardcoded Kimi/Moonshot assumptions |
| [04](phase-04.md) | Migrate Environment Variables | completed | ✅ | Phase 03 | Rename all `KIMI_*` environment variables to `CONSILIUM_*` across codebase, tests, and docs |
| [05](phase-05.md) | Update Share Directory & Documentation | completed | ✅ | Phase 04 | Migrate to `~/.consilium/`; update README & MODEL_OPTIONS_RESEARCH.md; final codebase audit |
| [06](phase-06.md) | Fix explore Subagent Type in Think Mode | implemented | ✅ | Phases 04, 05 | Remove blanket try/except in `create_think_soul()`; add per-subagent error handling |
| [07](phase-07.md) | Investigate Why Only Think Sessions Show in History | completed | ✅ | Phase 06 | Traced the session history data flow; root cause found (missing `listDoSessions()`); fix proposal filed |
| [08](phase-08.md) | Relocate Think/Do Buttons to Header | completed | ✅ | Phase 07 | TabBar removed; Think/Do buttons + live-status dots moved into Header.tsx; App.tsx cleaned up |
| [09](phase-09.md) | Move Session Archive to Workspace-Specific Directory | planning | ⬜ | Phase 07 | Relocate session storage to per-workspace location under `{workDir}/.consilium/sessions/` |
| [10](phase-10.md) | Model Modality Detection & `/media` Slash Command | planning | ⬜ | Phase 03 | Auto-detect model image_in capabilities; strip image payloads on text-only models; add `/media` slash command |

> **Statuses:** `planning` = spec exists, not yet approved; `ready` = spec approved, ready for implementation; `implemented` = work complete; `completed` = work complete and verified; `archived` = inactive.

---

## Dependencies Graph

```
Phase 01 (Archive & Setup)
    └── Phase 02 (Rename Core Runtime Classes)
            └── Phase 03 (Refactor LLM & Config Defaults)
                    └── Phase 04 (Migrate Environment Variables)
                            └── Phase 05 (Update Share Directory & Documentation)
                                    └── Phase 06 (Fix explore Subagent Type) ── depends on subagent system (04) & agent spec loading (05)
    └── Phase 07 (Investigate Think-Only Session History)
            └── Phase 08 (Relocate Think/Do Buttons to Header)
```

All phases form a linear dependency chain. No parallel tracks exist in the current plan.

---

## Current Phase

**Phase 09 — Move Session Archive to Workspace-Specific Directory** is the current phase.

- **Status:** `planning` (spec complete, awaiting approval)
- **Spec file:** `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\phase-09.md`
- **Goal:** Relocate session storage to be per-workspace under `{workDir}/.consilium/sessions/`, isolating sessions between workspaces.

All numbered phases (01–09) are now **completed**, **implemented**, in **research**, or in **planning**.

---

## Reports & Reviews

### Implementation Reports

| Report | Phase | File |
|--------|-------|------|
| Phase 02 — Rename Core Runtime Classes | 02 | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-02-implementation-report.md` |
| Phase 03 — Subagent Execution Enhancement | 03 | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-03-implementation-report.md` |
| Phase 04 — Environment Variable Migration | 04 | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-04-implementation-report.md` |
| Phase 05 — Share Directory & Documentation | 05 | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-05-implementation-report.md` |
| Phase 06 — Fix explore Subagent Type | 06 | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reports\phase-06-implementation-report.md` |

### Reviews

| Review | Phase | Verdict | File |
|--------|-------|---------|------|
| Pre-Implementation Review — Phase 03 | 03 | 🟢 Feasible | `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\reviews\phase-03-review.md` |

---

## Supplementary Documents (Legacy Table)

For reference, these documents are also listed in the [Supplementary Plans](#supplementary-plans) table above with their status and description:

---

## Archive Reference

The `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\archive\` directory contains an older 26-phase plan inherited from a different fork. These documents are retained for historical reference and are **not** part of the active plan.

- **26 phase specs** covering a different plan structure from the original fork
- **Archive index:** `c:\Users\zemuro\Antigravity\kimi_cli_mod\plan\archive\index.md`
- **Note:** The archive index is maintained separately from this master index. See `plan/archive/index.md` for the full list of archived phases.

---

## Notes

- Phase 02 and 03 spec files (`phase-02.md`, `phase-03.md`) are concise task lists without formal frontmatter — they predate the `document_type: phase_spec` convention.
- Phase 04 and 05 implementation reports confirm completion:
  - **Phase 04** (`plan/reports/phase-04-implementation-report.md`): Environment variable migration — all `KIMI_*` renamed to `CONSILIUM_*` with backward compatibility; 1096 core tests passing.
  - **Phase 05** (`plan/reports/phase-05-implementation-report.md`): Share directory migration, documentation update, global renaming of Markdown/code references; 1096 core tests passing.
- Phase 04 and 05 spec files (`phase-04.md`, `phase-05.md`) still show unchecked task items (`[ ]`) despite having implementation reports filed. This may indicate the spec files were not updated after implementation, or the reports were generated from a parallel session. Keep the reports as the source of truth for completion status.
- Phase 06 (`phase-06.md`) is the first spec to use the full `document_type: phase_spec` frontmatter convention.