---
phase_id: phase-04a
title: 4: Think — Python Execution & Bridge
status: implemented
dependencies:
  - phase-03
files_involved:
  - src/consilium/think/python_runner.py
  - src/consilium/think/push.py
---

### Architecture

Think mode becomes a first-class strategist. It runs as a **completely disjoint** session from Do mode — separate process, separate context, separate history. The only connection is a **unidirectional push** from Think → Do.

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTENSION HOST                                │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐│
│  │   THINK TAB         │    │   DO TAB                        ││
│  │   (mutable history) │    │   (immutable, git-backed)       ││
│  │   • Brainstorm      │───►│   • Execute tools               ││
│  │   • Plan            │push│   • Inline diffs                ││
│  │   • Audit code      │    │   • Accept/Reject hunks         ││
│  │   • Run Python      │    │   • Change journal              ││
│  └─────────────────────┘    └─────────────────────────────────┘│
│         ▲                            ▲                          │
│         │                            │                          │
│    kimi --wire                  kimi --do --wire                │
│    (ThinkSoul)                  (KimiSoul + DoSession)          │
│    lightweight                  full tooling                    │
│    mutable                      immutable                       │
│    no git                       git snapshotting                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 Python Execution Tool

**File:** `src/consilium/think/python_tool.py` — new module

Think mode gets a `run_python` tool. The LLM generates Python code; the tool executes it and returns output.

```python
"""Python execution tool for Think mode."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from consilium.config import Config
from consilium.utils.logging import logger


class PythonExecutionError(Exception):
    """Python code execution failed."""


class PythonTool:
    """Execute Python code in a restricted or unrestricted environment."""

    def __init__(self, work_dir: Path, config: Config) -> None:
        self.work_dir = work_dir.resolve()
        self.cfg = config.think.python

    async def execute(self, code: str) -> dict[str, Any]:
        """Execute Python code and return results.

        Returns dict with keys:
            - stdout: str
            - stderr: str
            - exit_code: int
            - figures: list[str]  # paths to saved matplotlib figures
            - duration_ms: int
        """
        if self.cfg.restriction_level == "sandboxed":
            return await self._execute_sandboxed(code)
        elif self.cfg.restriction_level == "restricted":
            return await self._execute_restricted(code)
        else:
            return await self._execute_unrestricted(code)

    async def _execute_unrestricted(self, code: str) -> dict[str, Any]:
        """Run with full user permissions. Same risk as existing shell tool."""
        return await self._run_subprocess(code, restricted=False)

    async def _execute_restricted(self, code: str) -> dict[str, Any]:
        """Run with light restrictions: limited imports, workdir file access only."""
        # Validate AST: block dangerous imports
        self._validate_ast(code)
        return await self._run_subprocess(code, restricted=True)

    async def _execute_sandboxed(self, code: str) -> dict[str, Any]:
        """Run inside macOS sandbox-exec ( Seatbelt ). Falls back to restricted on non-macOS."""
        if sys.platform != "darwin":
            logger.warning("sandboxed mode only available on macOS, falling back to restricted")
            return await self._execute_restricted(code)
        return await self._run_sandboxed(code)

    def _validate_ast(self, code: str) -> None:
        """Parse AST and block dangerous imports / calls."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise PythonExecutionError(f"Syntax error: {e}") from e

        blocked_modules = {"os", "subprocess", "socket", "urllib", "http", "ftplib", "telnetlib"}
        if not self.cfg.allow_network:
            blocked_modules |= {"requests", "aiohttp", "httpx", "urllib3"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in blocked_modules:
                        raise PythonExecutionError(f"Import blocked: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in blocked_modules:
                        raise PythonExecutionError(f"Import blocked: {node.module}")
            elif isinstance(node, ast.Call):
                # Block eval, exec, compile, __import__
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
                    raise PythonExecutionError(f"Call blocked: {node.func.id}")

    async def _run_subprocess(self, code: str, restricted: bool) -> dict[str, Any]:
        """Run code via subprocess with optional restriction preloader."""
        import time

        start = time.monotonic()

        # Write code to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            if restricted:
                # Prepend security module that restricts open() to work_dir
                f.write(self._security_prelude())
            f.write("\n")
            # Capture matplotlib figures
            f.write(self._matplotlib_prelude())
            f.write("\n")
            f.write(code)
            f.write("\n")
            f.write(self._matplotlib_postlude())
            script_path = f.name

        # Environment
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["CONSILIUM_WORK_DIR"] = str(self.work_dir)
        if restricted:
            env["CONSILIUM_PYTHON_RESTRICTED"] = "1"
            # Prevent importing from arbitrary paths
            env["PYTHONPATH"] = str(self.work_dir)
            env["PYTHONNOUSERSITE"] = "1"

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=self.work_dir if restricted else None,
                capture_output=True,
                text=True,
                timeout=self.cfg.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise PythonExecutionError(f"Execution timed out after {self.cfg.timeout_seconds}s")
        finally:
            Path(script_path).unlink(missing_ok=True)

        duration_ms = int((time.monotonic() - start) * 1000)

        # Collect matplotlib figures from temp dir
        figures = []
        fig_dir = Path(tempfile.gettempdir()) / "kimi_python_figures"
        if fig_dir.exists():
            for fig in sorted(fig_dir.glob(f"kimi_fig_*.png")):
                figures.append(str(fig))

        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "figures": figures,
            "duration_ms": duration_ms,
        }

    async def _run_sandboxed(self, code: str) -> dict[str, Any]:
        """Run via macOS sandbox-exec wrapper."""
        # Uses sandbox-wrapper.sh from antigravity_extension (adapted)
        # ... implementation details ...
        pass

    def _security_prelude(self) -> str:
        """Python code injected before user code to restrict file access."""
        return '''
import builtins
import os
_original_open = builtins.open
_WORK_DIR = os.environ.get("CONSILIUM_WORK_DIR", ".")

def _restricted_open(path, *args, **kwargs):
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(os.path.abspath(_WORK_DIR)):
        raise PermissionError(f"File access outside work directory blocked: {path}")
    return _original_open(path, *args, **kwargs)

builtins.open = _restricted_open
'''

    def _matplotlib_prelude(self) -> str:
        """Setup matplotlib to save figures instead of displaying."""
        return '''
import os, tempfile
os.environ["MPLBACKEND"] = "Agg"
_kimi_fig_dir = os.path.join(tempfile.gettempdir(), "kimi_python_figures")
os.makedirs(_kimi_fig_dir, exist_ok=True)
'''

    def _matplotlib_postlude(self) -> str:
        """Save any open matplotlib figures."""
        return '''
try:
    import matplotlib.pyplot as _plt
    for i, fig in enumerate(_plt.get_fignums(), 1):
        _plt.figure(fig).savefig(os.path.join(_kimi_fig_dir, f"kimi_fig_{i:03d}.png"), dpi=150, bbox_inches="tight")
    _plt.close("all")
except Exception:
    pass
'''
```

**Restriction levels:**

| Level | File Access | Network | Imports | Platform |
|-------|------------|---------|---------|----------|
| `none` | Full user permissions | Allowed | All | All |
| `restricted` | Work dir only | Configurable | Blocked: `os`, `subprocess`, `socket`, network libs | All |
| `sandboxed` | Seatbelt profile | Configurable | Same as restricted | macOS only |

**File:** `src/consilium/think/__init__.py` — modifications

Register `run_python` as a tool available to ThinkSoul:

```python
# In ThinkSoul.__init__() or tool registration:
from consilium.think.python_tool import PythonTool

self._python_tool = PythonTool(
    work_dir=Path(session.work_dir),
    config=config,
)

# In the tool call handler:
async def handle_tool_call(self, tool_name: str, arguments: dict) -> str:
    if tool_name == "run_python":
        result = await self._python_tool.execute(arguments["code"])
        output_lines = [f"[Python execution: {result['duration_ms']}ms]"]
        if result["stdout"]:
            output_lines.append("--- stdout ---")
            output_lines.append(result["stdout"])
        if result["stderr"]:
            output_lines.append("--- stderr ---")
            output_lines.append(result["stderr"])
        if result["figures"]:
            output_lines.append(f"--- figures: {len(result['figures'])} ---")
            for fig in result["figures"]:
                output_lines.append(fig)
        return "\n".join(output_lines)
    # ... existing tools ...
```

### 4.2 Extension Config for Python Restrictions

**File:** `kimi extension_mod/package.json` — additions to `contributes.configuration`

```json
{
  "kimi.think.python.restrictionLevel": {
    "type": "string",
    "default": "restricted",
    "enum": ["none", "restricted", "sandboxed"],
    "enumDescriptions": [
      "Full Python access (same risk as shell tool)",
      "Work-dir-only file access, blocked dangerous imports, optional network block",
      "macOS Seatbelt sandbox (falls back to restricted on non-macOS)"
    ],
    "description": "Sandbox level for Python code execution in Think mode"
  },
  "kimi.think.python.allowNetwork": {
    "type": "boolean",
    "default": false,
    "description": "Allow Python code to access the network (requests, urllib, etc.)"
  },
  "kimi.think.python.timeoutSeconds": {
    "type": "number",
    "default": 30,
    "minimum": 1,
    "maximum": 300,
    "description": "Maximum execution time for Python code in seconds"
  },
  "kimi.think.python.maxMemoryMB": {
    "type": "number",
    "default": 512,
    "minimum": 64,
    "description": "Maximum memory for Python subprocess in MB (best-effort)"
  },
  "kimi.think.python.autoApprove": {
    "type": "boolean",
    "default": false,
    "description": "Auto-approve Python tool calls without user confirmation"
  }
}
```

**File:** `kimi extension_mod/src/config/vscode-settings.ts` — additions

Expose the new settings to the extension's config module so they can be passed as environment variables to the CLI process.

### 4.3 Think → Do Bridge

**⚠️ SUPERCEDED by §4d (Plan-Driven Think/Do Orchestration).** The original design below pushed raw conversation history via JSON outbox files. The current architecture (§4d) uses structured Markdown plan documents in `plan/index.md` with phased implementation, external memory, and bidirectional artifact exchange. The code in `src/consilium/think/push.py` and the `--seed-from-think` flag remain for backward compatibility but are considered legacy.

**Concept:** Think produces plans, reviews, audit results. The user (or automation) pushes selected content into a Do session. Think continues independently.

**File:** `src/consilium/think/push.py` — new module

```python
"""Think → Do bridge: export Think history for Do session seeding."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kosong.message import Message

from consilium.think.models import ThinkMessage, ThinkSession
from consilium.think.storage import think_path

OUTBOX_DIR = Path.home() / ".consilium" / "think_outbox"


def export_think_history(
    think_session: ThinkSession,
    turn_range: tuple[int, int] | None = None,
) -> Path:
    """Export Think messages to a JSON seed file for Do mode.

    Args:
        think_session: The Think session to export from.
        turn_range: Optional (start, end) inclusive range of message indices.
            None = export all messages.

    Returns:
        Path to the written seed file.
    """
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

    messages = think_session.messages
    if turn_range is not None:
        start, end = turn_range
        messages = messages[start:end + 1]

    # Convert ThinkMessage to upstream Message format
    seed_messages: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            continue  # Do mode uses its own system prompt
        seed_messages.append({
            "role": msg.role,
            "content": [{"type": "text", "text": msg.content}],
        })

    seed_data = {
        "think_session_id": think_session.id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "messages": seed_messages,
    }

    seed_file = OUTBOX_DIR / f"{think_session.id}.json"
    seed_file.write_text(json.dumps(seed_data, indent=2), encoding="utf-8")
    return seed_file
```

**File:** `src/consilium/think/slash.py` — additions (Think mode slash commands)

```python
@slash_command("/push-to-do")
async def slash_push_to_do(soul: ThinkSoul, args: str) -> None:
    """Export Think conversation to a seed file for Do mode.

    Usage: /push-to-do [start]-[end]
    Examples:
        /push-to-do         # Export all messages
        /push-to-do 5-10    # Export messages 5 through 10
        /push-to-do -5      # Export last 5 messages
    """
    from consilium.think.push import export_think_history

    think_session = soul._think_session
    turn_range = None

    args = args.strip()
    if args:
        if "-" in args:
            parts = args.split("-", 1)
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else len(think_session.messages) - 1
            turn_range = (start, end)
        else:
            idx = int(args)
            turn_range = (idx, idx)

    seed_file = export_think_history(think_session, turn_range)
    wire_send(TextPart(
        text=f"Exported {len(think_session.messages)} messages to {seed_file}\n"
             f"Do mode can seed from this file with --seed-from-think {think_session.id}"
    ))
```

**File:** `src/consilium/cli/__init__.py` — additions

Add `--seed-from-think` CLI flag:

```python
seed_from_think: Annotated[
    str | None,
    typer.Option(
        "--seed-from-think",
        help="Seed Do mode context from a Think session export file",
    ),
] = None,
```

**File:** `src/consilium/app.py` — modifications in `KimiCLI.create()`

When `do_mode=True` and `seed_from_think` is provided, pre-populate the context:

```python
# After creating Context, before KimiSoul:
if do_mode and seed_from_think:
    from consilium.think.push import OUTBOX_DIR
    seed_file = OUTBOX_DIR / f"{seed_from_think}.json"
    if seed_file.exists():
        seed_data = json.loads(seed_file.read_text(encoding="utf-8"))
        for msg_data in seed_data.get("messages", []):
            await context.append_message(Message(**msg_data))
        logger.info("Seeded Do context from Think session %s", seed_from_think)
```

**File:** `src/consilium/soul/kimisoul.py` — additions

Expose a wire command or slash command to receive pushed messages directly from the extension:

```python
@slash_command("/inject")
async def slash_inject(soul: KimiSoul, args: str) -> None:
    """Inject a system or user message into the context (used by extension push)."""
    # Parse args: "role: content"
    if ":" not in args:
        wire_send(TextPart(text="Usage: /inject <role>: <content>"))
        return
    role, content = args.split(":", 1)
    role = role.strip()
    content = content.strip()
    if role not in {"user", "system", "assistant"}:
        wire_send(TextPart(text=f"Invalid role: {role}"))
        return
    await soul.context.append_message(Message(role=role, content=[{"type": "text", "text": content}]))
    wire_send(TextPart(text=f"Injected {role} message."))
```

### 4.4 Backend Web API

**Status: DEFERRED.**

The web server (`kimi web`) is only started by explicit commands and is not available in wire/ACP/shell modes. The extension runs the CLI in wire mode (`kimi --wire`), so HTTP endpoints are unreachable.

**Alternative:** The extension reads the journal file directly from disk at `~/.consilium/do_sessions/{session_id}/journal.jsonl`. No CLI changes needed.

When the web server is running, these endpoints would be useful:
- `GET /{session_id}/changes` — query journal entries
- `GET /{session_id}/baselines/{content_hash}` — retrieve blob content
- `GET /{session_id}/turns/{turn_index}/summary` — aggregated turn stats

See git history for the full endpoint implementations if needed in the future.

### 4.5 Wire Protocol Extension

**File:** `src/consilium/wire/types.py` — additions

```python
class ToolFileModifiedEvent(BaseModel):
    """Sent when a tool call modifies a file in Do mode.

    The extension uses this to open or refresh an inline diff view.
    """

    type: Literal["tool_file_modified"] = "tool_file_modified"
    entry_id: str
    turn_index: int
    step_index: int
    tool_call_id: str
    tool_name: str
    path: str
    baseline_hash: str
    post_hash: str
    lines_added: int
    lines_removed: int
```

**File:** `src/consilium/do/session.py` — additions in `on_tool_result()`

After recording the diff in the journal, send a wire event:

```python
# After: await self.journal.append(entry)
from consilium.wire import wire_send
from consilium.wire.types import ToolFileModifiedEvent

wire_send(ToolFileModifiedEvent(
    entry_id=entry.id,
    turn_index=entry.turn_index,
    step_index=entry.step_index,
    tool_call_id=entry.tool_call_id,
    tool_name=entry.tool_name,
    path=entry.path,
    baseline_hash=entry.baseline_hash,
    post_hash=entry.post_hash,
    lines_added=entry.lines_added,
    lines_removed=entry.lines_removed,
))
```

### 4.6 Config Additions

**File:** `src/consilium/config.py` — additions

```python
class PythonConfig(BaseModel):
    """Configuration for Python execution in Think mode."""

    restriction_level: Literal["none", "restricted", "sandboxed"] = Field(
        default="restricted",
        description="Sandbox level for Python execution",
    )
    allow_network: bool = Field(default=False)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_memory_mb: int = Field(default=512, ge=64)
    auto_approve: bool = Field(default=False)


class ThinkConfig(BaseModel):
    """Existing ThinkConfig + new python field."""
    # ... existing fields ...
    python: PythonConfig = Field(default_factory=PythonConfig)
```

### 4.7 Testing Requirements

| Test | File | Description |
|------|------|-------------|
| `test_python_execute_hello_world` | `tests/core/test_python_tool.py` | Basic execution returns stdout |
| `test_python_execute_blocked_import` | `tests/core/test_python_tool.py` | Restricted mode blocks `os.system` |
| `test_python_execute_matplotlib` | `tests/core/test_python_tool.py` | Figure captured and returned |
| `test_python_execute_timeout` | `tests/core/test_python_tool.py` | Infinite loop killed at timeout |
| `test_python_execute_network_blocked` | `tests/core/test_python_tool.py` | `requests` blocked when allow_network=false |
| `test_push_to_do_creates_seed` | `tests/core/test_push_bridge.py` | Export Think history to JSON |
| `test_seed_from_think_populates_context` | `tests/core/test_push_bridge.py` | Do mode reads seed file into context |
| `test_wire_tool_file_modified_event` | `tests/core/test_wire_events.py` | Event sent after file-modifying tool call |
| `test_force_abort_closes_stream` | `tests/core/test_instant_cancel.py` | `force_abort()` kills in-flight HTTP request within 100ms |

---

### 4.8 Instant Stream Cancellation (`force_abort`)

**Status: Fork-specific enhancement. Upstream issue filed; see §5.1 for upstream path.**

**Discovery:** `kosong.step()` already catches `asyncio.CancelledError` and cleans up tool-result futures correctly. The problem is that `asyncio.Task.cancel()` only injects `CancelledError` at the next `await` boundary. When the LLM is in a deep thinking block, `stream.__anext__()` may not yield for minutes, so cancellation stalls.

**Solution:** Close the provider's HTTP client from `_handle_cancel()`. The in-flight request immediately aborts with `httpx.HTTPError`, the provider re-raises as `ChatProviderError`, and `step()` propagates it. The whole turn unwinds in milliseconds.

#### Why this works

All major providers store an `httpx.AsyncClient`-backed SDK client internally:
- `Kimi` → `self.client` (`AsyncOpenAI`)
- `OpenAIResponses` → `self._client` (`AsyncOpenAI`)
- `OpenAILegacy` → `self._client` (`AsyncOpenAI`)
- `Anthropic` → `self._client` (`Anthropic` SDK client)

These providers already have `on_retryable_error()` code that **closes and replaces** the client:

```python
def on_retryable_error(self, error: BaseException) -> bool:
    old_client = self._client
    self._client = create_openai_client(...)
    close_replaced_openai_client(old_client, client_kwargs=self._client_kwargs)
    return True
```

We repurpose this pattern into an explicit `force_abort()` method that can be called on demand.

#### Provider changes

**File:** `src/consilium/chat_provider_ext.py` — new module

```python
"""Fork-specific extensions to kosong chat providers for instant cancellation."""

from kosong.chat_provider.openai_common import close_replaced_openai_client
from kosong.contrib.chat_provider.openai_responses import OpenAIResponses
from kosong.contrib.chat_provider.openai_legacy import OpenAILegacy
from kosong.chat_provider.consilium import Kimi


async def _force_abort_openai(provider: OpenAIResponses | OpenAILegacy | Kimi) -> None:
    """Close the provider's HTTP client, aborting any in-flight request."""
    client_attr = "client" if isinstance(provider, Kimi) else "_client"
    old_client = getattr(provider, client_attr)
    kwargs = provider._client_kwargs
    new_client = create_openai_client(
        api_key=getattr(provider, "_api_key", old_client.api_key),
        base_url=getattr(provider, "_base_url", None),
        client_kwargs=kwargs,
    )
    setattr(provider, client_attr, new_client)
    close_replaced_openai_client(old_client, client_kwargs=kwargs)


# Monkey-patch providers at import time
OpenAIResponses.force_abort = lambda self: _force_abort_openai(self)
OpenAILegacy.force_abort = lambda self: _force_abort_openai(self)
Kimi.force_abort = lambda self: _force_abort_openai(self)
```

**Anthropic provider** (`packages/kosong/src/kosong/contrib/chat_provider/anthropic.py`) needs a separate implementation because it uses the Anthropic SDK, not OpenAI:

```python
# In src/consilium/chat_provider_ext.py or a provider-specific patch
async def _force_abort_anthropic(provider: Anthropic) -> None:
    old_client = provider._client
    # Anthropic client recreation
    from anthropic import AsyncAnthropic
    provider._client = AsyncAnthropic(
        api_key=provider._api_key,
        base_url=provider._base_url,
        # ... other kwargs from provider._client_kwargs
    )
    await old_client.close()
```

**Google GenAI** — deferred; the Google SDK uses a different transport. Can fall back to cooperative cancellation.

#### Wire server changes

**File:** `src/consilium/wire/server.py` — modification to `_handle_cancel()`

```python
async def _handle_cancel(self, msg: JSONRPCCancelMessage) -> ...:
    if not self._is_streaming:
        return JSONRPCErrorResponse(...)

    assert self._cancel_event is not None
    self._cancel_event.set()

    # FORK-SPECIFIC: Force abort the HTTP stream for instant cancellation
    if isinstance(self._soul, KimiSoul):
        llm = self._soul.runtime.llm
        if llm is not None:
            provider = llm.chat_provider
            if hasattr(provider, "force_abort"):
                try:
                    await provider.force_abort()
                except Exception:
                    logger.exception("force_abort failed")

    return JSONRPCSuccessResponse(id=msg.id, result={})
```

**Key design decision:** The `hasattr(provider, "force_abort")` gate means:
- Providers with the patch get instant cancellation
- Providers without it fall back to cooperative cancellation
- No upstream divergence if the method doesn't exist
- Easy to remove when upstream adds proper abort signals

#### Exception flow after `force_abort()`

```
[force_abort() called]
  → old_client closed → httpx aborts in-flight request
  → stream.__anext__() throws httpx.HTTPError immediately
  → Provider catches → raises ChatProviderError
  → kosong.generate() propagates
  → kosong.step() catches ChatProviderError → cancels tool futures → re-raises
  → KimiSoul._agent_loop() catches ChatProviderError (except Exception)
  → Turn ends with error message
```

**Latency:** milliseconds, not minutes.

#### Upstream compatibility

| Concern | Mitigation |
|---------|------------|
| kosong changes | **None.** All changes are in fork code. |
| Provider private attrs | Uses `_client` / `client` which are stable in current kosong. A rename would break this but is unlikely. |
| Future turns broken | No — client is replaced with a fresh one. |
| Extension compatibility | Extension sends `cancel` wire event same as before. It doesn't know about `force_abort`. |
| Feature flag | Implicit — `hasattr` gate. Can also add explicit `kimi.experimental.instant_cancel = true` config if desired. |

---
