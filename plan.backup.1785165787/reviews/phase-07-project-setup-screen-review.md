---
document_type: review
phase: 07-project-setup-screen
title: Review — Phase 07 Project Setup Screen
reviewer: Consilium
review_date: 2026-07-27
verdict: 🟢
---

# Review — Phase 07 Project Setup Screen

## Scope

Add a new `"uninitialized"` status to the extension's initialization flow, and a `ProjectSetupScreen` component that lets users scaffold the `.consilium/` workspace directory structure before starting their first session.

## Files to Change

| File | Change |
|------|--------|
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\shared\bridge.ts` | Add `CheckProjectSetup` and `InitializeProject` to Methods enum |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\session.handler.ts` | Add `checkProjectSetup` and `initializeProject` handlers (file is `session.handler.ts`, NOT `session.ts` as spec says) |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\src\handlers\index.ts` | Auto-registered via `sessionHandlers` spread — no change needed |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\services\bridge.ts` | Add `checkProjectSetup()` and `initializeProject()` methods |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\hooks\useAppInit.ts` | Add `"uninitialized"` to `AppStatus`; add project setup check after CLI check |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\components\ProjectSetupScreen.tsx` | New component (modeled after ConfigErrorScreen) |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\App.tsx` | Add `"uninitialized"` case before `"ready"` |
| `c:\Users\zemuro\Antigravity\kimi_extension_mod\webview-ui\src\stores\settings.store.ts` | Add `projectSetupSkipped` boolean |

## Corrections from Spec

| # | Spec Says | Actual | Fix |
|---|-----------|--------|-----|
| 1 | File `src/handlers/session.ts` | Actual file is `src/handlers/session.handler.ts` | Use correct path |
| 2 | No mention of `shared/bridge.ts` Methods enum | Methods enum must be updated for handler routing | Add `CheckProjectSetup` and `InitializeProject` |
| 3 | No mention of bridge service methods | `bridge.ts` must expose `checkProjectSetup()` and `initializeProject()` | Add both methods |
| 4 | No mention of settings store for `projectSetupSkipped` | Needs a Zustand settings store field | Add to `settings.store.ts` |
| 5 | New status order: `uninitialized` before `no-models` | `App.tsx` has `shouldShowSetup` check before status checks | Insert `uninitialized` check after `shouldShowSetup` block, before `no-models` |
| 6 | Plan references `context.requireWorkDir()` | Handler context may not have this exact method | Use `context.workDir` or `ctx.workspaceRoot` |

## Edge Cases

| Case | Handling |
|------|----------|
| Existing project with `.consilium/` | `checkProjectSetup` returns `initialized: true`, status stays `"ready"` |
| User skips setup | `projectSetupSkipped` flag stored in settings store, prevents re-showing on refresh |
| Initialization fails | Handler returns `{ success: false }`, show error toast in component |
| `.consilium/` exists but empty | `initialized: false` — scaffold creates missing dirs |
| User re-opens skipped workspace | Skip flag persists in settings store — goes straight to `"ready"` |

## Verdict

🟢 **Feasible** — corrections are minor (wrong file path, missing bridge/service/settings entries). Implementation time: ~30-45 minutes.

## Risks

| # | Risk | Severity | Notes |
|---|------|----------|-------|
| 1 | Wrong file path in spec (`session.ts` vs `session.handler.ts`) | L | Already corrected — verified actual file exists at the correct path |
| 2 | Missing bridge/service/settings entries in spec | L | Identified and enumerated in Corrections table — all trivial additions |
| 3 | `context.requireWorkDir()` may not exist in handler context | M | Mitigated by using `context.workDir` or `ctx.workspaceRoot` instead |
| 4 | Status insertion point in `App.tsx` differs from spec assumption | L | Corrected — `uninitialized` goes after `shouldShowSetup` block, before `no-models` |

## Recommendations

1. Follow the Implementation Order listed below — bridge enums first, handlers second, then UI layers bottom-up — to avoid forward references.
2. Verify the actual handler context API before writing `checkProjectSetup` — check whether `ctx.workspaceRoot` or `context.workDir` is available.
3. After implementation, manually test the "skip" flow to confirm the `projectSetupSkipped` flag survives a webview refresh.

## Questions

1. Should `checkProjectSetup` also validate that `.consilium/` contains the expected subdirectory structure (e.g., `agents/`, `sessions/`), or just check for the directory's existence?
2. Does the `projectSetupSkipped` flag need to be persisted to disk (e.g., VS Code globalState/memento) or is in-memory Zustand sufficient for the session lifetime?

## Summary

The spec is sound and the feature is well-scoped. Six corrections were identified, all minor (wrong file path, missing enum entries, missing bridge methods, missing settings field, status insertion point, and a non-existent context method). The corrections table and edge-case matrix are complete enough to guide implementation directly. With ~30-45 minutes of effort this phase is ready to proceed.

## Implementation Order

1. `shared/bridge.ts` — Add Methods enum entries
2. `src/handlers/session.handler.ts` — Add handlers
3. `webview-ui/src/services/bridge.ts` — Add bridge methods
4. `webview-ui/src/stores/settings.store.ts` — Add `projectSetupSkipped`
5. `webview-ui/src/hooks/useAppInit.ts` — Add `"uninitialized"` status + check
6. `webview-ui/src/components/ProjectSetupScreen.tsx` — New component
7. `webview-ui/src/App.tsx` — Add status case