"""Tests for per-subagent temperature and budget override resolution."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from consilium.config import (
    Config,
    GenerationConfig,
    LLMModel,
    LLMProvider,
    ResolvedSubagentConfig,
    SubagentBudgetConfig,
    SubagentOverrideConfig,
    SubagentsConfig,
)
from consilium.subagent_config import build_subagent_config, resolve_subagent_config


def _make_config(
    *,
    temperature: float | None = 0.7,
    max_tokens: int = 80_000,
    max_tools: int = 100,
    timeout: int = 900,
    overrides: dict[str, SubagentOverrideConfig] | None = None,
) -> Config:
    generation = GenerationConfig(temperature=temperature) if temperature is not None else None
    provider = LLMProvider(
        type="kimi",
        api_key=SecretStr("test-key"),
        base_url="https://test.example.com",
    )
    model = LLMModel(
        provider="test",
        model="test-model",
        max_context_size=128_000,
        generation=generation,
    )
    return Config(
        is_from_default_location=False,
        default_model="test-model",
        models={"test-model": model},
        providers={"test": provider},
        subagents=SubagentsConfig(
            timeout_seconds=timeout,
            budget=SubagentBudgetConfig(
                max_tokens_per_task=max_tokens,
                max_tool_calls_per_task=max_tools,
            ),
            overrides=overrides or {},
        ),
    )


def test_resolve_uses_global_defaults() -> None:
    config = _make_config()
    resolved = resolve_subagent_config("explore", config)
    assert resolved == ResolvedSubagentConfig(
        temperature=0.7,
        max_tokens_per_task=80_000,
        max_tool_calls_per_task=100,
        timeout_seconds=900,
    )


def test_resolve_uses_file_overrides() -> None:
    config = _make_config(
        overrides={
            "explore": SubagentOverrideConfig(
                temperature=0.5,
                max_tokens_per_task=10_000,
                max_tool_calls_per_task=50,
                timeout_seconds=600,
            ),
        },
    )
    resolved = resolve_subagent_config("explore", config)
    assert resolved.temperature == pytest.approx(0.5)
    assert resolved.max_tokens_per_task == 10_000
    assert resolved.max_tool_calls_per_task == 50
    assert resolved.timeout_seconds == 600


def test_unconfigured_type_falls_back_to_global() -> None:
    config = _make_config(
        overrides={
            "explore": SubagentOverrideConfig(temperature=0.5),
        },
    )
    resolved = resolve_subagent_config("coder", config)
    assert resolved.temperature == pytest.approx(0.7)


def test_cli_overrides_take_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSILIUM_SUBAGENT_CODER_TEMPERATURE", "0.2")
    config = _make_config(
        overrides={"coder": SubagentOverrideConfig(temperature=0.5)},
    )
    cli = SubagentOverrideConfig(temperature=0.1)
    resolved = resolve_subagent_config("coder", config, cli_overrides=cli)
    assert resolved.temperature == pytest.approx(0.1)


def test_env_overrides_take_precedence_over_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSILIUM_SUBAGENT_CODER_TEMPERATURE", "0.2")
    config = _make_config(
        overrides={"coder": SubagentOverrideConfig(temperature=0.5)},
    )
    resolved = resolve_subagent_config("coder", config)
    assert resolved.temperature == pytest.approx(0.2)


def test_env_overrides_ignored_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSILIUM_SUBAGENT_CODER_TEMPERATURE", "not-a-number")
    config = _make_config(
        overrides={"coder": SubagentOverrideConfig(temperature=0.5)},
    )
    resolved = resolve_subagent_config("coder", config)
    assert resolved.temperature == pytest.approx(0.5)


def test_temperature_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSILIUM_SUBAGENT_CODER_TEMPERATURE", "3.0")
    config = _make_config()
    resolved = resolve_subagent_config("coder", config)
    assert resolved.temperature == pytest.approx(2.0)


def test_default_temperature_uses_model_generation() -> None:
    config = _make_config(temperature=0.55)
    resolved = resolve_subagent_config("explore", config, default_temperature=0.55)
    assert resolved.temperature == pytest.approx(0.55)


def test_build_subagent_config_clones_and_isolates() -> None:
    config = _make_config(
        temperature=0.7,
        overrides={
            "explore": SubagentOverrideConfig(
                temperature=0.3,
                max_tokens_per_task=4_096,
                max_tool_calls_per_task=30,
                timeout_seconds=600,
            ),
        },
    )
    resolved = resolve_subagent_config("explore", config)
    subagent_config = build_subagent_config(config, "explore", "test-model", resolved)

    # Global config unchanged.
    assert config.models["test-model"].generation is None or config.models["test-model"].generation.temperature == pytest.approx(0.7)
    assert config.subagents.budget.max_tokens_per_task == 80_000
    assert config.subagents.timeout_seconds == 900

    # Subagent config updated.
    assert subagent_config.models["test-model"].generation is not None
    assert subagent_config.models["test-model"].generation.temperature == pytest.approx(0.3)
    assert subagent_config.subagents.budget.max_tokens_per_task == 4_096
    assert subagent_config.subagents.budget.max_tool_calls_per_task == 30
    assert subagent_config.subagents.timeout_seconds == 600


def test_build_subagent_config_creates_generation_when_missing() -> None:
    config = _make_config(temperature=None)
    resolved = resolve_subagent_config("explore", config, default_temperature=0.7)
    subagent_config = build_subagent_config(config, "explore", "test-model", resolved)
    assert subagent_config.models["test-model"].generation is not None
    assert subagent_config.models["test-model"].generation.temperature == pytest.approx(0.7)


def test_invalid_override_key_rejected() -> None:
    with pytest.raises(ValueError):
        SubagentsConfig(
            overrides={"Bad-Key": SubagentOverrideConfig(temperature=0.5)},
        )


def test_legacy_config_without_overrides_still_loads() -> None:
    # Simulates an old config dict that predates the overrides field.
    data = {
        "default_model": "test-model",
        "models": {
            "test-model": {
                "provider": "test",
                "model": "test-model",
                "max_context_size": 128_000,
            },
        },
        "providers": {
            "test": {
                "type": "kimi",
                "api_key": "test-key",
                "base_url": "https://test.example.com",
            },
        },
        "subagents": {
            "timeout_seconds": 300,
            "budget": {
                "max_tokens_per_task": 80_000,
                "max_tool_calls_per_task": 100,
            },
        },
    }
    config = Config.model_validate(data)
    resolved = resolve_subagent_config("coder", config)
    assert resolved.timeout_seconds == 300
    assert resolved.max_tokens_per_task == 80_000
