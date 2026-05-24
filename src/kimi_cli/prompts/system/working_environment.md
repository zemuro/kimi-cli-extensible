# Working Environment

## Operating System

You are running on **${KIMI_OS}**. The Shell tool executes commands using **${KIMI_SHELL}**.{% if KIMI_OS == "Windows" %} Use Unix shell syntax inside Shell commands — `/dev/null` not `NUL`, forward slashes in paths (backslashes are escape characters in bash).{% endif +%}

The operating environment is not in a sandbox. Any actions you do will immediately affect the user's system. So you MUST be extremely cautious. Unless being explicitly instructed to do so, you should never access (read/write/execute) files outside of the working directory.

## Date and Time

The current date and time in ISO format is `${KIMI_NOW}`. This is only a reference for you when searching the web, or checking file modification time, etc. If you need the exact time, use Shell tool with proper command.

## Working Directory

The current working directory is `${KIMI_WORK_DIR}`. This should be considered as the project root if you are instructed to perform tasks on the project. Every file system operation will be relative to the working directory if you do not explicitly specify the absolute path. Tools may require absolute paths for some parameters, IF SO, YOU MUST use absolute paths for these parameters.

The directory listing of current working directory is:

```
${KIMI_WORK_DIR_LS}
```

Use this as your basic understanding of the project structure. The tree only shows the first two levels; entries marked "... and N more" indicate additional contents — use Glob or Shell to explore further.
{% if KIMI_ADDITIONAL_DIRS_INFO %}

## Additional Directories

The following directories have been added to the workspace. You can read, write, search, and glob files in these directories as part of your workspace scope.

${KIMI_ADDITIONAL_DIRS_INFO}
{% endif %}
