from __future__ import annotations

import pytest
from pydantic import ValidationError

from kimi_cli.config import Config, load_config_from_string


def test_system_prompt_overrides_valid_paths(tmp_path):
    override_file = tmp_path / "custom.md"
    override_file.write_text("# custom", encoding="utf-8")

    config = Config(
        system_prompt_overrides={"identity": str(override_file)},
    )
    assert config.system_prompt_overrides["identity"] == str(override_file)


def test_system_prompt_overrides_missing_path():
    with pytest.raises(ValidationError, match="system_prompt_overrides\\['identity'\\] file not found"):
        Config(
            system_prompt_overrides={"identity": "/nonexistent/path/to/file.md"},
        )


def test_system_prompt_overrides_tilde_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    override_file = home / "custom.md"
    override_file.write_text("# custom", encoding="utf-8")

    config = Config(
        system_prompt_overrides={"identity": "~/custom.md"},
    )
    assert config.system_prompt_overrides["identity"] == "~/custom.md"


def test_system_prompt_overrides_missing_tilde_path(monkeypatch):
    monkeypatch.setenv("HOME", "/nonexistent/home")
    monkeypatch.setenv("USERPROFILE", "\\nonexistent\\home")

    with pytest.raises(ValidationError, match="system_prompt_overrides\\['identity'\\] file not found"):
        Config(
            system_prompt_overrides={"identity": "~/missing.md"},
        )
