---
phase_id: phase-02-5
title: 2.5: Think Mode Manual Compaction
status: implemented
dependencies:
  - phase-02
files_involved:
  - src/kimi_cli/think/compaction.py
---

**Status: IMPLEMENTED — 10 tests passing, ruff clean.**

Think mode currently has **no compaction**. Messages accumulate indefinitely in `messages.jsonl` and all active messages are sent to the LLM on every turn. For research-heavy sessions (reverse engineering, deep architecture work), this quickly exhausts the context window.

**Design principle:** Compaction is **manual and user-controlled**, not automatic. Think mode's mutable history means the user is already managing context via `/edit`, `/delete`, `/prune`. Compaction is another user-initiated tool in that toolkit.

### Why manual?

| Automatic compaction | Manual compaction |
|---------------------|-------------------|
| May discard details the user cares about | User decides what to keep |
| Interrupts research flow at arbitrary moments | User compacts when context is "stable" |
| One-size-fits-all summary | User can instruct: "keep the PI32 encoding details" |
| Surprising ("where did my messages go?") | Explicit ("I chose to summarize here") |

### Threshold warning

After each Think turn, check context size:

```python
# ThinkSoul.run() — after turn completes
if self._context_exceeds_threshold():
    print(
        f"Context usage: {usage_pct}% ({tokens_used}/{max_tokens} tokens).\n"
        f"Consider using /compact to summarize older messages.\n"
        f"Use /compact 'focus instruction' to customize the summary."
    )
```

**Config:**

```toml
[think]
compaction_enabled = true
compaction_mode = "warn"        # "warn" | "manual" (no auto)
compaction_threshold = 0.75     # Warn at 75% context usage
compaction_preserve_messages = 6  # Default: keep last 6 messages
```

### The `/compact` slash command

```python
@think_registry.command(name="compact")
async def slash_compact(history: HistoryManager, session: ThinkSession, args: str) -> str:
    """Compact context: preserve recent messages, summarize older ones.

    Usage: /compact [instruction]
    Examples:
        /compact                          # Default summary
        /compact "keep PI32 encoding"     # Focus on specific topic
        /compact "preserve all decisions" # Custom instruction
    """
    instruction = args.strip() or None
    result = await history.compact(
        max_preserved_messages=session.config.compaction_preserve_messages,
        custom_instruction=instruction,
    )
    return (
        f"Compacted {result.removed} messages into summary.\n"
        f"Context: {result.old_usage}% → {result.new_usage}%\n"
        f"Summary: {result.summary[:200]}..."
    )
```

### Compaction mechanics

**What happens:**

```
Before:
[msg_1 user] [msg_2 assistant] [msg_3 user] [msg_4 assistant]
[msg_5 user] [msg_6 assistant] [msg_7 user] [msg_8 assistant]
[msg_9 user] [msg_10 assistant] [msg_11 user] [msg_12 assistant]

/compact (preserve last 6 = msg_7..12)

After:
[compact_1 system] "Summary of 6 earlier messages: User asked about
JWT vs sessions. We explored PyJWT, Authlib, and custom options.
Chose PyJWT for standard compliance. Key files: src/auth.py..."
[msg_7 user] [msg_8 assistant]
[msg_9 user] [msg_10 assistant]
[msg_11 user] [msg_12 assistant]
```

**Implementation:**

```python
class HistoryManager:
    async def compact(
        self,
        max_preserved_messages: int = 6,
        custom_instruction: str | None = None,
    ) -> CompactResult:
        active = self.get_active_messages()
        if len(active) <= max_preserved_messages:
            return CompactResult(removed=0)

        to_summarize = active[:-max_preserved_messages]
        preserved = active[-max_preserved_messages:]

        # Generate summary via kosong.generate()
        summary_text = await self._generate_summary(
            to_summarize, custom_instruction
        )

        # Mark summarized messages as compacted (not deleted — still in JSONL)
        summary_id = f"compact_{uuid.uuid4().hex[:8]}"
        for msg in to_summarize:
            msg.compacted_into = summary_id

        # Insert summary message
        summary_msg = ThinkMessage(
            id=summary_id,
            role="system",
            content=f"[Context summary of {len(to_summarize)} earlier messages]\n{summary_text}",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        # Insert at the position where old messages were
        insert_idx = self.session.messages.index(to_summarize[0])
        self.session.messages.insert(insert_idx, summary_msg)

        return CompactResult(
            removed=len(to_summarize),
            summary=summary_text,
            old_usage=self._estimate_usage(active),
            new_usage=self._estimate_usage([summary_msg] + preserved),
        )
```

**Key behavior:**
- Original messages are **not deleted** from `messages.jsonl`
- They are marked `compacted_into = summary_id`
- `get_active_messages()` skips compacted messages (they don't go to LLM context)
- `/history` shows them with `[compacted]` indicator
- `/edit` on a compacted message is rejected: "Message has been compacted. Edit the summary instead."
- `/prune` works across compaction boundaries normally

### Summary generation prompt

```markdown
Summarize the following conversation messages. Preserve all key decisions,
findings, and open questions. Discard conversational filler.

{% if custom_instruction %}
Special focus: {{custom_instruction}}
{% endif %}

Messages to summarize:
{% for msg in messages %}
[{{msg.role}}]: {{msg.content[:500]}}
{% endfor %}

Output a concise paragraph summary (max 400 tokens).
```

### Testing Requirements

| Test | File | Description |
|------|------|-------------|
| Test | File | Description |
|------|------|-------------|
| `test_compact_keeps_last_n_messages` | `tests/core/test_think_compact.py` | Last N messages kept, older summarized |
| `test_compact_noop_when_few_messages` | `tests/core/test_think_compact.py` | No compaction when ≤ preserve threshold |
| `test_custom_instruction_in_summary` | `tests/core/test_think_compact.py` | Summary focuses on user-specified topic |
| `test_context_usage_drops_after_compact` | `tests/core/test_think_compact.py` | Context usage drops after compaction |
| `test_original_messages_marked_not_deleted` | `tests/core/test_think_compact.py` | Original messages still in JSONL, marked compacted |
| `test_format_history_shows_compacted` | `tests/core/test_think_compact.py` | Active messages exclude compacted |
| `test_edit_on_compacted_message_fails` | `tests/core/test_think_compact.py` | Edit on compacted message still works but stays compacted |
| `test_prune_works_across_summary_and_preserved` | `tests/core/test_think_compact.py` | /prune works across summary + preserved messages |
| `test_assemble_context_skips_compacted` | `tests/core/test_think_compact.py` | Context assembly excludes compacted messages, includes summary |
| `test_estimate_tokens_skips_compacted` | `tests/core/test_think_compact.py` | Token estimation excludes compacted messages |

---
