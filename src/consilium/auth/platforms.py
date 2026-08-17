from __future__ import annotations

import os
from typing import Any, NamedTuple, cast

import aiohttp
from pydantic import BaseModel

from consilium.auth import CONSILIUM_CODE_PLATFORM_ID
from consilium.config import Config, LLMModel, load_config, save_config
from consilium.llm import ModelCapability
from consilium.utils.aiohttp import new_client_session
from consilium.utils.logging import logger


class ModelInfo(BaseModel):
    """Model information returned from the API."""

    id: str
    context_length: int
    supports_reasoning: bool
    supports_image_in: bool
    supports_video_in: bool
    display_name: str | None = None

    @property
    def capabilities(self) -> set[ModelCapability]:
        """Derive capabilities from model info."""
        caps: set[ModelCapability] = set()
        if self.supports_reasoning:
            caps.add("thinking")
        # Models with "thinking" in name are always-thinking
        if "thinking" in self.id.lower():
            caps.update(("thinking", "always_thinking"))
        if self.supports_image_in:
            caps.add("image_in")
        if self.supports_video_in:
            caps.add("video_in")
        if self.id.lower().startswith("kimi-k2"):
            caps.update(("thinking", "image_in", "video_in"))
        return caps


class Platform(NamedTuple):
    id: str
    name: str
    base_url: str
    search_url: str | None = None
    fetch_url: str | None = None
    allowed_prefixes: list[str] | None = None


def _kimi_code_base_url() -> str:
    if base_url := os.getenv("CONSILIUM_CODE_BASE_URL"):
        return base_url
    return "https://api.consilium.com/coding/v1"


PLATFORMS: list[Platform] = [
    Platform(
        id=CONSILIUM_CODE_PLATFORM_ID,
        name="Consilium",
        base_url=_kimi_code_base_url(),
        search_url=f"{_kimi_code_base_url()}/search",
        fetch_url=f"{_kimi_code_base_url()}/fetch",
    ),
    Platform(
        id="moonshot-cn",
        name="Moonshot AI Open Platform (moonshot.cn)",
        base_url="https://api.moonshot.cn/v1",
        allowed_prefixes=["kimi-k"],
    ),
    Platform(
        id="moonshot-ai",
        name="Moonshot AI Open Platform (moonshot.ai)",
        base_url="https://api.moonshot.ai/v1",
        allowed_prefixes=["kimi-k"],
    ),
]

_PLATFORM_BY_ID = {platform.id: platform for platform in PLATFORMS}
_PLATFORM_BY_NAME = {platform.name: platform for platform in PLATFORMS}


def get_platform_by_id(platform_id: str) -> Platform | None:
    return _PLATFORM_BY_ID.get(platform_id)


def get_platform_by_name(name: str) -> Platform | None:
    return _PLATFORM_BY_NAME.get(name)


MANAGED_PROVIDER_PREFIX = "managed:"


def managed_provider_key(platform_id: str) -> str:
    return f"{MANAGED_PROVIDER_PREFIX}{platform_id}"


def managed_model_key(platform_id: str, model_id: str) -> str:
    return f"{platform_id}/{model_id}"


def parse_managed_provider_key(provider_key: str) -> str | None:
    if not provider_key.startswith(MANAGED_PROVIDER_PREFIX):
        return None
    return provider_key.removeprefix(MANAGED_PROVIDER_PREFIX)


def is_managed_provider_key(provider_key: str) -> bool:
    return provider_key.startswith(MANAGED_PROVIDER_PREFIX)


def get_platform_name_for_provider(provider_key: str) -> str | None:
    platform_id = parse_managed_provider_key(provider_key)
    if not platform_id:
        return None
    platform = get_platform_by_id(platform_id)
    return platform.name if platform else None


def _select_retry_api_keys(
    *,
    attempted_api_key: str,
    resolved_api_key: str,
    fallback_api_key: str,
) -> list[str]:
    result: list[str] = []
    for candidate in (resolved_api_key, fallback_api_key):
        if not candidate or candidate == attempted_api_key or candidate in result:
            continue
        result.append(candidate)
    return result


async def refresh_managed_models(config: Config) -> bool:
    if not config.is_from_default_location:
        return False

    managed_providers = {
        key: provider for key, provider in config.providers.items() if is_managed_provider_key(key)
    }
    if not managed_providers:
        return False

    changed = False
    updates: list[tuple[str, str, list[ModelInfo]]] = []
    oauth_manager = None
    for provider_key, provider in managed_providers.items():
        platform_id = parse_managed_provider_key(provider_key)
        if not platform_id:
            continue
        platform = get_platform_by_id(platform_id)
        if platform is None:
            logger.warning("Managed platform not found: {platform}", platform=platform_id)
            continue

        fallback_api_key = provider.api_key.get_secret_value()
        api_key = fallback_api_key
        if provider.oauth:
            if oauth_manager is None:
                from consilium.auth.oauth import OAuthManager

                oauth_manager = OAuthManager(config)
            try:
                await oauth_manager.ensure_fresh()
            except Exception as exc:
                logger.warning(
                    "Failed to refresh OAuth token before model sync for {platform}: {error}",
                    platform=platform_id,
                    error=exc,
                )
            api_key = oauth_manager.resolve_api_key(provider.api_key, provider.oauth)
        if not api_key:
            logger.warning(
                "Missing API key for managed provider: {provider}",
                provider=provider_key,
            )
            continue
        try:
            models = await list_models(platform, api_key)
        except aiohttp.ClientResponseError as exc:
            if exc.status != 401 or provider.oauth is None or oauth_manager is None:
                logger.error(
                    "Failed to refresh models for {platform}: {error}",
                    platform=platform_id,
                    error=exc,
                )
                continue
            logger.warning(
                "Received 401 while refreshing models for {platform}; attempting token refresh",
                platform=platform_id,
            )
            refresh_exc: Exception | None = None
            try:
                await oauth_manager.ensure_fresh(force=True)
            except Exception as exc2:
                refresh_exc = exc2
                logger.warning(
                    "Failed to refresh OAuth token after 401 for {platform}: {error}",
                    platform=platform_id,
                    error=exc2,
                )

            retry_api_keys = _select_retry_api_keys(
                attempted_api_key=api_key,
                resolved_api_key=oauth_manager.resolve_api_key(provider.api_key, provider.oauth),
                fallback_api_key=fallback_api_key,
            )
            if not retry_api_keys:
                logger.error(
                    "Failed to refresh models for {platform}: {error}",
                    platform=platform_id,
                    error=refresh_exc or exc,
                )
                continue
            retry_exc: Exception | None = None
            for retry_api_key in retry_api_keys:
                try:
                    models = await list_models(platform, retry_api_key)
                    break
                except Exception as exc3:
                    retry_exc = exc3
            else:
                logger.error(
                    "Failed to refresh models for {platform}: {error}",
                    platform=platform_id,
                    error=retry_exc or refresh_exc or exc,
                )
                continue
        except Exception as exc:
            logger.error(
                "Failed to refresh models for {platform}: {error}",
                platform=platform_id,
                error=exc,
            )
            continue

        updates.append((provider_key, platform_id, models))
        if _apply_models(config, provider_key, platform_id, models):
            changed = True

    if changed:
        config_for_save = load_config()
        save_changed = False
        for provider_key, platform_id, models in updates:
            if _apply_models(config_for_save, provider_key, platform_id, models):
                save_changed = True
        if save_changed:
            save_config(config_for_save)
    return changed


async def list_models(platform: Platform, api_key: str) -> list[ModelInfo]:
    async with new_client_session() as session:
        models = await _list_models(
            session,
            base_url=platform.base_url,
            api_key=api_key,
        )
    if platform.allowed_prefixes is None:
        return models
    prefixes = tuple(platform.allowed_prefixes)
    return [model for model in models if model.id.startswith(prefixes)]


_OPENROUTER_RESPONSE_TYPES = {"openai_responses", "openai_legacy"}
"""Provider types whose /models response follows the OpenAI/OpenRouter shape
(``data[].id``, ``context_length``, ``supported_parameters``,
``architecture.input_modalities``).
"""


async def _list_user_api_models(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    api_key: str,
) -> dict[str, ModelInfo]:
    """Fetch model metadata for a user-supplied API provider.

    Handles both the OpenAI-shape response (``{data: [...]}``) used by
    OpenRouter and a bare list. Only well-known fields are mapped; models
    whose metadata cannot be parsed are skipped. This is intentionally
    lenient: user providers may be any OpenAI-compatible gateway.
    """
    models_url = f"{base_url.rstrip('/')}/models"
    async with session.get(
        models_url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        raise_for_status=True,
    ) as response:
        resp_json = await response.json()

    data = resp_json.get("data") if isinstance(resp_json, dict) else None
    if not isinstance(data, list):
        if isinstance(resp_json, list):
            data = resp_json
        else:
            raise ValueError(f"Unexpected models response for {base_url}")

    result: dict[str, ModelInfo] = {}
    for item in cast(list[dict[str, Any]], data):
        model_id = item.get("id")
        if not model_id:
            continue
        model_id = str(model_id)

        context_length = int(item.get("context_length") or 0)
        if context_length <= 0:
            continue

        # OpenRouter exposes reasoning support via supported_parameters.
        supported_parameters = item.get("supported_parameters") or []
        supports_reasoning = bool(
            isinstance(supported_parameters, list)
            and any(p in supported_parameters for p in ("reasoning", "include_reasoning"))
        )

        # Modalities live under architecture.input_modalities (a simple list on
        # OpenRouter), or directly on the item for some gateways.
        architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        input_modalities = architecture.get("input_modalities")
        if not isinstance(input_modalities, list):
            input_modalities = item.get("input_modalities")
        input_modalities = input_modalities if isinstance(input_modalities, list) else []
        supports_image_in = "image" in input_modalities
        supports_video_in = "video" in input_modalities

        raw_display_name = item.get("display_name") or item.get("name")
        display_name = str(raw_display_name) if raw_display_name else None

        result[model_id] = ModelInfo(
            id=model_id,
            context_length=context_length,
            supports_reasoning=supports_reasoning,
            supports_image_in=supports_image_in,
            supports_video_in=supports_video_in,
            display_name=display_name,
        )
    return result


def _apply_user_api_context_info(
    config: Config,
    provider_key: str,
    model_info: dict[str, ModelInfo],
) -> bool:
    """Update existing config models of a user-api provider with real metadata.

    Unlike the managed-provider path (which creates/deletes models to mirror
    the API), this only *enriches* models the user already configured — the
    explicitly selected user-api models must keep their identity.
    """
    changed = False
    for model_key, model in config.models.items():
        if model.provider != provider_key:
            continue
        info = model_info.get(model.model or model_key)
        if info is None:
            continue
        capabilities = info.capabilities or None  # empty set -> None
        if model.max_context_size != info.context_length:
            model.max_context_size = info.context_length
            changed = True
        if model.capabilities != capabilities:
            model.capabilities = capabilities
            changed = True
        if model.display_name != info.display_name:
            model.display_name = info.display_name
            changed = True
    return changed


async def refresh_user_api_models(config: Config) -> bool:
    """Refresh metadata for user-supplied API providers (e.g. OpenRouter).

    The managed-provider refresh (``refresh_managed_models``) only handles
    known platforms. User providers (``user-api`` with an OpenAI-compatible
    gateway) were never API-fetched, so their models kept whatever bogus
    ``max_context_size``/``capabilities`` the extension hardcoded. This
    fetches ``/models`` and updates existing model entries in place.
    """
    if not config.is_from_default_location:
        return False

    changed = False
    for provider_key, provider in config.providers.items():
        if is_managed_provider_key(provider_key):
            continue
        if provider.type not in _OPENROUTER_RESPONSE_TYPES:
            continue
        base_url = (provider.base_url or "").strip()
        api_key = provider.api_key.get_secret_value().strip()
        if not base_url or not api_key:
            continue
        try:
            model_info = await refresh_user_api_models_for_provider(provider_key, base_url, api_key)
        except Exception as exc:
            logger.error(
                "Failed to refresh models for provider {provider}: {error}",
                provider=provider_key,
                error=exc,
            )
            continue
        if _apply_user_api_context_info(config, provider_key, model_info):
            changed = True

    if changed:
        config_for_save = load_config()
        save_changed = False
        for provider_key, provider in config_for_save.providers.items():
            if is_managed_provider_key(provider_key):
                continue
            if provider.type not in _OPENROUTER_RESPONSE_TYPES:
                continue
            base_url = (provider.base_url or "").strip()
            api_key = provider.api_key.get_secret_value().strip()
            if not base_url or not api_key:
                continue
            model_info = await refresh_user_api_models_for_provider(provider_key, base_url, api_key)
            if _apply_user_api_context_info(config_for_save, provider_key, model_info):
                save_changed = True
        if save_changed:
            save_config(config_for_save)
    return changed


async def refresh_user_api_models_for_provider(
    provider_key: str,
    base_url: str,
    api_key: str,
) -> dict[str, ModelInfo]:
    async with new_client_session() as session:
        return await _list_user_api_models(
            session,
            base_url=base_url,
            api_key=api_key,
        )


async def _list_models(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    api_key: str,
) -> list[ModelInfo]:
    models_url = f"{base_url.rstrip('/')}/models"
    try:
        async with session.get(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            raise_for_status=True,
        ) as response:
            resp_json = await response.json()
    except aiohttp.ClientError:
        raise

    data = resp_json.get("data")
    if not isinstance(data, list):
        raise ValueError(f"Unexpected models response for {base_url}")

    result: list[ModelInfo] = []
    for item in cast(list[dict[str, Any]], data):
        model_id = item.get("id")
        if not model_id:
            continue
        raw_display_name = item.get("display_name")
        display_name = str(raw_display_name) if raw_display_name else None
        result.append(
            ModelInfo(
                id=str(model_id),
                context_length=int(item.get("context_length") or 0),
                supports_reasoning=bool(item.get("supports_reasoning")),
                supports_image_in=bool(item.get("supports_image_in")),
                supports_video_in=bool(item.get("supports_video_in")),
                display_name=display_name,
            )
        )
    return result


def _apply_models(
    config: Config,
    provider_key: str,
    platform_id: str,
    models: list[ModelInfo],
) -> bool:
    changed = False
    model_keys: list[str] = []

    for model in models:
        model_key = managed_model_key(platform_id, model.id)
        model_keys.append(model_key)

        existing = config.models.get(model_key)
        capabilities = model.capabilities or None  # empty set -> None

        if existing is None:
            config.models[model_key] = LLMModel(
                provider=provider_key,
                model=model.id,
                max_context_size=model.context_length,
                capabilities=capabilities,
                display_name=model.display_name,
            )
            changed = True
            continue

        if existing.provider != provider_key:
            existing.provider = provider_key
            changed = True
        if existing.model != model.id:
            existing.model = model.id
            changed = True
        if existing.max_context_size != model.context_length:
            existing.max_context_size = model.context_length
            changed = True
        if existing.capabilities != capabilities:
            existing.capabilities = capabilities
            changed = True
        if existing.display_name != model.display_name:
            existing.display_name = model.display_name
            changed = True

    removed_default = False
    model_keys_set = set(model_keys)
    for key, model in list(config.models.items()):
        if model.provider != provider_key:
            continue
        if key in model_keys_set:
            continue
        del config.models[key]
        if config.default_model == key:
            removed_default = True
        changed = True

    if removed_default:
        if model_keys:
            config.default_model = model_keys[0]
        else:
            config.default_model = next(iter(config.models), "")
        changed = True

    if config.default_model and config.default_model not in config.models:
        config.default_model = next(iter(config.models), "")
        changed = True

    return changed
