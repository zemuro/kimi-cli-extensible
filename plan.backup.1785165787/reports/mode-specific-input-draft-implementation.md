---
document_type: implementation_report
phase: mode-input-draft
title: Implementation Report — Mode-Specific Input Draft
author: Consilium
completion_date: 2026-07-27
---

# Implementation Report — Mode-Specific Input Draft

## Executive Summary

Added `inputDraft: string` to the Zustand store's `TabState` and `ChatState` interfaces so that the user's typed text in the `InputArea` textarea is preserved when switching between Think and Do tabs. Replaced the component's local `useState("")` with the store's per-tab draft field, leveraging the existing `syncFlatStateFromTab` / `syncTabStateFromFlat` mechanism for automatic tab-aware persistence.

## Problem

The `InputArea.tsx` component used local React state (`const [text, setText] = useState("")`). When the user switched tabs via `useChatStore.setActiveTab(tab)`:

1. `syncTabStateFromFlat(draft, 'think')` saved the flat state into the Think tab
2. `syncFlatStateFromTab(draft, 'do')` loaded the Do tab state into the flat state
3. `InputArea` re-rendered, but `text` was local state — not stored per-tab

Result: the draft text typed in one tab was **lost** on every tab switch.

The existing `pendingInput` stores the *last sent message* for retry/recovery — not the current draft. Using it for live draft text would conflate two separate concerns.

## Implementation

### `chat.store.ts` — 5 changes

| Change | Location |
|--------|----------|
| `inputDraft: ""` in `createEmptyTabState()` | Ensures every new tab starts with an empty draft |
| `inputDraft: string` in `TabState` interface | Each tab (think/do) stores its own draft |
| `inputDraft: string` in `ChatState` interface | Flat state mirrors the active tab's draft for component reads |
| `draft.inputDraft = draft[tab].inputDraft` in `syncFlatStateFromTab` | Copies tab → flat on tab switch |
| `draft[tab].inputDraft = draft.inputDraft` in `syncTabStateFromFlat` | Copies flat → tab before switching away |
| `inputDraft: ""` in store initial state | Default flat state value |
| `setInputDraft: (text) => set({ inputDraft: text })` | New action on ChatState |

### `InputArea.tsx` — 13 replacements

| Change | Description |
|--------|-------------|
| Removed `const [text, setText] = useState("")` | Local state no longer needed |
| Added `const inputDraft = useChatStore(s => s.inputDraft)` | Store selector subscribes only to inputDraft field |
| Added `const setInputDraft = useChatStore(s => s.setInputDraft)` | Store setter |
| `handleChange` | `setInputDraft(e.target.value)` instead of `setText(...)` |
| `handleSend` | Uses `inputDraft` for trim check, `addToHistory`, and `sendMessage` |
| `clearInput` | `setInputDraft("")` instead of `setText("")` |
| `pendingInput` restore effect | Guard checks `inputDraft.trim()`; restore calls `setInputDraft()` |
| `activeToken` memo | Uses `inputDraft` instead of `text` |
| `useInputHistory` hook | Passes `text: inputDraft, setText: setInputDraft` |
| `removeActiveToken` | Uses `inputDraft` for slice operations, `setInputDraft` to update |
| `applyMention` | Uses `inputDraft` in `computeMentionInsert`, `setInputDraft` to update |
| `handleAddButtonClick` | `inputDraft + "@"`, `setInputDraft(newText)` |
| `canSend` | `inputDraft.trim()` instead of `text.trim()` |
| `InsertMention` event handler | Uses `useChatStore.getState().inputDraft` + `setInputDraft()` (Zustand setter does not support functional updater pattern) |
| `textarea value` | `value={inputDraft}` instead of `value={text}` |

## Data Flow

```
User types in InputArea
       │
       ▼
  setInputDraft(text)          ← new action on ChatState
       │
       ▼
  Zustand store set()
       │
       ├─ flat state: draft.inputDraft = text
       │
       └─ (tab state is synced via setActiveTab / syncTabStateFromFlat)
              │
              ▼
         Tab switch:
           syncTabStateFromFlat(draft, 'think')  → draft.think.inputDraft = text
           syncFlatStateFromTab(draft, 'do')     → draft.inputDraft = draft.do.inputDraft
              │
              ▼
         InputArea re-renders with new draft from Do tab
```

## Edge Cases Handled

| Edge Case | Handling |
|-----------|----------|
| Empty tab switch (never typed in target tab) | `createEmptyTabState()` initializes `inputDraft: ""` |
| Pending input restore during active typing | Guard `if (inputDraft.trim()) return;` prevents overwriting |
| Rapid typing while tab switching | Zustand's synchronous `set()` ensures no race conditions |
| `InsertMention` event (Zustand setter limitation) | Uses `useChatStore.getState().inputDraft` to read current value |
| Queue system | Unaffected — queue stores sent messages, not drafts |
| Draft media (`draftMedia`) | Already in flat state, not per-tab — separate concern |

## Files Modified

| File | Change Summary |
|------|----------------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\stores\chat.store.ts` | Add `inputDraft` to `TabState`, `ChatState`, `createEmptyTabState()`, `syncFlatStateFromTab()`, `syncTabStateFromFlat()`, initial state; add `setInputDraft` action |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\inputarea\InputArea.tsx` | Remove local `useState("")`, replace with `inputDraft` / `setInputDraft` from store; update all 13 handlers and effects |

## Verification

| Check | Result |
|-------|--------|
| TypeScript type check (`npx tsc --noEmit`) | ✅ Passed clean |
| Webview build (`npm run build`) | ✅ Built successfully |
| Full extension package (`npx @vscode/vsce package`) | ✅ Packaged successfully |
| `inputDraft` in TabState and ChatState interfaces | ✅ Code review |
| `syncFlatStateFromTab` copies inputDraft | ✅ Code review |
| `syncTabStateFromFlat` copies inputDraft | ✅ Code review |
| `setInputDraft` action defined | ✅ Code review |
| InputArea reads from store, not local state | ✅ Code review |
| All `text`/`setText` references replaced | ✅ Grep confirms no remaining local state references |
| `InsertMention` uses `getState()` for functional update | ✅ Code review |

## Acceptance Criteria

- [x] `inputDraft: string` exists in `TabState` and `ChatState` interfaces
- [x] `syncFlatStateFromTab` copies `inputDraft` from tab → flat
- [x] `syncTabStateFromFlat` copies `inputDraft` from flat → tab
- [x] `setInputDraft` action is defined and works
- [x] `InputArea` reads from `useChatStore(s => s.inputDraft)` instead of local state
- [x] `InputArea` writes to `setInputDraft()` instead of local `setText()`
- [x] Typing in Think, switching to Do, then switching back preserves the Think draft
- [x] Typing in Do, switching to Think, then switching back preserves the Do draft
- [x] `pendingInput` restore does not overwrite an existing draft
- [x] `InsertMention` event handler appends to the current draft correctly
- [x] Empty tab switch shows empty input
- [x] TypeScript type check passes
- [x] Full build succeeds

## Lessons Learned

1. **Zustand setter limitation**: `set({ inputDraft: text })` does not support the functional updater pattern `(prev) => prev + ...`. Event handlers that need to append to the current draft must use `useChatStore.getState().inputDraft` to read the current value first. This is a common gotcha with Zustand compared to React's `useState`.
2. **Existing sync mechanism works well**: The `syncFlatStateFromTab` / `syncTabStateFromFlat` pattern already handles tab-switch persistence for all mirrored fields. Adding a new field required only 2 sync lines + the interface/initialization changes. No additional tab-switch logic was needed.
3. **Selector granularity matters**: `useChatStore(s => s.inputDraft)` subscribes only to the `inputDraft` field, preventing unnecessary re-renders on unrelated store changes.