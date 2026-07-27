---
document_type: fix_proposal
phase: 07
title: Fix Proposal — Add Do Session Scanning to GetAllConsiliumSessions
author: Kimi Code
created: 2026-07-27
estimated_effort: 1.5 hours
priority: high
---

# Fix Proposal: Add Do Session Scanning to `GetAllConsiliumSessions`

## Root Cause Reference

The root cause is documented in [phase-07.md](../phase-07.md#6-root-cause-analysis): `GetAllConsiliumSessions()` in `session.handler.ts` never scans `~/.consilium/do_sessions/`.

## Proposed Changes

### 1. Add `listDoSessions()` to `session.handler.ts`

**File:** `C:/Users/zemuro/Antigravity/kimi_extension_mod/src/handlers/session.handler.ts`

Add a new function after `listThinkSessions()` (line 82):

```typescript
async function listDoSessions(): Promise<SessionInfo[]> {
  const dir = path.join(os.homedir(), ".consilium", "do_sessions");
  console.log("[session.handler] listDoSessions dir:", dir, "exists:", fs.existsSync(dir));
  if (!fs.existsSync(dir)) return [];
  const entries = await fs.promises.readdir(dir, { withFileTypes: true });
  const sessions: SessionInfo[] = [];
  for (const e of entries) {
    if (!e.isDirectory() || !UUID_REGEX.test(e.name)) continue;
    const journalPath = path.join(dir, e.name, "journal.jsonl");
    if (!fs.existsSync(journalPath)) continue;
    const st = await fs.promises.stat(journalPath);
    // Do sessions don't embed a user message in the journal;
    // use an excerpt of the work_dir as the display title.
    const brief = await getFirstEntryWorkDir(journalPath) || DEFAULT_FALLBACK_TITLE;
    sessions.push({
      id: e.name,
      workDir: brief, // work_dir from journal entry
      updatedAt: st.mtimeMs || st.mtime.getTime(),
      contextFile: journalPath,
      brief,
      isThinking: false,
    });
  }
  return sessions.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Read the work_dir from the first session_start entry of a Do session journal. */
async function getFirstEntryWorkDir(journalPath: string): Promise<string | null> {
  try {
    const lines = (await fs.promises.readFile(journalPath, "utf-8")).split("\n");
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (entry.type === "session_start" && entry.work_dir) {
          return entry.work_dir;
        }
      } catch { continue; }
    }
  } catch { /* ignore */ }
  return null;
}
```

### 2. Wire it into `GetAllConsiliumSessions`

**File:** `C:/Users/zemuro/Antigravity/kimi_extension_mod/src/handlers/session.handler.ts`

In the `[Methods.GetAllConsiliumSessions]` handler, add a Do session scan block after the Think session scan (after line 132, before the sort on line 134):

```typescript
// Also surface Do sessions (not scanned by SDK or Think scanner)
for (const s of await listDoSessions()) {
  if (!seen.has(s.id)) {
    seen.add(s.id);
    const meta = ctx.getSessionMetadata(s.id);
    s.brief = meta?.title || s.brief;
    (s as any).mode = meta?.mode || 'do';
    allSessions.push(s);
  }
}
```

### 3. Update `SessionInfo` type to include `isThinking: false` for Do sessions

No change needed — the `SessionInfo` interface already has `isThinking: boolean`. Do sessions should have `isThinking: false`, which is what the proposed `listDoSessions()` does.

### 4. Frontend

No frontend changes needed. `SessionList.tsx` already renders a `ModeBadge` for `mode: 'do'`.

## Edge Cases & Risks

| Edge case | Mitigation |
|-----------|------------|
| Do session directory exists but `journal.jsonl` is empty | `getFirstEntryWorkDir` returns null; fall back to `DEFAULT_FALLBACK_TITLE` |
| Do session has no `session_start` entry | Same fallback |
| Corrupted `journal.jsonl` | try/catch — entry is skipped gracefully |
| `do_sessions/` directory doesn't exist | `fs.existsSync` check returns early |
| Case-insensitive UUID collision (very unlikely) | `seen` set deduplicates by ID, same as Think sessions |
| Do session titles are less informative than Think titles | Use `work_dir` as title; user can rename via the existing rename feature |

## Alternative Approach Considered

Add `listDoSessions()` to the SDK (`agent_sdk/storage.ts`) and export it alongside `listSessions()` and `listThinkSessions()`. This would keep the listing logic centralized but requires rebuilding the npm package. The proposed approach keeps the fix isolated to the extension handler, is simpler, and can be implemented without a package rebuild.

## Effort Estimate

| Task | Time |
|------|------|
| Add `listDoSessions()` function | 0.5h |
| Wire into `GetAllConsiliumSessions` | 0.25h |
| Test with existing Do sessions | 0.5h |
| Verify frontend renders Do badges correctly | 0.25h |
| **Total** | **1.5h** |

## Recommendation

Implement this as part of Phase 08 (or rename Phase 07 to include the fix). The investigation is complete and the fix is small — ~15 lines of new code, no frontend changes, no SDK rebuild.