# Proposal: Single-Mode Interactive Execution (Agile Do Mode)

## 1. Executive Summary

This proposal outlines a new session mode for Consilium: **Single-Mode Interactive Execution** (or **Agile Do Mode**), selectable during project initialization (`/init` or initial setup). 

Rather than maintaining a hard boundary between Think Mode (research/planning phase) and Do Mode (execution phase), this mode runs as a unified interactive loop where:
- The system operates strictly with **Do-mode tools and safety guarantees** (git tracking, immutable change journal, external memory).
- The agent remains in **continuous interactive dialogue** with the user.
- **Dynamic Plan Evolution**: The agent automatically captures new user ideas, refinements, and subtasks, dynamically adding new stages to the project plan (`plan/index.md` & `plan/phase-XX.md`).
- **Incremental Implementation Reporting**: After completing each significant step or feature chunk, the agent automatically generates an implementation report (`plan/reports/phase-XX-step-Y-report.md`) and presents a concise summary to the user before continuing.

---

## 2. Core Concepts & Workflow

### 2.1 Mode Selection at Project Initialization
When executing `/init` or initializing a workspace, the user is prompted for their preferred operational workflow:
1. **Dual Mode (Standard)**: Classic two-stage workflow (Think mode research → approval → Do mode batch execution).
2. **Agile Do Mode (Single-Agent Interactive)**: Unified interactive execution loop with live plan tracking.

### 2.2 Architectural Mechanics

```
User Prompt / Idea ──► Interactive Dialogue ──► Auto-Update Plan (`plan/index.md`)
                                                          │
                                                          ▼
User Feedback ◄── Implementation Report ◄── Execute Step & Audit Git Snapshot
```

1. **External Memory & Persistent Plan Structure**:
   - Maintains the standard `plan/` directory layout (`index.md`, `phase-XX.md`, `reports/`).
   - All state, context, and external memory remain persistent across turns.

2. **Dynamic Idea & Plan Staging**:
   - As the user discusses ideas or requests changes in chat, the agent parses the requirements, creates/updates the relevant `phase-XX.md` file, and updates `plan/index.md`.

3. **Incremental Execution & Reporting**:
   - The agent executes code changes step-by-step.
   - After each logical unit of work (e.g. implementing a script, fixing a component, adding a test suite), the agent writes an implementation report under `plan/reports/`.
   - The user gets immediate feedback without waiting for an entire batch phase to complete.

---

## 3. Integration Points

### 3.1 Consilium CLI (`kimi_cli_mod`)
- Add `agile_do` / `single_mode` flag to workspace configuration (`.consilium/config.toml`).
- Configure `ConsiliumSoul` prompt behavior for unified interactive plan updates and auto-reporting.

### 3.2 Consilium Extension (`kimi_extension_mod`)
- Add mode selection card in Project Setup Wizard (`/init` UI).
- Display active mode badge ("Agile Do Mode") in top header navigation.

---

## 4. Next Steps & Timeline
- Phase 11 spec in CLI repository.
- Phase 09 spec in Extension repository.
