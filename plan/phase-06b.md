# Phase 6B: Session Pairing Support for Dual-Process

## Summary

Add minimal CLI-side support for persistent Think/Do session pairing. This enables the extension's meta-session rename, paired loading, and cascade delete features (Extension Phase 7.5).

**Scope:** Small, additive changes to existing models and the Think→Do handoff. No new storage layers.

**Prerequisite:** Phase 6a (peer status coordination) complete.

---

## Changes

### 1. `src/consilium/session_state.py` — Add `paired_session_id`

**Change:** One new field on `SessionState`.

```python
class SessionState(BaseModel):
    version: int = 1
    approval: ApprovalStateData = Field(default_factory=ApprovalStateData)
    additional_dirs: list[str] = Field(default_factory=list)
    custom_title: str | None = None
    title_generated: bool = False
    title_generate_attempts: int = 0
    plan_mode: bool = False
    plan_session_id: str | None = None
    plan_slug: str | None = None
    wire_mtime: float | None = None
    archived: bool = False
    archived_at: float | None = None
    auto_archive_exempt: bool = False
    todos: list[TodoItemState] = Field(default_factory=list)
    paired_session_id: str | None = None  # ← NEW
```

**Why it works without migration:** `SessionState.model_validate(json.load(f))` is a Pydantic validator. Old `state.json` files that lack `paired_session_id` will simply get `None` as the default. New files written after this change will include the field.

---

### 2. `src/consilium/plan/models.py` — Add `think_session_id` to `Dispatch`

**Change:** One new field on `Dispatch`.

```python
class Dispatch(BaseModel):
    dispatch_id: str
    plan_id: str
    plan_file: str | None = None
    action: DispatchAction
    target_phase: str
    dispatched_at: float = Field(default_factory=lambda: __import__("time").time())
    dispatched_by: Literal["think", "user", "afk_auto"] = "think"
    require_user_approval: bool = True
    afk_mode: bool = False
    think_session_id: str | None = None  # ← NEW
```

---

### 3. `src/consilium/plan/dispatch.py` — Accept `think_session_id`

**Change:** Add parameter and pass it through.

```python
def write_dispatch(
    plan_id: str,
    target_phase: str,
    plan_file: str | None = None,
    action: DispatchAction = None,
    require_user_approval: bool = True,
    afk_mode: bool = False,
    dispatched_by: str = "think",
    think_session_id: str | None = None,  # ← NEW
) -> Dispatch:
    # ... existing validation ...

    dispatch = Dispatch(
        dispatch_id=f"disp_{time.time():.0f}_{uuid.uuid4().hex[:6]}",
        plan_id=plan_id,
        plan_file=plan_file,
        action=action,
        target_phase=target_phase,
        dispatched_by=dispatched_by,
        require_user_approval=require_user_approval,
        afk_mode=afk_mode,
        think_session_id=think_session_id,  # ← NEW
    )

    DISPATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISPATCH_PATH.write_text(dispatch.model_dump_json(indent=2), encoding="utf-8")
    return dispatch
```

---

### 4. `src/consilium/think/push.py` — Pass Think session ID

**Change:** Accept and forward `think_session_id`.

```python
def push_plan_to_do(
    plan_file: Path,
    target_phase: str,
    think_session_id: str | None = None,  # ← NEW
) -> Dispatch:
    """Write a dispatch signal pointing to the plan document."""
    from consilium.plan.dispatch import write_dispatch
    from consilium.plan.models import DispatchAction
    from consilium.plan.parser import parse_plan_directory_from_path

    if not plan_file.exists():
        raise RuntimeError(f"No plan found at {plan_file}. Use /plan init first.")

    plan_dir = parse_plan_directory_from_path(plan_file)
    return write_dispatch(
        plan_id=plan_dir.metadata.plan_id or "untitled",
        target_phase=target_phase,
        plan_file=str(plan_file),
        action=DispatchAction.START_IMPLEMENT,
        think_session_id=think_session_id,  # ← NEW
    )
```

---

### 5. `src/consilium/think/slash.py` — Pass Think session ID on `/push-to-do`

**Change:** Find the Think session ID and pass it.

```python
async def slash_push_to_do(think_soul: ThinkSoul, args: str) -> str:
    """Push the current plan to Do mode."""
    # ... existing validation ...

    # Get the Think session ID
    think_session_id = think_soul.session.id  # or think_soul._session.id — verify attribute

    dispatch = push_plan_to_do(plan_file, target_phase, think_session_id=think_session_id)
    return f"Dispatched plan to Do mode.\nTarget phase: {target_phase}\nRun: consilium --do --plan-file {plan_file} --phase {target_phase}"
```

**Note:** Verify the exact attribute path to the session ID on `ThinkSoul`. It may be `think_soul._session.id` or `think_soul.session.id`.

---

### 6. `src/consilium/app.py` — Link Do session to Think on startup

**Change:** After creating the Do `Session`, read `dispatch.json`. If it has a `think_session_id`, write it into the Do session's state.

```python
# In KimiCLI.create(), after Session.create() returns (around line 647 or 709)
# and before DoSession is created:

# Read dispatch if present
dispatch_think_id: str | None = None
if do_mode and plan_file:
    from consilium.plan.dispatch import read_dispatch  # or equivalent
    try:
        dispatch = read_dispatch()
        if dispatch and dispatch.think_session_id:
            dispatch_think_id = dispatch.think_session_id
    except Exception:
        pass

# ... existing DoSession creation ...

# After DoSession starts, link sessions
if do_mode and dispatch_think_id:
    session.state.paired_session_id = dispatch_think_id
    from consilium.session_state import save_session_state
    save_session_state(session.state, session_dir)
```

**Note:** `read_dispatch()` may not exist. If `plan/dispatch.py` only has `write_dispatch()`, add a simple `read_dispatch()`:

```python
# In plan/dispatch.py
DISPATCH_PATH = Path.home() / ".consilium" / "dispatch.json"

def read_dispatch() -> Dispatch | None:
    if not DISPATCH_PATH.exists():
        return None
    try:
        return Dispatch.model_validate_json(DISPATCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
```

---

## Tests

Add tests to verify:
- `SessionState.model_validate()` tolerates missing `paired_session_id` (backward compat)
- `SessionState.model_dump()` includes `paired_session_id` when set
- `write_dispatch()` stores `think_session_id`
- `read_dispatch()` round-trips correctly
- Do session creation sets `state.paired_session_id` from dispatch

---

## Acceptance Criteria

- [x] `SessionState` has `paired_session_id` field
- [x] Old `state.json` files load without errors (backward compat)
- [x] `Dispatch` has `think_session_id` field
- [x] `/push-to-do` writes Think session ID into dispatch
- [x] Do session startup reads dispatch and sets `state.paired_session_id`
- [x] `Session.list()` surfaces `paired_session_id` (already loads `state.json`)
- [x] `uv run pytest` passes

---

## Implementation Order

1. Add `paired_session_id` to `SessionState` (5 min)
2. Add `think_session_id` to `Dispatch` and `write_dispatch()` (10 min)
3. Pass Think session ID from `slash_push_to_do()` (10 min)
4. Read dispatch and link Do session in `app.py` (20 min)
5. Add `read_dispatch()` if missing (10 min)
6. Tests (30 min)

**Total: ~1.5 hours**
