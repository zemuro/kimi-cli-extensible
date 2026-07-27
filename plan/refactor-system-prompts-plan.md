# Refactoring Plan: System Prompt Variable Migration

## Issue Identified
The system prompts in `/c/Users/zemuro/Antigravity/kimi_cli_mod/.consilium/agents/prompts/system/` contain unresolved KIMI variables that break agent functionality:
- `${KIMI_OS}` → `${CONSILIUM_OS}`
- `${KIMI_SHELL}` → `${CONSILIUM_SHELL}` 
- `${KIMI_WORK_DIR}` → `${CONSILIUM_WORK_DIR}`
- `${KIMI_NOW}` → `${CONSILIUM_NOW}`
- `${KIMI_WORK_DIR_LS}` → `${CONSILIUM_WORK_DIR_LS}`
- `${KIMI_ADDITIONAL_DIRS_INFO}` → `${CONSILIUM_ADDITIONAL_DIRS_INFO}`
- `${KIMI_AGENTS_MD}` → `${CONSILIUM_AGENTS_MD}`
- `${KIMI_SKILLS}` → `${CONSILIUM_SKILLS}`

## Refactoring Approach

### 1. Update Working Environment Prompt
**File:** `working_environment.md`
Replace all KIMI variables with CONSILIUM equivalents

### 2. Update Project Info Prompt  
**File:** `project_info.md`
Replace `${KIMI_AGENTS_MD}` with `${CONSILIUM_AGENTS_MD}`

### 3. Update Skills Prompt
**File:** `skills.md`
Replace `${KIMI_SKILLS}` with `${CONSILIUM_SKILLS}`

### 4. Update System Prompt Assembly Logic
The `__init__.py` file in the system prompts directory likely needs updates to properly populate these variables.

## Implementation Steps

1. **Create backup** of all system prompt files
2. **Replace variable references** in each markdown file
3. **Update assembly logic** if needed in `__init__.py`
4. **Verify** that the new variables resolve properly
5. **Test** system prompt generation

## Expected Benefits
- Fixes broken system prompt rendering
- Enables proper agent contextual awareness
- Completes the Kimi→Consilium migration properly
- Allows agent to properly understand its environment