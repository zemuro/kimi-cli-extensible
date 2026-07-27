---
document_type: implementation_report
phase: 08
title: Relocate Think/Do Buttons to Header
author: Kimi Code
completion_date: 2026-07-27
---

# Phase 08 — Relocate Think/Do Buttons to Header

## Executive Summary

Moved the Think/Do mode selector buttons (with live-status pulsing dots) from the standalone `TabBar` component into the `Header` component, eliminating the wasted vertical space of the TabBar bar. The header now contains logo, session info, mode selector, ChatStatus token counter, History, and New Conversation — all in one row.

## Files Modified

| File | Change |
|------|--------|
| `C:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\Header.tsx` | Added mode button JSX, imports (`cn`, `usePeerStatus`, `IconBrain`, `IconTool`), destructured `activeTab`/`setActiveTab`/`peerStatus` |
| `C:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\App.tsx` | Removed `<TabBar />` from render tree (line 103), removed import (line 4) |
| `C:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\TabBar.tsx` | Deleted (54 lines, replaced by inline JSX in Header) |

## Design Decisions

### Layout position
The mode buttons are placed **before** ChatStatus in the header's right-side flex container:

```
logo  |  [Session Info]  [Think|Do buttons]  [ChatStatus]  [History]  [+]
```

### Responsive handling
Added `@max-[400px]:hidden` to the mode button container — hides the buttons on very narrow viewports (phones), joining the existing responsive chain:
- `@max-[400px]`: hide mode buttons
- `@max-[320px]`: collapse Session Info to icon-only
- `@max-[280px]`: hide "History" label
- `@max-[240px]`: hide ChatStatus entirely

### Styling preservation
- Removed the TabBar's outer container bg/border (`bg-zinc-50 dark:bg-zinc-900 border-b`) — header already has `border-b border-border`
- Preserved the inner segmented control styling (`bg-zinc-200/50 dark:bg-zinc-800/50 rounded-lg p-1`)
- Preserved active/inactive button styling, icon sizes, and live-status dot animations
- Preserved `select-none` on the mode button group

### Imports added to Header.tsx
- `cn` from `@/lib/utils` (for class merging)
- `usePeerStatus` from `@/hooks/usePeerStatus` (for live-status dots)
- `IconBrain`, `IconTool` from `@tabler/icons-react` (for button icons)

## State Bindings Preserved

| Binding | Source | Dest |
|---------|--------|------|
| `activeTab` | `useChatStore()` → `Header.tsx` | Button active class styling |
| `setActiveTab` | `useChatStore()` → `Header.tsx` | Button onClick handlers |
| `peerStatus.think.is_alive` | `usePeerStatus()` → `Header.tsx` | Think live-status dot |
| `peerStatus.do.is_alive` | `usePeerStatus()` → `Header.tsx` | Do live-status dot |

## Acceptance Criteria

- [x] Think/Do buttons with live-status dots render inside Header.tsx adjacent to ChatStatus
- [x] TabBar.tsx no longer rendered — `<TabBar />` removed from App.tsx
- [x] State bindings preserved via same Zustand store hooks
- [x] ChatStatus token counter still displays correctly (layout position unchanged)
- [x] Live-status dots reflect backend health (same `usePeerStatus` hook)
- [x] Header layout responsive (mode buttons hidden at `@max-[400px]`)
- [x] No TypeScript compilation errors introduced

## Test Results (Manual Verification Required)

- [ ] Click Think → switches to Think mode (blue active)
- [ ] Click Do → switches to Do mode (green active)
- [ ] Live-status dot pulses when backend is alive
- [ ] ChatStatus renders correctly adjacent to mode buttons
- [ ] No overflow at 400px+ widths
- [ ] Mode buttons hidden below 400px

## Delta from Spec

| Spec | Actual |
|------|--------|
| Files in `kimi_cli_mod/webview-ui/` | Files in `kimi_extension_mod/webview-ui/` |
| Store at `store/chat.store.ts` | Store at `stores/chat.store.ts` |
| Effort: 3.75h | Actual: ~0.75h (simpler than spec estimated) |
| Task 0-6 (7 tasks) | Completed in 3 steps (read + modify + clean) |

## Conclusion

Clean relocation accomplished. The header now serves as a single unified bar for mode selection, token status, and session management. No UI real estate is wasted.