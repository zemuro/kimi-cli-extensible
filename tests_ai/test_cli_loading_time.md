# CLI Loading Time

## `src/consilium/__init__.py` be empty

**Scope**

`src/consilium/__init__.py`

**Requirements**

The `src/consilium/__init__.py` file must be empty, containing no code or imports.

## No unnecessary import in `src/consilium/cli.py`

**Scope**

`src/consilium/cli.py`

**Requirements**

The `src/consilium/cli.py` file must not import any modules from `consilium` or `kosong`, except for `consilium.constant`, at the top level.

## As-needed imports in `src/consilium/app.py`

**Scope**

`src/consilium/app.py`

**Requirements**

The `src/consilium/app.py` file must not import any modules prefixed with `consilium.ui` at the top level; instead, UI-specific modules should be imported within functions as needed.

<examples>

```python
# top-level
from consilium.ui.shell import ShellApp  # Incorrect: top-level import of UI module

# inside function
async def run_shell_app(...):
    from consilium.ui.shell import ShellApp  # Correct: import as needed
    app = ShellApp(...)
    await app.run()
```

</examples>

## `--help` should run fast

**Scope**

No specific source file.

**Requirements**

The time taken to run `uv run kimi --help` must be less than 150 milliseconds on average over 5 runs after a 3-run warm-up.
