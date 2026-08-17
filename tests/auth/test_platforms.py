"""Tests for managed-platform model listing and syncing."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from pydantic import SecretStr

from consilium.auth.platforms import (
    ModelInfo,
    _apply_models,
    _list_models,
    refresh_managed_models,
)
from consilium.config import Config, LLMModel, LLMProvider, OAuthRef, Services
from consilium.llm import model_display_name


def _make_config_with_model(
    *,
    display_name: str | None = None,
    api_key: str = "",
) -> Config:
    provider = LLMProvider(
        type="kimi",
        base_url="https://api.test/v1",
        api_key=SecretStr(api_key),
        oauth=OAuthRef(storage="file", key="oauth/kimi-code"),
    )
    model = LLMModel(
        provider="managed:kimi-code",
        model="kimi-for-coding",
        max_context_size=1_000_000,
        display_name=display_name,
    )
    return Config(
        default_model="kimi-code/kimi-for-coding",
        providers={"managed:kimi-code": provider},
        models={"kimi-code/kimi-for-coding": model},
        services=Services(),
    )


# ── ModelInfo / _list_models: display_name parsing ─────────────────


@pytest.mark.asyncio
async def test_list_models_parses_display_name():
    """_list_models should capture display_name from the API response."""
    api_payload = {
        "data": [
            {
                "id": "kimi-for-coding",
                "context_length": 262_144,
                "supports_reasoning": True,
                "supports_image_in": True,
                "supports_video_in": True,
                "display_name": "k2.6-code-preview",
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value=api_payload)

    class FakeCM:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, *args):
            pass

    session = MagicMock()
    session.get = MagicMock(return_value=FakeCM())

    models = await _list_models(session, base_url="https://api.test/v1", api_key="k")
    assert len(models) == 1
    assert models[0].display_name == "k2.6-code-preview"


@pytest.mark.asyncio
async def test_list_models_display_name_absent_is_none():
    """Missing display_name should become None on the ModelInfo."""
    api_payload = {
        "data": [
            {
                "id": "kimi-for-coding",
                "context_length": 262_144,
                "supports_reasoning": False,
                "supports_image_in": False,
                "supports_video_in": False,
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value=api_payload)

    class FakeCM:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, *args):
            pass

    session = MagicMock()
    session.get = MagicMock(return_value=FakeCM())

    models = await _list_models(session, base_url="https://api.test/v1", api_key="k")
    assert models[0].display_name is None


# ── _apply_models: display_name sync ──────────────────────────────


def test_apply_models_writes_display_name_on_insert():
    """New model entries should carry display_name from the API."""
    config = Config(services=Services())
    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=262_144,
            supports_reasoning=True,
            supports_image_in=True,
            supports_video_in=True,
            display_name="k2.6-code-preview",
        )
    ]

    changed = _apply_models(config, "managed:kimi-code", "kimi-code", models)

    assert changed is True
    entry = config.models["kimi-code/kimi-for-coding"]
    assert entry.display_name == "k2.6-code-preview"


def test_apply_models_updates_display_name_on_change():
    """Existing model entries should have display_name updated to the latest API value."""
    config = _make_config_with_model(display_name="old-name")
    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=100_000,
            supports_reasoning=False,
            supports_image_in=False,
            supports_video_in=False,
            display_name="k2.6-code-preview",
        )
    ]

    changed = _apply_models(config, "managed:kimi-code", "kimi-code", models)

    assert changed is True
    assert config.models["kimi-code/kimi-for-coding"].display_name == "k2.6-code-preview"


def test_apply_models_clears_display_name_when_api_drops_it():
    """If API stops returning display_name, local entry should be cleared."""
    config = _make_config_with_model(display_name="old-name")
    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=100_000,
            supports_reasoning=False,
            supports_image_in=False,
            supports_video_in=False,
            display_name=None,
        )
    ]

    changed = _apply_models(config, "managed:kimi-code", "kimi-code", models)

    assert changed is True
    assert config.models["kimi-code/kimi-for-coding"].display_name is None


# ── model_display_name: prefers LLMModel.display_name ────────────


def test_model_display_name_prefers_config_display_name():
    """When LLMModel has a display_name, use it instead of hard-coded mapping."""
    model = LLMModel(
        provider="managed:kimi-code",
        model="kimi-for-coding",
        max_context_size=1_000_000,
        display_name="k2.6-code-preview",
    )
    assert model_display_name("kimi-for-coding", model) == "k2.6-code-preview"


def test_model_display_name_falls_back_to_hardcoded_when_missing():
    """Without display_name, fall back to the legacy hard-coded mapping."""
    model = LLMModel(
        provider="managed:kimi-code",
        model="kimi-for-coding",
        max_context_size=1_000_000,
    )
    assert model_display_name("kimi-for-coding", model) == "kimi-for-coding"


def test_model_display_name_no_model_uses_raw_name():
    """When no LLMModel is provided, use the raw model name."""
    assert model_display_name("kimi-k2-turbo-preview") == "kimi-k2-turbo-preview"


def test_model_display_name_empty_returns_empty():
    assert model_display_name(None) == ""
    assert model_display_name("") == ""


@pytest.mark.asyncio
async def test_refresh_managed_models_retries_after_oauth_401():
    config = _make_config_with_model()
    config.is_from_default_location = True

    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=100_000,
            supports_reasoning=False,
            supports_image_in=False,
            supports_video_in=False,
            display_name=None,
        )
    ]
    unauthorized = aiohttp.ClientResponseError(
        request_info=MagicMock(real_url="https://api.test/v1/models"),
        history=(),
        status=401,
        message="Unauthorized",
    )

    with (
        patch(
            "consilium.auth.platforms.list_models",
            AsyncMock(side_effect=[unauthorized, models]),
        ) as list_models_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.ensure_fresh",
            new=AsyncMock(),
        ) as ensure_fresh_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.resolve_api_key",
            side_effect=["stale-access-token", "fresh-access-token"],
        ),
    ):
        changed = await refresh_managed_models(config)

    assert changed is False
    assert list_models_mock.await_count == 2
    assert len(ensure_fresh_mock.await_args_list) == 2
    assert ensure_fresh_mock.await_args_list[0].kwargs == {}
    assert ensure_fresh_mock.await_args_list[1].kwargs == {"force": True}


@pytest.mark.asyncio
async def test_refresh_managed_models_401_falls_back_to_static_api_key_when_refresh_fails():
    config = _make_config_with_model(api_key="static-api-key")
    config.is_from_default_location = True

    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=100_000,
            supports_reasoning=False,
            supports_image_in=False,
            supports_video_in=False,
            display_name=None,
        )
    ]
    unauthorized = aiohttp.ClientResponseError(
        request_info=MagicMock(real_url="https://api.test/v1/models"),
        history=(),
        status=401,
        message="Unauthorized",
    )

    with (
        patch(
            "consilium.auth.platforms.list_models",
            AsyncMock(side_effect=[unauthorized, models]),
        ) as list_models_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.ensure_fresh",
            new=AsyncMock(side_effect=[None, RuntimeError("refresh failed")]),
        ) as ensure_fresh_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.resolve_api_key",
            side_effect=["oauth-access-token", "oauth-access-token"],
        ),
    ):
        changed = await refresh_managed_models(config)

    assert changed is False
    assert list_models_mock.await_count == 2
    assert list_models_mock.await_args_list[0].args[1] == "oauth-access-token"
    assert list_models_mock.await_args_list[1].args[1] == "static-api-key"
    assert len(ensure_fresh_mock.await_args_list) == 2
    assert ensure_fresh_mock.await_args_list[0].kwargs == {}
    assert ensure_fresh_mock.await_args_list[1].kwargs == {"force": True}


@pytest.mark.asyncio
async def test_refresh_managed_models_401_tries_static_api_key_after_refreshed_oauth_still_fails():
    config = _make_config_with_model(api_key="static-api-key")
    config.is_from_default_location = True

    models = [
        ModelInfo(
            id="kimi-for-coding",
            context_length=100_000,
            supports_reasoning=False,
            supports_image_in=False,
            supports_video_in=False,
            display_name=None,
        )
    ]
    unauthorized = aiohttp.ClientResponseError(
        request_info=MagicMock(real_url="https://api.test/v1/models"),
        history=(),
        status=401,
        message="Unauthorized",
    )

    with (
        patch(
            "consilium.auth.platforms.list_models",
            AsyncMock(side_effect=[unauthorized, unauthorized, models]),
        ) as list_models_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.ensure_fresh",
            new=AsyncMock(side_effect=[None, None]),
        ) as ensure_fresh_mock,
        patch(
            "consilium.auth.oauth.OAuthManager.resolve_api_key",
            side_effect=["stale-oauth-token", "fresh-oauth-token"],
        ),
    ):
        changed = await refresh_managed_models(config)

    assert changed is False
    assert list_models_mock.await_count == 3
    assert list_models_mock.await_args_list[0].args[1] == "stale-oauth-token"
    assert list_models_mock.await_args_list[1].args[1] == "fresh-oauth-token"
    assert list_models_mock.await_args_list[2].args[1] == "static-api-key"
    assert len(ensure_fresh_mock.await_args_list) == 2
    assert ensure_fresh_mock.await_args_list[0].kwargs == {}
    assert ensure_fresh_mock.await_args_list[1].kwargs == {"force": True}


# ── user-api (OpenRouter) metadata refresh ───────────────────────────


def _make_user_api_config(*, is_default: bool = True) -> Config:
    provider = LLMProvider(
        type="openai_responses",
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("sk-or-test"),
    )
    model = LLMModel(
        provider="user-api",
        model="deepseek/deepseek-v4-flash",
        # Bogus values that the extension used to hardcode:
        max_context_size=200_000,
        capabilities={"image_in", "video_in", "thinking"},
        display_name="deepseek/deepseek-v4-flash",
    )
    config = Config(
        default_model="deepseek/deepseek-v4-flash",
        providers={"user-api": provider},
        models={"deepseek/deepseek-v4-flash": model},
        services=Services(),
    )
    config.is_from_default_location = is_default
    return config


_OPENROUTER_PAYLOAD = {
    "data": [
        {
            "id": "deepseek/deepseek-v4-flash",
            "name": "DeepSeek V4 Flash",
            "context_length": 1_048_576,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["reasoning", "tools"],
        },
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek Chat",
            "context_length": 163_840,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["tools"],
        },
    ]
}


@pytest.mark.asyncio
async def test__list_user_api_models_maps_openrouter_fields():
    """OpenRouter /models response maps to ModelInfo: context, thinking via
    supported_parameters, modalities via architecture.input_modalities."""
    from consilium.auth.platforms import _list_user_api_models

    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value=_OPENROUTER_PAYLOAD)

    class FakeCM:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, *args):
            pass

    session = MagicMock()
    session.get = MagicMock(return_value=FakeCM())

    info = await _list_user_api_models(session, base_url="https://openrouter.ai/api/v1", api_key="k")

    flash = info["deepseek/deepseek-v4-flash"]
    assert flash.context_length == 1_048_576
    assert flash.supports_reasoning is True
    assert flash.supports_image_in is False
    assert flash.supports_video_in is False
    assert "thinking" in flash.capabilities
    assert "image_in" not in flash.capabilities
    assert "video_in" not in flash.capabilities

    chat = info["deepseek/deepseek-chat"]
    assert chat.context_length == 163_840
    assert chat.supports_reasoning is False
    assert chat.capabilities == set()


@pytest.mark.asyncio
async def test_refresh_user_api_models_updates_in_place():
    """refresh_user_api_models overwrites bogus hardcoded values with the real
    API metadata without creating/deleting unrelated models."""
    from consilium.auth.platforms import refresh_user_api_models

    config = _make_user_api_config()
    # The save path re-reads the on-disk config; isolate from the real user
    # config by patching both load_config and save_config.
    fresh = _make_user_api_config()
    saved: list[Config] = []

    async def fake_fetch(provider_key, base_url, api_key) -> dict:
        return {
            "deepseek/deepseek-v4-flash": ModelInfo(
                id="deepseek/deepseek-v4-flash",
                context_length=1_048_576,
                supports_reasoning=True,
                supports_image_in=False,
                supports_video_in=False,
                display_name="DeepSeek V4 Flash",
            ),
        }

    with patch(
        "consilium.auth.platforms.refresh_user_api_models_for_provider", new=fake_fetch
    ), patch("consilium.auth.platforms.load_config", return_value=fresh) as load_mock, patch(
        "consilium.auth.platforms.save_config",
        side_effect=lambda cfg: saved.append(cfg),
    ) as save_mock:
        changed = await refresh_user_api_models(config)

    assert changed is True
    model = config.models["deepseek/deepseek-v4-flash"]
    assert model.max_context_size == 1_048_576
    assert model.capabilities == {"thinking"}
    assert model.display_name == "DeepSeek V4 Flash"
    load_mock.assert_called_once()
    assert save_mock.call_count == 1
    saved_model = saved[0].models["deepseek/deepseek-v4-flash"]
    assert saved_model.max_context_size == 1_048_576
    assert saved_model.capabilities == {"thinking"}


@pytest.mark.asyncio
async def test_refresh_user_api_skips_non_user_providers():
    """Providers without a key are skipped and no save occurs."""
    from consilium.auth.platforms import refresh_user_api_models

    config = _make_config_with_model(api_key="")  # managed:kimi-code, no key
    config.is_from_default_location = True

    fetched: list[str] = []

    async def fake_fetch(provider_key, base_url, api_key) -> dict:
        fetched.append(provider_key)
        return {}

    with patch("consilium.auth.platforms.refresh_user_api_models_for_provider", new=fake_fetch):
        changed = await refresh_user_api_models(config)

    assert changed is False
    assert fetched == []  # managed providers are never user-api-fetched

