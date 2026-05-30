---
phase_id: phase-02
title: 2: Think Mode
status: implemented
dependencies:
  - phase-01
files_involved:
  - src/kimi_cli/think/
  - src/kimi_cli/think/slash_commands.py
---

**Goal:** A mutable-history REPL for speculative reasoning, stored separately from upstream sessions.

### Data Model

```python
# src/kimi_cli/think/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

@dataclass
class ThinkMessage:
    id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:8]}")
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tokens_in: int | None = None
    tokens_out: int | None = None
    deleted: bool = False
    edited_at: datetime | None = None

@dataclass
class ThinkSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[ThinkMessage] = field(default_factory=list)
    system_prompt: str = "You are a helpful assistant."
    checkpoint_name: str | None = None  # if resumed from checkpoint
```

### Storage Format (JSONL)

Path: `~/.kimi/think_sessions/{session_id}.jsonl`

Each line is a JSON object representing one `ThinkMessage`. The first line is always the system message.

Checkpoints: `~/.kimi/think_sessions/{session_id}/checkpoints/{name}.json` — full `ThinkSession` serialized.

### Implementation Steps

#### Step 2.1: Create `src/kimi_cli/think/` package

Files to create:
- `src/kimi_cli/think/__init__.py`
- `src/kimi_cli/think/models.py` — dataclasses above
- `src/kimi_cli/think/storage.py` — JSONL load/save
- `src/kimi_cli/think/history.py` — CRUD operations
- `src/kimi_cli/think/context.py` — assemble active context for API
- `src/kimi_cli/think/repl.py` — Think mode REPL loop

#### Step 2.2: Implement JSONL storage

```python
# src/kimi_cli/think/storage.py
import json
from pathlib import Path
from .models import ThinkSession, ThinkMessage

THINK_DIR = Path.home() / ".kimi" / "think_sessions"

def save_session(session: ThinkSession) -> None:
    path = THINK_DIR / f"{session.id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for msg in session.messages:
            f.write(json.dumps({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "tokens_in": msg.tokens_in,
                "tokens_out": msg.tokens_out,
                "deleted": msg.deleted,
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
            }) + "\n")

def load_session(session_id: str) -> ThinkSession | None:
    path = THINK_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return None
    messages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            messages.append(ThinkMessage(...))
    return ThinkSession(id=session_id, messages=messages)

def list_sessions() -> list[tuple[str, datetime]]:
    """Return (session_id, modified_time) for all think sessions."""
    ...
```

#### Step 2.3: Implement history CRUD

```python
# src/kimi_cli/think/history.py
from .models import ThinkSession, ThinkMessage

class HistoryManager:
    def __init__(self, session: ThinkSession) -> None:
        self.session = session

    def add_message(self, role: str, content: str) -> ThinkMessage:
        msg = ThinkMessage(role=role, content=content)
        self.session.messages.append(msg)
        return msg

    def edit_message(self, msg_id: str, new_content: str) -> ThinkMessage:
        msg = self._get(msg_id)
        msg.content = new_content
        msg.edited_at = datetime.now()
        return msg

    def delete_message(self, msg_id: str) -> None:
        msg = self._get(msg_id)
        msg.deleted = True

    def get_active_messages(self) -> list[ThinkMessage]:
        """Return non-deleted messages in chronological order."""
        return [m for m in self.session.messages if not m.deleted]

    def fork_from(self, msg_id: str) -> ThinkSession:
        """Create new session with messages up to and including msg_id."""
        ...

    def _get(self, msg_id: str) -> ThinkMessage:
        for m in self.session.messages:
            if m.id == msg_id:
                return m
        raise KeyError(f"Message {msg_id} not found")
```

#### Step 2.4: Implement context assembly

```python
# src/kimi_cli/think/context.py
from kosong.message import Message, TextPart
from .models import ThinkSession

def assemble_context(session: ThinkSession, budget_tokens: int | None = None) -> list[Message]:
    """Build OpenAI-compatible message list from ThinkSession.

    1. Prepend system prompt
    2. Add active messages in chronological order
    3. Drop oldest non-system messages if over budget
    """
    messages: list[Message] = [Message(role="system", content=[TextPart(text=session.system_prompt)])]
    active = [m for m in session.messages if not m.deleted and m.role != "system"]
    for msg in active:
        messages.append(Message(role=msg.role, content=[TextPart(text=msg.content)]))
    # TODO: token truncation if budget exceeded
    return messages
```

**Important:** The `kosong.message.Message` class is the internal message format used by the LLM pipeline. Convert `ThinkMessage` to `kosong.message.Message` before sending to `create_llm()` or `kosong.step()`.

#### Step 2.5: Implement REPL loop

```python
# src/kimi_cli/think/repl.py
async def think_repl(
    session: ThinkSession,
    llm: LLM,
    config: Config,
    budget_tokens: int | None = None,
) -> None:
    """Think mode REPL loop.

    - Mutable history
    - No tool execution
    - Slash commands: /history, /edit, /delete, /regenerate, /prune, /checkpoint, /promote
    """
    history = HistoryManager(session)
    # Initialize LLM conversation with system prompt
    while True:
        user_input = await prompt("think> ")
        if user_input.startswith("/"):
            await handle_think_slash_command(user_input, history, session)
            continue
        msg = history.add_message("user", user_input)
        context = assemble_context(session)
        # Call LLM via kosong
        response = await call_llm(context, llm, config)
        assistant_msg = history.add_message("assistant", response)
        # Log tokens
        ...
```

**LLM calling pattern:** Use `kosong.generate()` or `kosong.step()` directly, bypassing `KimiSoul` (which is designed for the upstream agent loop with tools). Think mode is simpler — just chat completion.

```python
from kosong import generate

async def call_llm(messages: list[Message], llm: LLM, config: Config) -> str:
    result = await generate(
        llm.chat_provider,
        system_prompt="",  # already in messages[0]
        tools=[],  # no tools in Think mode
        history=messages[1:],  # exclude system
    )
    return result.message.extract_text()
```

#### Step 2.6: Wire CLI entry points

**File:** `src/kimi_cli/cli/__init__.py`

Modify the main `kimi` command to default to Think mode. Add explicit subcommands:

```python
# In the main CLI function:
if think_mode or not do_mode:
    # Open Think REPL
    await think_repl(session, llm, config)
else:
    # Open upstream Do REPL (existing behavior)
    await KimiCLI.create(...)
```

Actually, a cleaner approach: keep the existing `kimi` entry point but add a `--think` flag. Default to Think mode when no mode is specified.

```python
# Add to CLI options:
think: Annotated[
    bool,
    typer.Option("--think", help="Open Think mode (default)."),
] = True,
do: Annotated[
    bool,
    typer.Option("--do", help="Open Do mode (agent loop with tools)."),
] = False,
```

Logic:
```python
if do:
    # Existing upstream agent REPL
    instance = await KimiCLI.create(...)
else:
    # Think mode
    await run_think_repl(session, llm, config, budget_tokens)
```

#### Step 2.7: Implement `$EDITOR` integration

```python
# src/kimi_cli/utils/editor.py
import os
import subprocess
import tempfile
from pathlib import Path

async def open_editor(initial_text: str) -> str:
    """Open $EDITOR with initial text, return edited text."""
    editor = os.environ.get("EDITOR", "vim")
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".md", delete=False) as f:
        f.write(initial_text)
        path = Path(f.name)
    try:
        subprocess.run([editor, str(path)], check=True)
        return path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)
```

### Testing Requirements

- `test_think_storage_roundtrip()` — save and load ThinkSession, verify all fields
- `test_think_history_crud()` — add, edit, delete messages
- `test_think_context_assembles_active_only()` — deleted messages excluded
- `test_think_repl_slash_commands()` — mock input, verify history state
- `test_think_checkpoint_save_restore()` — save checkpoint, load, verify identical

---
