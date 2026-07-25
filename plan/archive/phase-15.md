# Phase 15: E2E Testing Infrastructure

## Summary

Build deterministic end-to-end tests for the full Think → Plan → Push → Do → Implement pipeline. Currently the test suite is entirely unit/integration tests. E2E tests verify that the complete workflow — across two CLI processes and the extension — actually works.

**Two strategies:**
1. **Mock LLM** — deterministic, fast, no network. Good for CI.
2. **Ollama** — lightweight local LLM (e.g., `qwen2.5:3b`). More realistic but requires local setup.

**Prerequisites:** All core features stable (Phases 1–13).

**Estimated effort:** 3–4 days.

---

## Sub-Phase 15.1: Mock LLM Provider

### Problem
Unit tests mock individual functions. E2E tests need to mock the LLM at the provider level so the entire Think/Do pipeline runs with deterministic responses.

### Solution
Create a `MockChatProvider` that implements the same interface as the real LLM provider.

### Files

#### NEW: `tests_e2e/fixtures/mock_llm.py`

```python
from typing import AsyncIterator
import json

class MockChatProvider:
    """Deterministic LLM for E2E tests."""

    def __init__(self, responses: list[str]):
        self._responses = iter(responses)
        self._calls: list[list[dict]] = []

    async def complete(self, messages: list[dict], **kwargs) -> str:
        self._calls.append(messages)
        return next(self._responses, "Mock response.")

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        response = await self.complete(messages, **kwargs)
        yield response

    def get_calls(self) -> list[list[dict]]:
        return self._calls
```

**Integration point:** The `kosong` package (or whatever abstraction layer the CLI uses) must accept a pluggable provider. Verify the injection point:

```python
# In test setup:
from consilium.soul.consilium_soul import ConsiliumSoul
from tests_e2e.fixtures.mock_llm import MockChatProvider

mock_llm = MockChatProvider([
    "Phase 1: Create src/main.py\nPhase 2: Add tests",
    "Plan exported to plan/index.md",
])

soul = ConsiliumSoul(..., llm_provider=mock_llm)
```

If the provider is not injectable, add a test-only factory method.

### Acceptance Criteria
- [ ] `MockChatProvider` implements the full provider interface
- [ ] Responses are consumed in order
- [ ] All LLM calls are recorded for assertion
- [ ] Works with both `complete()` and `stream()` paths

---

## Sub-Phase 15.2: Full Pipeline E2E Test

### Test Scenario

```
1. Start Think session in temp directory
2. User: "Plan a minimal todo app"
3. Think generates 2-phase plan
4. User: /push-to-do
5. Think writes plan/index.md + dispatch.json
6. Start Do session with --plan-file plan/index.md --phase phase-1
7. Do loads plan, implements phase-1
8. Assertions:
   - plan/index.md exists
   - src/main.py exists
   - Do journal has entry for src/main.py
   - plan phase-1 status == "implemented"
   - Think inbox has completion report (if Phase 13 done)
```

### Files

#### NEW: `tests_e2e/test_full_pipeline.py`

```python
import pytest
from pathlib import Path
from tests_e2e.fixtures.mock_llm import MockChatProvider
from tests_e2e.fixtures.git_repo import git_repo  # pytest fixture

@pytest.mark.asyncio
async def test_think_plan_push_do_implement(git_repo: Path):
    # 1. Mock Think LLM
    think_llm = MockChatProvider([
        "Phase 1: Create src/main.py with a Todo class\n"
        "Phase 2: Add pytest tests in tests/test_todo.py",
        "Plan created at plan/index.md",
    ])

    # 2. Start Think
    think = create_think_soul(work_dir=git_repo, llm=think_llm)
    await think.run("Plan a minimal todo app")

    # 3. Push to Do
    await think.slash_push_to_do("phase-1")

    # 4. Verify plan written
    plan_file = git_repo / "plan" / "index.md"
    assert plan_file.exists()

    # 5. Mock Do LLM
    do_llm = MockChatProvider([
        "I'll create src/main.py with a Todo class.",
        "File created. Here's the implementation...",
    ])

    # 6. Start Do
    do = create_do_session(
        work_dir=git_repo,
        plan_file=plan_file,
        phase="phase-1",
        llm=do_llm,
    )
    await do.start()

    # 7. Assertions
    assert (git_repo / "src" / "main.py").exists()
    assert do.journal.has_entry(type="diff", path="src/main.py")
    assert plan_file.read_text().contains("status: implemented")
```

### Fixtures Needed

#### `tests_e2e/fixtures/git_repo.py`

```python
import pytest
from pathlib import Path
import subprocess

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo
```

#### `tests_e2e/fixtures/soul_factory.py`

Factory functions to create Think/Do souls with injected mock LLM and temp config paths.

### Acceptance Criteria
- [ ] Test creates a real git repo in tmp_path
- [ ] Think generates plan with mock LLM
- [ ] `/push-to-do` writes dispatch.json
- [ ] Do implements phase with mock LLM
- [ ] File system assertions pass
- [ ] Plan status assertions pass
- [ ] Test completes in < 30 seconds

---

## Sub-Phase 15.3: Ollama Integration (Optional)

### Problem
Mock LLM tests verify plumbing but not LLM reasoning quality. Ollama provides a lightweight local LLM for more realistic tests.

### Setup

```bash
# One-time setup
ollama pull qwen2.5:3b
```

### Provider

#### NEW: `tests_e2e/fixtures/ollama_llm.py`

```python
import aiohttp

class OllamaChatProvider:
    """Local Ollama provider for E2E tests."""

    def __init__(self, model: str = "qwen2.5:3b", url: str = "http://localhost:11434"):
        self.model = model
        self.url = url

    async def complete(self, messages: list[dict], **kwargs) -> str:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{self.url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
            )
            data = await resp.json()
            return data["message"]["content"]
```

### Acceptance Criteria
- [ ] `OllamaChatProvider` works as drop-in replacement for `MockChatProvider`
- [ ] Skips gracefully if Ollama is not running (`pytest.skip()`)
- [ ] Same test suite runs with either provider (parametrized fixture)

---

## Sub-Phase 15.4: Extension E2E Test (Optional/Deferred)

### Problem
The extension webview is hard to test headlessly. But we can test the bridge protocol layer.

### Approach
Use VS Code: extension testing API or mock the webview message bus.

**Decision:** Defer to future. Extension E2E is lower priority than CLI E2E.

---

## Acceptance Criteria (Phase 15 Overall)

- [ ] `MockChatProvider` exists and is injectable
- [ ] Full pipeline E2E test passes with mock LLM
- [ ] Test uses temp directory, real git, real tools (WriteFile, Shell)
- [ ] Only LLM is mocked; everything else is real
- [ ] Test completes in < 30 seconds
- [ ] `pytest tests_e2e/` runs and passes
- [ ] Ollama provider exists (optional, skip if not available)
- [ ] CI runs E2E tests (or marks them as slow/optional)

---

## Implementation Order

1. **15.1** — Mock LLM provider + injection point (1 day)
2. **15.2** — Full pipeline test + fixtures (2 days)
3. **15.3** — Ollama provider (optional, 1 day)
4. **15.4** — Extension E2E (deferred)
5. **CI** — Add `tests_e2e/` to test matrix (optional/scheduled)

**Total: ~3–4 days (2–3 days without Ollama)**

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM provider not injectable | 🔴 High | Verify `kosong` abstraction first; may need small refactor |
| Do mode uses real network APIs | 🟡 Medium | Ensure test config disables external calls; mock at HTTP layer if needed |
| Test is flaky due to async timing | 🟡 Medium | Use `asyncio.wait_for`; avoid fixed sleeps |
| Ollama not available in CI | 🟢 Low | Mark Ollama tests as optional; run only MockChatProvider in CI |
