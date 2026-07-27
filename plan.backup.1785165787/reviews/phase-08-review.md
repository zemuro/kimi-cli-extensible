---
document_type: review
phase: 08
title: Phase 08 Review — Relocate Think/Do Buttons to Header
reviewer: Kimi Code
review_date: 2026-07-27
verdict: 🟢
---

# Phase 08 Review — Relocate Think/Do Buttons to Header

## Verdict

🟢 **Feasible** — low risk, well-scoped, no backend changes needed.

## Actual Code State vs. Spec

| Spec Path | Actual Path | Notes |
|-----------|-------------|-------|
| `kimi_cli_mod/webview-ui/src/components/TabBar.tsx` | `kimi_extension_mod/webview-ui/src/components/TabBar.tsx` | Same repo confusion as Phase 07 |
| `kimi_cli_mod/webview-ui/src/components/Header.tsx` | `kimi_extension_mod/webview-ui/src/components/Header.tsx` | Same |
| `kimi_cli_mod/webview-ui/src/components/ChatStatus.tsx` | `kimi_extension_mod/webview-ui/src/components/ChatStatus.tsx` | Same |
| `kimi_cli_mod/webview-ui/src/App.tsx` | `kimi_extension_mod/webview-ui/src/App.tsx` | Same |
| `kimi_cli_mod/webview-ui/src/store/chat.store.ts` | `kimi_extension_mod/webview-ui/src/stores/chat.store.ts` | Path has `stores/` not `store/` |

## Code Analysis

### TabBar.tsx (54 lines)

Simple component with no external props:

```tsx
export function TabBar() {
  const { activeTab, setActiveTab } = useChatStore();
  const { peerStatus } = usePeerStatus();
  const { think, do: doStatus } = peerStatus;
  // renders two buttons in a segmented-control pattern
}
```

**State bindings to preserve:**
- `useChatStore()` → `activeTab`, `setActiveTab`
- `usePeerStatus()` → `peerStatus.think.is_alive`, `peerStatus.do.is_alive`
- `IconBrain` (think) / `IconTool` (do) — from `@tabler/icons-react`
- `cn()` — from `@/lib/utils`

**Live-status dot logic:**
```tsx
{think?.is_alive && (
  <span className="flex size-2 absolute top-1.5 right-1.5">
    <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-blue-400 opacity-75"></span>
    <span className="relative inline-flex rounded-full size-2 bg-blue-500"></span>
  </span>
)}
```
Identical pattern for `doStatus` with green colors.

**Key styling:**
- Outer container: `flex px-4 py-2 bg-zinc-50 dark:bg-zinc-900 border-b border-border select-none`
- Inner container (segmented): `flex gap-1.5 p-1 bg-zinc-200/50 dark:bg-zinc-800/50 rounded-lg`
- Active button: `bg-white dark:bg-zinc-700 shadow-sm text-blue-600 dark:text-blue-400`
- Inactive button: `text-muted-foreground hover:text-foreground hover:bg-zinc-200 dark:hover:bg-zinc-700/50`

### Header.tsx (99 lines)

Current right-side layout (after logo + "Consilium"):

```
<div className="flex items-center gap-1">
  [Session Info btn]  [ChatStatus pill mr-2]  [History popover]  [New btn]
</div>
```

**Key imports already present:**
- `useChatStore` from `@/stores` — already imported
- `IconPlus`, `IconChevronDown`, `IconInfoCircle` from `@tabler/icons-react` — need to add `IconBrain`, `IconTool`
- `cn` — NOT imported; need to add from `@/lib/utils`
- `usePeerStatus` — NOT imported; need to add from `@/hooks/usePeerStatus`

**Container query breakpoints in use:**
- `@max-[320px]` — hides Session Info text
- `@max-[500px]` — hides "Session" label
- `@max-[280px]` — hides "History" label
- `@max-[240px]` — hides ChatStatus entirely

### ChatStatus.tsx (102 lines)

- Compact pill with `rounded-full px-2 py-0.5 h-6 box-border mr-2`
- Has `@max-[240px]:hidden` — disappears on very narrow viewports
- Has `@max-[440px]:hidden` on input/output token sections
- **No changes needed** — just needs the new buttons positioned next to it

### App.tsx (170 lines)

`TabBar` is rendered on line 103 inside `<MainContent>`:
```tsx
return (
  <>
    <TabBar />   {/* ← remove this */}
    <div className="flex-1 min-h-0 relative group/chat">
      <ChatArea />
    </div>
    ...
  </>
);
```

### chat.store.ts (689 lines)

- `activeTab: 'think' | 'do'` — available, used by `TabBar` already
- `setActiveTab(tab)` — available, used by `TabBar` already
- Tab state management (syncFlatStateFromTab / syncTabStateFromFlat) is robust
- **No changes needed**

### usePeerStatus.ts (60 lines)

- Polls `bridge.getPeerStatus()` every 2.5s
- Depends on `thinkSessionId` and `doSessionId` being non-null to start polling
- Returns `{ peerStatus, isStale }` — `peerStatus.think`, `peerStatus.do`
- **No changes needed**

## Key Observations

### 1. Spec repo path inaccuracy
All spec file paths reference `kimi_cli_mod/webview-ui/src/` but actual files are in `kimi_extension_mod/webview-ui/src/`. This is the same pattern as Phase 07.

### 2. Layout crowding risk (real)
Current header right side: `[Session Info] [ChatStatus] [History] [New btn]` — 4 items.
After relocation: `[Session Info] [Think|Do buttons] [ChatStatus] [History] [New btn]` — 5 items.

The Think/Do segmented control is ~120px wide (2 buttons × ~50px + gap). On narrow viewports (<400px), this may cause overflow. Mitigations:

- The existing `@max-[240px]:hidden` on ChatStatus already handles the narrowest case
- Add a responsive breakpoint to hide the mode buttons on very narrow viewports (e.g., `@max-[360px]:hidden`)
- The `@container` query on `<header>` enables container-based responsive breakpoints

### 3. Styling adaptation needed
The TabBar's outer container styling (`bg-zinc-50 dark:bg-zinc-900 border-b border-border px-4 py-2`) provides visual separation. When moved into the header:

- The header already has `border-b border-border` — no need to duplicate
- The `bg-zinc-50` background should be removed (header has its own background)
- The segmented control inner container (`bg-zinc-200/50 dark:bg-zinc-800/50 rounded-lg p-1`) should be preserved
- `select-none` should be preserved on the buttons

### 4. No new imports needed for core functionality
- `useChatStore` is already in Header.tsx
- `activeTab`/`setActiveTab` are already exported from the store
- Only need to add: `cn`, `usePeerStatus`, `IconBrain`, `IconTool`

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CSS conflicts from migrated buttons (bg, padding, border clash) | M | M | Remove outer container bg/border; keep inner segmented styling; header already has its own border |
| Header too crowded on narrow viewports | M | M | Add `@max-[360px]:hidden` on the mode buttons; existing `@max-[240px]` breakpoint hides ChatStatus |
| `usePeerStatus` starts polling too early or doesn't poll | L | M | Hook guards on `thinkSessionId`/`doSessionId` — same behavior as before |
| Accidental deletion of shared reference when removing TabBar.tsx | L | L | Only one file imports TabBar: `App.tsx` line 4. Run `grep -r TabBar` to confirm before deleting. |

## Acceptance Criteria Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| Think/Do buttons with live-status dots in Header | 🟢 | Straightforward JSX relocation |
| TabBar.tsx removed from render tree | 🟢 | Single `<TabBar />` removal in App.tsx |
| State bindings preserved | 🟢 | Same Zustand store, same hook |
| Layout renders correctly | 🟡 | Needs responsive testing; crowding risk at narrow widths |
| No visual breakage | 🟡 | Styling adaptation needed (remove outer bg, adjust positioning) |

## Recommendation

**Proceed with implementation.** The work is straightforward:

1. Extract button JSX from `TabBar.tsx` (~30 lines of JSX)
2. Insert into `Header.tsx` right-side flex container, before or after ChatStatus
3. Add necessary imports to Header.tsx: `cn`, `usePeerStatus`, `IconBrain`, `IconTool`
4. Remove `<TabBar />` from `App.tsx` and its import
5. Delete `TabBar.tsx` (after confirming no other references)
6. Test responsive behavior at narrow widths

Estimated effort: **1.5-2 hours** (spec says 3.75h, but actual code is simpler — no new component, just inline relocation).
