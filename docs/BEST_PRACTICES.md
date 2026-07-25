# Best Practices — Think/Do Workflow

> This guide is for users of the `consilium-extensible` fork. It assumes you are familiar with the basic upstream Consilium CLI features.

---

## 1. When to Use Think vs Do

| Use Think when... | Use Do when... |
|---|---|
| You don't know the solution yet | You have a clear plan and want it executed |
| You need to explore the codebase | You need to edit files, run tests, commit |
| You're designing architecture | You're implementing a known design |
| You're writing or revising a plan | You're following an existing plan |
| You want mutable history (edit/delete) | You want immutable audit trail |

**The rule of thumb:** If you would open a notebook to think through a problem, use Think. If you would open an IDE to write code, use Do.

---

## 2. The Think → Do Handoff

### Step 1: Research in Think

```
[Think] > Explore the auth module. I need to add OAuth2.
[Think] > /explore "How is auth currently implemented?"
...
[Think] > Now draft a plan for OAuth2 integration
```

### Step 2: Export the plan

```
[Think] > /push-to-do
Plan exported to docs/plan/index.md + phase files.
```

### Step 3: Execute in Do

```sh
kimi --do --plan-file docs/plan.md --phase phase-oauth2
```

Do will:
1. Stash your uncommitted changes
2. Load only `phase-oauth2.md` + `index.md`
3. Run the plan review gate (`/review` if not auto-triggered)
4. Execute tool calls with full journaling

### Step 4: Review the journal

```
[Do] > /journal
- Turn 1: write_file src/auth/oauth2.py (+45/-0 lines)
- Turn 2: run_command pytest tests/auth/ (exit 0)
- Turn 3: commit "Add OAuth2 support"
```

---

## 3. Plan Structure

### For small projects (< 5 phases)

A single `docs/plan.md` is fine. Keep it under 500 lines.

```markdown
# Plan: Tiny Tool

## Phase 1: Scaffold
- Create main.py
- Add argparse

## Phase 2: Core Logic
- Implement the algorithm
- Add tests
```

### For large projects (5+ phases)

Use the decomposed format:

```
docs/plan/
├── index.md
├── phase-01.md
├── phase-02.md
└── ...
```

**`index.md`** should contain:
- Plan metadata (id, created, last updated)
- Dependency graph (mermaid or list)
- Status table (one row per phase)

**`phase-XX.md`** should contain:
- YAML frontmatter with `phase_id`, `title`, `status`, `dependencies`, `files_involved`
- Description (what this phase does)
- Acceptance criteria (how you know it's done)
- Risks and unknowns

### Phase frontmatter template

```markdown
---
phase_id: phase-03
title: API Endpoints
status: pending
locked: false
dependencies:
  - phase-01
  - phase-02
files_involved:
  - src/api/routes.py
  - src/api/schemas.py
---
```

**Status values:** `pending` → `under_review` → `approved` → `implemented` → `aborted`

**Locking:** Once `implemented`, a phase is locked. Do mode will reject edits. Think mode can append a new phase if requirements change.

---

## 4. Subagent Budget Tuning

Default limits (20k tokens, 20 tool calls) are conservative. Tune based on your project:

| Project size | Tokens | Tool calls | Rationale |
|---|---|---|---|
| Small script (< 1k LOC) | 10,000 | 10 | Quick exploration |
| Medium service (1k–10k LOC) | 20,000 | 20 | Default, covers most cases |
| Large codebase (10k+ LOC) | 50,000 | 50 | Deep exploration needed |
| Plan review (simple change) | 10,000 | 15 | Should be quick |
| Plan review (complex refactor) | 30,000 | 30 | May need extensive investigation |

### Warning ratios

- **0.8 (default)** — Good for most cases. Gives you a heads-up without being noisy.
- **0.5** — Use when debugging subagent behavior. You'll see warnings early.
- **1.0** — Disable warnings. Only hard limits apply.

### When a subagent hits the limit

1. Read the partial results — they often contain useful findings
2. Narrow your query — be more specific about what you want
3. Increase limits if the task genuinely requires more resources
4. Consider breaking the task into smaller subagent calls

---

## 5. Context Compaction

Think mode warns you when context usage exceeds 75% (configurable). When this happens:

**Option A: Manual compaction (`/compact`)**
```
[Think] > /compact
Old messages summarized. Context freed.
```

Best when: You want to preserve key findings in a summary.

**Option B: Prune history (`/prune msg_id`)**
```
[Think] > /prune msg_abc123
Removed all messages after msg_abc123.
```

Best when: You took a wrong turn and want to rewind.

**Option C: Checkpoint and restart (`/checkpoint`)**
```
[Think] > /checkpoint before-auth-refactor
[Think] > ... (explore, realize it's wrong)
[Think] > /checkpoint --list
[Think] > /checkpoint before-auth-refactor  # restore
```

Best when: You want to experiment and have a clean fallback.

---

## 6. Git Workflow in Do Mode

Do mode automatically stashes your uncommitted changes on start. Here's the intended workflow:

```
# Start Do with a clean-ish working tree
$ git status
# some unstaged changes

$ kimi --do --plan-file docs/plan.md --phase phase-02
[Do] Stashed uncommitted changes. Starting...

# Do implements the phase...

# Option 1: Keep changes
[Do] > /commit "Implement phase 2: OAuth2"
[Do] > /end

# Option 2: Discard everything
[Do] > /abort
[Do] Working tree restored to pre-session state.
```

**Never** run Do on a dirty tree with uncommitted work you care about unless you're comfortable with `/abort` reverting it.

---

## 7. Plan Review Workflow

When Do is seeded from Think, the plan review gate auto-triggers. When typing a plan directly in Do, use `/review`:

```
[Do] > Here's my plan: create a new microservice for billing...
[Do] > /review
[Do] Reviewing plan...

Feasible: yes
Risks:
  - No database schema defined
  - Missing API contract
Recommendations:
  - Define schema first
  - Add integration tests

[Do] > /approve
[Do] Plan approved. Resuming execution...
```

If the review finds issues:
```
[Do] > /reject need schema first
[Do] Plan review rejected.
# Edit your plan, then /review again
```

---

## 8. Common Mistakes

| Mistake | Why It Hurts | Fix |
|---|---|---|
| Writing a 100-phase plan upfront | Plans rot. Requirements change. | Use stubs — detail 2–3 phases ahead, leave rest as placeholders |
| Keeping everything in Think mode | Think has no tool access. You can't verify. | Push to Do as soon as you have a concrete plan |
| Running Do without `--plan-file` | Do has no guidance. It wanders. | Always provide a plan, even a simple one |
| Ignoring budget warnings | Subagent burns tokens silently | Set `[subagents.budget]` limits appropriate for your budget |
| Not using checkpoints | One bad message poisons the context | `/checkpoint` before major experiments |
| Editing plan.md while Do is running | Do loads the plan at startup. Edits mid-flight are ignored. | Stop Do, edit, restart |

---

## 9. Quick Reference

### Think mode slash commands

| Command | Description |
|---|---|
| `/think` | Enter Think mode |
| `/edit <msg_id>` | Edit a message |
| `/delete <msg_id>` | Soft-delete a message |
| `/prune <msg_id>` | Remove all messages after |
| `/regenerate` | Remove last assistant message |
| `/checkpoint <name>` | Save snapshot |
| `/compact` | Summarize old history |
| `/push-to-do` | Export plan and send to Do |
| `/explore "query"` | Spawn explore subagent |
| `/python <code>` | Execute Python |
| `/history` | Show message list |

### Do mode slash commands

| Command | Description |
|---|---|
| `--do` | Enter Do mode |
| `/review` | Manually trigger plan review |
| `/approve` | Approve pending review |
| `/reject [reason]` | Reject pending review |
| `/commit "message"` | Git commit current state |
| `/abort` | Revert to initial stash |
| `/journal` | Show change journal |
| `/token-usage` | Show session token stats |
