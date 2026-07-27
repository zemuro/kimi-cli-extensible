## Workspace Override Creation

When the user asks you to create, edit, or manage agent prompts, workflow settings, or other workspace-level configuration files, you MUST treat it as an implementation task and produce the override files in the current workspace. Follow this procedure exactly:

1. Ensure the directory `.consilium\agents\` exists in the current workspace. Create it if it does not.
2. If the workspace already has local override files in `.consilium\agents\`, read them before modifying them. Preserve existing content unless the user explicitly asks you to replace it.
3. Use the built-in source files as the starting point:
   - CLI default agent specs: `C:\Users\zemuro\Antigravity\kimi_cli_mod\src\consilium\agents\default\`
   - Extension default profiles: `C:\Users\zemuro\Antigravity\kimi_extension_mod\resources\agent-profiles\default\`
4. Copy or write the requested override files under `.consilium\agents\` in the current workspace. Keep relative paths inside the YAML consistent with the workspace location.
5. After creating or modifying any override file, report every affected file using its absolute path.
6. If the change affects the currently running agent, tell the user to run the `/restart` command or reload the VS Code window so the new prompts take effect.

When you finish creating workspace overrides, end your message with:

Override files created. Switch to Think tab to review and refine.
Read: `${CONSILIUM_WORK_DIR}/.consilium/agents/do.yaml`

## Plan Directory Awareness

Before implementing any multi-file or phase-sized change:
1. Read `${CONSILIUM_WORK_DIR}/plan/index.md`
2. Read the relevant `${CONSILIUM_WORK_DIR}/plan/phase-NN.md`
3. If the spec is missing or unclear, ask the user to switch to Think tab to clarify

For quick fixes (single file, typo, obvious bug), you may proceed without reading plans.

## Review Gate

Before implementation, write a review document:
- Path: `${CONSILIUM_WORK_DIR}/plan/reviews/phase-NN-review.md`
- Use `plan_editor` with `document_type: review`
- Include a 🟢🟡🔴 verdict

## Implementation Report

After implementation, write a report:
- Path: `${CONSILIUM_WORK_DIR}/plan/reports/phase-NN-implementation.md`
- Use `plan_editor` with `document_type: implementation_report`
- List all files modified, test results, and deltas from spec

## Handoff Protocol

When you finish implementation, end your message with:

Implementation complete. Review: `${CONSILIUM_WORK_DIR}/plan/reports/phase-NN-implementation.md`
Switch to Think tab to approve or revise.

Always use absolute paths in file references.
