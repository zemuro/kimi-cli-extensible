"""Tests for per-subagent model override resolution (visual + default model)."""

from __future__ import annotations

import pytest

from consilium.config import (
    Config,
    LLMModel,
    LLMProvider,
    ResolvedSubagentConfig,
    SubagentOverrideConfig,
    SubagentsConfig,
)
from consilium.subagent_config import resolve_subagent_config


def _make_config(
    *,
    default_model: str | None = None,
    vision_model: str | None = None,
    coder_model: str | None = None,
) -> Config:
    models = {
        "deepseek/deepseek-v4-flash": LLMModel(
            provider="user-api",
            model="deepseek/deepseek-v4-flash",
            max_context_size=1_000_000,
            capabilities={"thinking"},
            display_name="DeepSeek V4 Flash",
        ),
        "qwen/qwen3.7-flash": LLMModel(
            provider="user-api",
            model="qwen/qwen3.7-flash",
            max_context_size=1_000_000,
            capabilities={"thinking", "image_in"},
            display_name="Qwen3.7 Flash",
        ),
    }
    overrides: dict[str, SubagentOverrideConfig] = {}
    if vision_model:
        overrides["vision"] = SubagentOverrideConfig(model=vision_model)
    if coder_model:
        overrides["coder"] = SubagentOverrideConfig(model=coder_model)
    return Config(
        default_model="deepseek/deepseek-v4-flash",
        models=models,
        providers={"user-api": LLMProvider(type="openai_responses", base_url="https://openrouter.ai/api/v1", api_key="x")},
        subagents=SubagentsConfig(
            default_model=default_model,
            overrides=overrides,
        ),
    )


class TestResolveSubagentModel:
    def test_per_subagent_override_wins(self) -> None:
        cfg = _make_config(default_model="deepseek/deepseek-v4-flash", vision_model="qwen/qwen3.7-flash")
        resolved = resolve_subagent_config("vision", cfg)
        assert resolved.model == "qwen/qwen3.7-flash"

    def test_no_override_yields_none(self) -> None:
        cfg = _make_config(default_model="deepseek/deepseek-v4-flash")
        resolved = resolve_subagent_config("coder", cfg)
        assert resolved.model is None

    def test_cli_override_beats_file(self) -> None:
        cfg = _make_config(vision_model="qwen/qwen3.7-flash")
        cli = SubagentOverrideConfig(model="deepseek/deepseek-v4-flash")
        resolved = resolve_subagent_config("vision", cfg, cli_overrides=cli)
        assert resolved.model == "deepseek/deepseek-v4-flash"

    def test_env_override_beats_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _make_config(vision_model="qwen/qwen3.7-flash")
        monkeypatch.setenv("CONSILIUM_SUBAGENT_VISION_MODEL", "deepseek/deepseek-v4-flash")
        resolved = resolve_subagent_config("vision", cfg)
        assert resolved.model == "deepseek/deepseek-v4-flash"

    def test_empty_env_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _make_config(vision_model="qwen/qwen3.7-flash")
        monkeypatch.setenv("CONSILIUM_SUBAGENT_VISION_MODEL", "   ")
        resolved = resolve_subagent_config("vision", cfg)
        assert resolved.model == "qwen/qwen3.7-flash"

    def test_default_model_falls_back_in_builder(self) -> None:
        """subagents.default_model is applied at the builder level, not in resolve."""
        cfg = _make_config(default_model="deepseek/deepseek-v4-flash")
        resolved = resolve_subagent_config("plan_reviewer", cfg)
        assert resolved.model is None
        # Builder applies default_model when resolved.model is None.
        effective = resolved.model or cfg.subagents.default_model
        assert effective == "deepseek/deepseek-v4-flash"


class TestResolvedConfigRoundTrip:
    def test_resolved_preserves_existing_fields(self) -> None:
        cfg = _make_config(vision_model="qwen/qwen3.7-flash")
        resolved = resolve_subagent_config("vision", cfg)
        assert isinstance(resolved, ResolvedSubagentConfig)
        assert resolved.temperature == 0.7
        assert resolved.max_tokens_per_task > 0
        assert resolved.max_tool_calls_per_task > 0
        assert resolved.timeout_seconds >= 10
        assert resolved.model == "qwen/qwen3.7-flash"
