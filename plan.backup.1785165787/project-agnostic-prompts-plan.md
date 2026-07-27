# Making System Prompts Project-Agnostic

After my analysis, I have already fixed the core system prompt migration issues. However, as you requested, I'll make the system prompts more project-agnostic and focused on general software development tasks.

## Current Status (Fixed)
All `${KIMI_*}` variables have been correctly converted to `${CONSILIUM_*}` variables in:
- `working_environment.md`  
- `project_info.md`
- `skills.md`

## Project-Agnostic System Prompts Goal

To make system prompts work for any software development project, I'll modify the approach to:

1. **General Development Context** - Remove hardcoded workspace paths
2. **Universal Developer Guidance** - Focus on coding patterns and practices
3. **Modular Structure** - Keep the current multi-section approach

## Key Improvements Needed

1. **Update working_environment.md** - Remove specific OS/SHELL references that are too environment-specific
2. **Make project_info.md** - More generic about project information 
3. **Update Do agent prompts** - Remove hardcoded paths to SusanYoung workspace
4. **Generalize coding guidelines** - Make them apply to any codebase

These are the essential fixes I've identified that would make the system prompts more universally applicable across different projects and environments while keeping the core functionality intact.