"""Tests for declarable project subagents + the core vision subagent."""

from __future__ import annotations

from pathlib import Path

import pytest

from consilium.agentspec import (
    MAIN_AGENT_FILES,
    discover_project_subagent_files,
    load_agent_spec,
)
from consilium.think import _make_spawn_subagent_tool


# ── discovery ─────────────────────────────────────────────────────────


def test_discover_finds_subagent_yamls(tmp_path: Path):
    """Custom subagent YAMLs in an override dir are discovered by file stem."""
    (tmp_path / "vision.yaml").write_text(
        "version: 1\nagent:\n  name: vision\n", encoding="utf-8"
    )
    (tmp_path / "translator.yaml").write_text(
        "version: 1\nagent:\n  name: translator\n", encoding="utf-8"
    )
    result = discover_project_subagent_files(tmp_path)
    assert set(result) == {"vision", "translator"}
    assert result["vision"] == tmp_path / "vision.yaml"


def test_discover_excludes_main_agent_files(tmp_path: Path):
    """Main-agent files are never treated as subagents."""
    for name in MAIN_AGENT_FILES:
        (tmp_path / name).write_text("version: 1\nagent: {}\n", encoding="utf-8")
    (tmp_path / "custom.yaml").write_text("version: 1\nagent: {}\n", encoding="utf-8")
    # Also a non-yaml and a nested dir must be ignored.
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.yaml").write_text("version: 1\n", encoding="utf-8")

    result = discover_project_subagent_files(tmp_path)
    assert set(result) == {"custom"}


def test_discover_missing_dir_returns_empty(tmp_path: Path):
    assert discover_project_subagent_files(tmp_path / "nope") == {}
    assert discover_project_subagent_files(tmp_path / "not-a-file.txt") == {}


def test_discover_builtin_default_includes_vision():
    """The shipped builtin default dir contains vision.yaml and it resolves."""
    from consilium.agentspec import get_agents_dir

    default_dir = get_agents_dir() / "default"
    result = discover_project_subagent_files(default_dir)
    assert "vision" in result
    spec = load_agent_spec(result["vision"])
    assert spec.model == "qwen/qwen3.7-flash"


# ── vision spec resolution ────────────────────────────────────────────


def test_vision_spec_model_and_tools():
    """vision.yaml declares the vision model + read-only media tools."""
    from consilium.agentspec import get_agents_dir

    spec = load_agent_spec(get_agents_dir() / "default" / "vision.yaml")
    assert spec.model == "qwen/qwen3.7-flash"
    assert "consilium.tools.file:ReadMediaFile" in spec.allowed_tools
    # No mutation tools for a read-only vision analyzer.
    assert "consilium.tools.file:WriteFile" not in spec.allowed_tools
    assert "consilium.tools.shell:Shell" not in spec.allowed_tools
    assert spec.when_to_use


# ── think spawn tool enum ─────────────────────────────────────────────


class _FakeMarket:
    def __init__(self, names: list[str]) -> None:
        self.builtin_types = {name: object() for name in names}


class _FakeRuntime:
    def __init__(self, names: list[str]) -> None:
        self.labor_market = _FakeMarket(names)


def test_spawn_tool_enum_core_only_without_runtime():
    tool = _make_spawn_subagent_tool(None)
    enum = tool.parameters["properties"]["subagent_type"]["enum"]
    assert enum == ["explore", "plan_editor", "investigate"]


def test_spawn_tool_enum_includes_registered_custom_types():
    tool = _make_spawn_subagent_tool(_FakeRuntime(["explore", "plan_editor", "investigate", "vision"]))
    enum = tool.parameters["properties"]["subagent_type"]["enum"]
    assert "vision" in enum
    assert enum == ["explore", "plan_editor", "investigate", "vision"]


# ── vision gating (parent image capability) ───────────────────────────


class _FakeLLM:
    def __init__(self, capabilities: set[str]) -> None:
        self.capabilities = capabilities


class _FakeRuntimeWithLLM:
    def __init__(self, capabilities: set[str]) -> None:
        self.llm = _FakeLLM(capabilities)


def test_parent_has_image_capability_true():
    from consilium.soul.agent import _parent_has_image_capability

    runtime = _FakeRuntimeWithLLM({"image_in", "thinking"})
    assert _parent_has_image_capability(runtime) is True


def test_parent_has_image_capability_false_for_text_only():
    from consilium.soul.agent import _parent_has_image_capability

    runtime = _FakeRuntimeWithLLM({"thinking"})
    assert _parent_has_image_capability(runtime) is False
    # No llm at all (e.g. pre-init) -> not redundant -> register.
    runtime_no_llm = _FakeRuntimeWithLLM(set())
    runtime_no_llm.llm = None
    assert _parent_has_image_capability(runtime_no_llm) is False
