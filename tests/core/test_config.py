from __future__ import annotations

import pytest
from inline_snapshot import snapshot

from consilium.config import (
    Config,
    LLMModel,
    LLMProvider,
    get_default_config,
    load_config,
    load_config_from_string,
    save_config,
)
from consilium.exception import ConfigError


def test_default_config():
    config = get_default_config()
    assert config == snapshot(Config())


def test_default_config_dump():
    config = get_default_config()
    assert config.model_dump() == snapshot(
        {
            "default_model": "",
            "default_thinking": False,
            "default_yolo": False,
            "default_plan_mode": False,
            "default_editor": "",
            "theme": "dark",
            "show_thinking_stream": True,
            "models": {},
            "providers": {},
            "loop_control": {
                "max_steps_per_turn": 1000,
                "max_retries_per_step": 3,
                "max_ralph_iterations": 0,
                "reserved_context_size": 100000,
                "compaction_trigger_ratio": 0.85,
                "max_preserved_messages": 10,
            },
            "background": {
                "max_running_tasks": 8,
                "read_max_bytes": 30000,
                "notification_tail_lines": 20,
                "notification_tail_chars": 3000,
                "wait_poll_interval_ms": 500,
                "worker_heartbeat_interval_ms": 5000,
                "worker_stale_after_ms": 15000,
                "kill_grace_period_ms": 2000,
                "keep_alive_on_exit": False,
                "agent_task_timeout_s": 900,
                "print_wait_ceiling_s": 3600,
            },
            "notifications": {
                "claim_stale_after_ms": 15000,
            },
            "services": {"web_search": None, "web_fetch": None},
            "mcp": {"client": {"tool_call_timeout_ms": 60000}},
            "hooks": [],
            "merge_all_available_skills": True,
            "extra_skill_dirs": [],
            "system_prompt_overrides": {},
            "budget_tokens": None,
            "think": {
                "default_temperature": 0.6,
                "max_context_tokens": 200000,
                "enable_checkpoints": True,
                "python": {
                    "restriction_level": "restricted",
                    "allow_network": False,
                    "timeout_seconds": 30,
                    "max_memory_mb": 512,
                    "auto_approve": False,
                },
                "compaction_enabled": True,
                "compaction_threshold": 0.85,
                "compaction_preserve_messages": 6,
            },
            "do": {
                "default_temperature": 0.3,
                "auto_git_snapshot": True,
                "max_iterations": 50,
                "enable_change_journal": True,
                "journal_include_diffs": True,
                "journal_retention_days": 30,
                "plan_review": {
                    "enabled": True,
                    "timeout_seconds": 300,
                    "model": None,
                    "system_prompt_path": None,
                },
                "enable_reverse_bridge": True,
            },
            "subagents": {
                "enabled": True,
                "timeout_seconds": 900,
                "default_type": "explore",
                "budget": {
                    "max_tokens_per_task": 80000,
                    "max_tool_calls_per_task": 100,
                    "warn_tokens_ratio": 0.8,
                    "warn_tool_calls_ratio": 0.8,
                }, "overrides": {}},
            "telemetry": True,
            "skip_afk_prompt_injection": False,
        }
    )


def test_load_config_text_toml():
    config = load_config_from_string('default_model = ""\n')
    assert config == get_default_config()


def test_load_config_text_json():
    config = load_config_from_string('{"default_model": ""}')
    assert config == get_default_config()


def test_load_config_sets_source_file(tmp_path):
    config_file = tmp_path / "custom.toml"

    config = load_config(config_file)

    assert config.source_file == config_file.resolve()
    assert not config.is_from_default_location


def test_load_config_text_has_no_source_file():
    config = load_config_from_string('{"default_model": ""}')

    assert config.source_file is None


def test_load_config_text_invalid():
    with pytest.raises(ConfigError, match="Invalid configuration text"):
        load_config_from_string("not valid {")


def test_load_config_invalid_ralph_iterations():
    with pytest.raises(ConfigError, match="max_ralph_iterations"):
        load_config_from_string('{"loop_control": {"max_ralph_iterations": -2}}')


def test_load_config_reserved_context_size():
    config = load_config_from_string('{"loop_control": {"reserved_context_size": 30000}}')
    assert config.loop_control.reserved_context_size == 30000


def test_load_config_max_steps_per_turn():
    config = load_config_from_string("[loop_control]\nmax_steps_per_turn = 42\n")
    assert config.loop_control.max_steps_per_turn == 42


def test_load_config_legacy_skip_yolo_prompt_injection_ignored():
    config = load_config_from_string("skip_yolo_prompt_injection = true\n")
    assert config.skip_afk_prompt_injection is False


def test_load_config_max_steps_per_run():
    config = load_config_from_string('{"loop_control": {"max_steps_per_run": 7}}')
    assert config.loop_control.max_steps_per_turn == 7


def test_load_config_reserved_context_size_too_low():
    with pytest.raises(ConfigError, match="reserved_context_size"):
        load_config_from_string('{"loop_control": {"reserved_context_size": 500}}')


def test_load_config_compaction_trigger_ratio():
    config = load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 0.8}}')
    assert config.loop_control.compaction_trigger_ratio == 0.8


def test_load_config_compaction_trigger_ratio_default():
    config = load_config_from_string("{}")
    assert config.loop_control.compaction_trigger_ratio == 0.85


def test_load_config_compaction_trigger_ratio_too_low():
    with pytest.raises(ConfigError, match="compaction_trigger_ratio"):
        load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 0.3}}')


def test_load_config_compaction_trigger_ratio_too_high():
    with pytest.raises(ConfigError, match="compaction_trigger_ratio"):
        load_config_from_string('{"loop_control": {"compaction_trigger_ratio": 1.0}}')


def test_save_config_refuses_missing_provider(tmp_path):
    """save_config must refuse to persist a model whose provider is absent.

    This is the exact corrupt state the user kept hitting: a
    [models."kimi-code/kimi-for-coding"] block referencing
    "managed:kimi-code" with no matching provider block. The Config model
    validator raises on load, but an in-memory Config that bypassed
    validation (e.g. a stale copy) would previously be written back to
    disk, re-corrupting the file for every subsequent CLI start.
    """
    config = get_default_config()
    config.models["kimi-code/kimi-for-coding"] = LLMModel(
        provider="managed:kimi-code",
        model="kimi-for-coding",
        max_context_size=10000,
    )
    # Provider block deliberately absent — the corrupt signature.
    config_file = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="Refusing to save config"):
        save_config(config, config_file)
    # No file must be written.
    assert not config_file.exists()


def test_save_config_allows_consistent_config(tmp_path):
    """save_config persists a config whose models all have providers."""
    config = get_default_config()
    config.providers["user-api"] = LLMProvider(
        type="openai_responses",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-test",
    )
    config.models["deepseek/deepseek-v4-flash"] = LLMModel(
        provider="user-api",
        model="deepseek-v4-flash",
        max_context_size=200000,
    )
    config_file = tmp_path / "config.toml"
    save_config(config, config_file)
    assert config_file.exists()
    # Round-trip: the saved file must validate cleanly.
    loaded = load_config(config_file)
    assert "deepseek/deepseek-v4-flash" in loaded.models

