from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast, get_args

import httpx
from kosong.chat_provider import ChatProvider
from pydantic import SecretStr

from consilium.constant import USER_AGENT
from consilium.utils.logging import logger

if TYPE_CHECKING:
    from consilium.auth.oauth import OAuthManager
    from consilium.config import Config, LLMModel, LLMProvider

type ProviderType = Literal[
    "kimi",
    "openai_legacy",
    "openai_responses",
    "anthropic",
    "google_genai",  # for backward-compatibility, equals to `gemini`
    "gemini",
    "vertexai",
    "_echo",
    "_scripted_echo",
    "_chaos",
]

type ModelCapability = Literal[
    "image_in",
    "video_in",
    "thinking",
    "always_thinking",
    "explicit_caching",
]
ALL_MODEL_CAPABILITIES: set[ModelCapability] = set(get_args(ModelCapability.__value__))


@dataclass(slots=True)
class LLM:
    chat_provider: ChatProvider
    max_context_size: int
    capabilities: set[ModelCapability]
    model_config: LLMModel | None = None
    provider_config: LLMProvider | None = None

    @property
    def model_name(self) -> str:
        return self.chat_provider.model_name


def model_display_name(model_name: str | None, model: LLMModel | None = None) -> str:
    if model is not None and model.display_name:
        return model.display_name
    if not model_name:
        return ""
    if model_name in ("kimi-for-coding", "kimi-code"):
        return "kimi-for-coding"
    return model_name


def augment_provider_with_env_vars(
    provider: LLMProvider,
    model: LLMModel,
    *,
    skip_model_name: bool = False,
) -> dict[str, str]:
    """Override provider/model settings from environment variables.

    Args:
        skip_model_name: When True, ``CONSILIUM_MODEL_NAME`` does not
            overwrite ``model.model``. Callers pass this when an explicit
            model was resolved (e.g. from ``--model`` or config), so a stale
            ``CONSILIUM_MODEL_NAME`` cannot silently change which model id is
            sent to the provider while all other fields (capabilities,
            display name, context size) come from the resolved object.
            The resulting mismatch previously caused requests to be routed to
            a different provider endpoint than the one the user selected.

    Returns:
        Mapping of environment variables that were applied.
    """
    applied: dict[str, str] = {}

    # Generic overrides for any provider if explicitly using CONSILIUM_*
    if base_url := os.getenv("CONSILIUM_BASE_URL"):
        provider.base_url = base_url
        applied["CONSILIUM_BASE_URL"] = base_url
    if api_key := os.getenv("CONSILIUM_API_KEY"):
        provider.api_key = SecretStr(api_key)
        applied["CONSILIUM_API_KEY"] = "******"
    if not skip_model_name and (model_name := os.getenv("CONSILIUM_MODEL_NAME")):
        model.model = model_name
        applied["CONSILIUM_MODEL_NAME"] = model_name
    if max_context_size := os.getenv("CONSILIUM_MODEL_MAX_CONTEXT_SIZE"):
        model.max_context_size = int(max_context_size)
        applied["CONSILIUM_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
    if capabilities := os.getenv("CONSILIUM_MODEL_CAPABILITIES"):
        caps_lower = (cap.strip().lower() for cap in capabilities.split(",") if cap.strip())
        model.capabilities = set(
            cast(ModelCapability, cap)
            for cap in caps_lower
            if cap in get_args(ModelCapability.__value__)
        )
        applied["CONSILIUM_MODEL_CAPABILITIES"] = capabilities

    match provider.type:
        case "openai_legacy" | "openai_responses":
            if base_url := os.getenv("OPENAI_BASE_URL"):
                provider.base_url = base_url
            if api_key := os.getenv("OPENAI_API_KEY"):
                provider.api_key = SecretStr(api_key)
        case _:
            pass

    if base_url := os.getenv("CONSILIUM_BASE_URL"):
        provider.base_url = base_url
        applied["CONSILIUM_BASE_URL"] = base_url
    if api_key := os.getenv("CONSILIUM_API_KEY"):
        provider.api_key = SecretStr(api_key)
        applied["CONSILIUM_API_KEY"] = "***"

    return applied


def _default_headers(provider: LLMProvider, oauth: OAuthManager | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if oauth:
        headers.update(oauth.common_headers())
    if provider.custom_headers:
        headers.update(provider.custom_headers)
    return headers


def _generation_kwargs_for_provider(
    generation: "LLMModel.generation | None",
    provider_type: ProviderType,
) -> dict[str, Any]:
    """Extract provider-specific generation kwargs from a GenerationConfig.

    Unknown params for a provider are silently omitted so strict SDKs
    (e.g. Anthropic) do not receive unsupported keys.
    """
    if generation is None:
        return {}

    kwargs: dict[str, Any] = {}

    match provider_type:
        case "kimi" | "openai_legacy":
            if generation.max_tokens is not None:
                kwargs["max_tokens"] = generation.max_tokens
            if generation.temperature is not None:
                kwargs["temperature"] = generation.temperature
            if generation.top_p is not None:
                kwargs["top_p"] = generation.top_p
            if generation.n is not None:
                kwargs["n"] = generation.n
            if generation.presence_penalty is not None:
                kwargs["presence_penalty"] = generation.presence_penalty
            if generation.frequency_penalty is not None:
                kwargs["frequency_penalty"] = generation.frequency_penalty
            if generation.stop is not None:
                kwargs["stop"] = generation.stop

        case "openai_responses":
            if generation.max_output_tokens is not None:
                kwargs["max_output_tokens"] = generation.max_output_tokens
            elif generation.max_tokens is not None:
                kwargs["max_output_tokens"] = generation.max_tokens
            if generation.temperature is not None:
                kwargs["temperature"] = generation.temperature
            if generation.top_p is not None:
                kwargs["top_p"] = generation.top_p
            if generation.max_tool_calls is not None:
                kwargs["max_tool_calls"] = generation.max_tool_calls
            if generation.top_logprobs is not None:
                kwargs["top_logprobs"] = generation.top_logprobs
            if generation.user is not None:
                kwargs["user"] = generation.user

        case "anthropic":
            if generation.max_tokens is not None:
                kwargs["max_tokens"] = generation.max_tokens
            if generation.temperature is not None:
                kwargs["temperature"] = generation.temperature
            if generation.top_p is not None:
                kwargs["top_p"] = generation.top_p
            if generation.top_k is not None:
                kwargs["top_k"] = generation.top_k
            if generation.tool_choice is not None:
                kwargs["tool_choice"] = generation.tool_choice
            if generation.extra_headers is not None:
                kwargs["extra_headers"] = generation.extra_headers

        case "google_genai" | "gemini" | "vertexai":
            if generation.max_output_tokens is not None:
                kwargs["max_output_tokens"] = generation.max_output_tokens
            elif generation.max_tokens is not None:
                kwargs["max_output_tokens"] = generation.max_tokens
            if generation.temperature is not None:
                kwargs["temperature"] = generation.temperature
            if generation.top_p is not None:
                kwargs["top_p"] = generation.top_p
            if generation.top_k is not None:
                kwargs["top_k"] = generation.top_k

        case _:
            # Unknown / test providers – pass common params and hope for the best
            if generation.temperature is not None:
                kwargs["temperature"] = generation.temperature
            if generation.top_p is not None:
                kwargs["top_p"] = generation.top_p
            if generation.max_tokens is not None:
                kwargs["max_tokens"] = generation.max_tokens

    return kwargs


def _map_cli_override(key: str, value: Any, provider_type: ProviderType) -> tuple[str, Any]:
    """Map common CLI parameter names to provider-specific API names."""
    if key == "max_tokens" and provider_type in (
        "openai_responses",
        "google_genai",
        "gemini",
        "vertexai",
    ):
        return "max_output_tokens", value
    return key, value


def create_llm(
    provider: LLMProvider,
    model: LLMModel,
    *,
    thinking: bool | None = None,
    session_id: str | None = None,
    oauth: OAuthManager | None = None,
    generation_overrides: dict[str, Any] | None = None,
    subagent_id: str | None = None,
) -> LLM | None:
    if provider.type not in {"_echo", "_scripted_echo"} and (
        not provider.base_url or not model.model
    ):
        logger.warning(
            "Cannot create LLM: missing base_url or model (provider_type={provider_type})",
            provider_type=provider.type,
        )
        return None

    resolved_api_key = (
        oauth.resolve_api_key(provider.api_key, provider.oauth)
        if oauth and provider.oauth
        else provider.api_key.get_secret_value()
    )

    match provider.type:
        case "kimi":
            from kosong.chat_provider.kimi import Kimi

            chat_provider = Kimi(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                default_headers=_default_headers(provider, oauth),
            )
        case "openai_legacy":
            from kosong.contrib.chat_provider.openai_legacy import OpenAILegacy

            reasoning_key = (
                provider.reasoning_key
                if provider.reasoning_key is not None
                else "reasoning_content"
            )
            chat_provider = OpenAILegacy(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                reasoning_key=reasoning_key,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
        case "openai_responses":
            from kosong.contrib.chat_provider.openai_responses import OpenAIResponses

            chat_provider = OpenAIResponses(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
        case "anthropic":
            from kosong.contrib.chat_provider.anthropic import Anthropic

            chat_provider = Anthropic(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                default_max_tokens=50000,
                metadata={"user_id": session_id} if session_id else None,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
        case "google_genai" | "gemini":
            from kosong.contrib.chat_provider.google_genai import GoogleGenAI

            chat_provider = GoogleGenAI(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
        case "vertexai":
            from kosong.contrib.chat_provider.google_genai import GoogleGenAI

            os.environ.update(provider.env or {})
            chat_provider = GoogleGenAI(
                model=model.model,
                base_url=provider.base_url,
                api_key=resolved_api_key,
                vertexai=True,
                default_headers=dict(provider.custom_headers) if provider.custom_headers else None,
            )
        case "_echo":
            from kosong.chat_provider.echo import EchoChatProvider

            chat_provider = EchoChatProvider()
        case "_scripted_echo":
            from kosong.chat_provider.echo import ScriptedEchoChatProvider

            if provider.env:
                os.environ.update(provider.env)
            scripts = _load_scripted_echo_scripts()
            trace_value = os.getenv("CONSILIUM_SCRIPTED_ECHO_TRACE", "")
            trace = trace_value.strip().lower() in {"1", "true", "yes", "on"}
            chat_provider = ScriptedEchoChatProvider(scripts, trace=trace)
        case "_chaos":
            from kosong.chat_provider.chaos import ChaosChatProvider, ChaosConfig
            from kosong.chat_provider.kimi import Kimi

            chat_provider = ChaosChatProvider(
                provider=Kimi(
                    model=model.model,
                    base_url=provider.base_url,
                    api_key=resolved_api_key,
                    default_headers=_default_headers(provider, oauth),
                ),
                chaos_config=ChaosConfig(
                    error_probability=0.8,
                    error_types=[429, 500, 503],
                ),
            )

    # ── Apply generation kwargs from config ──
    gen_kwargs = _generation_kwargs_for_provider(model.generation, provider.type)

    # Resolve capabilities early — needed for explicit_caching check and LLM object
    capabilities = resolve_model_capabilities(model, provider)

    # ── Prompt caching (OpenAI-compatible, e.g. DeepInfra, Kimi) ──
    # Always send the cache key for compatible providers (implicit prefix caching).
    # Only send explicit TTL options when the model declares `explicit_caching`
    # capability — otherwise providers like DeepInfra may 404 on unsupported models.
    if session_id and provider.type in ("kimi", "openai_legacy"):
        if subagent_id:
            gen_kwargs["prompt_cache_key"] = f"subagent-{subagent_id}"
            if "explicit_caching" in capabilities:
                gen_kwargs["prompt_cache_options"] = {"mode": "explicit", "ttl": "5m"}
        else:
            gen_kwargs["prompt_cache_key"] = session_id
            if "explicit_caching" in capabilities:
                ttl = model.generation.prompt_cache_ttl if model.generation and model.generation.prompt_cache_ttl else "1h"
                gen_kwargs["prompt_cache_options"] = {"mode": "explicit", "ttl": ttl}

    # Kimi-specific env var overrides (backward compatibility)
    if provider.type == "kimi":
        if temperature := os.getenv("CONSILIUM_MODEL_TEMPERATURE"):
            gen_kwargs["temperature"] = float(temperature)
        if top_p := os.getenv("CONSILIUM_MODEL_TOP_P"):
            gen_kwargs["top_p"] = float(top_p)
        if max_tokens := os.getenv("CONSILIUM_MODEL_MAX_TOKENS"):
            gen_kwargs["max_tokens"] = int(max_tokens)

    # CLI overrides (highest precedence)
    if generation_overrides:
        for key, value in generation_overrides.items():
            mapped_key, mapped_value = _map_cli_override(key, value, provider.type)
            gen_kwargs[mapped_key] = mapped_value

    if gen_kwargs:
        chat_provider = chat_provider.with_generation_kwargs(**gen_kwargs)

    # Apply thinking if specified or if model always requires thinking
    thinking_on = "always_thinking" in capabilities or (
        thinking is True and "thinking" in capabilities
    )
    if thinking_on:
        chat_provider = chat_provider.with_thinking("high")
    elif thinking is False:
        chat_provider = chat_provider.with_thinking("off")
    # If thinking is None and model doesn't always think, leave as-is (default behavior)

    # Apply Moonshot-specific ``thinking.keep`` (preserved thinking) only when
    # the model is actually in thinking mode; otherwise the API would see a
    # ``thinking.keep`` without an accompanying ``thinking.type`` it honors.
    if thinking_on and provider.type == "kimi":
        from kosong.chat_provider.kimi import Kimi

        if isinstance(chat_provider, Kimi) and (
            thinking_keep := os.getenv("CONSILIUM_MODEL_THINKING_KEEP")
        ):
            chat_provider = chat_provider.with_extra_body({"thinking": {"keep": thinking_keep}})

    return LLM(
        chat_provider=chat_provider,
        max_context_size=model.max_context_size,
        capabilities=capabilities,
        model_config=model,
        provider_config=provider,
    )


def clone_llm_with_model_alias(
    llm: LLM | None,
    config: Config,
    model_alias: str | None,
    *,
    session_id: str,
    oauth: OAuthManager | None,
    subagent_id: str | None = None,
) -> LLM | None:
    if model_alias is None:
        return llm
    if model_alias not in config.models:
        provider_type = os.getenv("CONSILIUM_PROVIDER", "kimi")
        base_url = ""
        api_key = SecretStr("")
        for p in config.providers.values():
            if p.type == provider_type and (p.base_url or p.api_key.get_secret_value()):
                base_url = p.base_url
                api_key = p.api_key
                break
        model = LLMModel(provider=provider_type, model=model_alias, max_context_size=100_000)
        provider = LLMProvider(type=provider_type, base_url=base_url, api_key=api_key)
        augment_provider_with_env_vars(provider, model)
    else:
        model = config.models[model_alias]
        provider = config.providers[model.provider]
    thinking: bool | None = None
    if llm is not None:
        effort = getattr(llm.chat_provider, "thinking_effort", None)
        if effort is not None:
            thinking = effort != "off"
    return create_llm(
        provider,
        model,
        thinking=thinking,
        session_id=session_id,
        oauth=oauth,
        subagent_id=subagent_id,
    )


def derive_model_capabilities(model: LLMModel) -> set[ModelCapability]:
    capabilities = set(model.capabilities or ())
    model_lower = model.model.lower()
    # Models with "thinking" or "reason" in their name are always-thinking models
    if "thinking" in model_lower or "reason" in model_lower:
        capabilities.update(("thinking", "always_thinking"))
    # Standard coding models support thinking (not necessarily vision)
    if "code" in model_lower or "coder" in model_lower:
        capabilities.add("thinking")
    # Vision-capable model patterns (heuristic fallback when API fetch unavailable)
    if any(
        pattern in model_lower
        for pattern in ("vision", "pixtral")
    ) or ("qwen" in model_lower and "vl" in model_lower):
        capabilities.add("image_in")
    if "vision" in model_lower:
        capabilities.add("video_in")
    if (("claude" in model_lower and "3" in model_lower)  # Claude 3+
            or "gemini" in model_lower
            or "gpt-4" in model_lower
            or "gpt-4o" in model_lower
            or "llama-3.2" in model_lower
            or "llama-4" in model_lower
            or "qwen2.5-vl" in model_lower
            or "qwen2.5vl" in model_lower):
        capabilities.add("image_in")
    return capabilities


_MODALITY_CACHE: dict[str, set[str]] | None = None


def fetch_openrouter_modalities(model_id: str, base_url: str | None) -> set[ModelCapability] | None:
    """Return capabilities from OpenRouter metadata, or None if unavailable.

    Fetches the OpenRouter `/api/v1/models` endpoint once per CLI session and
    caches the result in memory. Maps ``input_modalities`` ("image", "video")
    to Consilium capabilities ("image_in", "video_in"). Returns None on any
    error so the caller falls back to heuristic / explicit config.
    """
    global _MODALITY_CACHE
    if not base_url or "openrouter" not in base_url.lower():
        return None
    if _MODALITY_CACHE is None:
        try:
            resp = httpx.get("https://openrouter.ai/api/v1/models", timeout=5)
            resp.raise_for_status()
            cache: dict[str, set[str]] = {}
            for model in resp.json().get("data", []):
                arch = model.get("architecture", {})
                mods = arch.get("input_modalities", ["text"])
                caps: set[str] = set()
                if "image" in mods:
                    caps.add("image_in")
                if "video" in mods:
                    caps.add("video_in")
                cache[model["id"]] = caps
            _MODALITY_CACHE = cache
        except Exception:
            logger.warning("Failed to fetch OpenRouter model capabilities; using heuristics")
            return None
    return _MODALITY_CACHE.get(model_id)


def resolve_model_capabilities(
    model: LLMModel,
    provider: LLMProvider | None = None,
) -> set[ModelCapability]:
    """Resolve the effective capabilities for a model.

    Resolution order:
      1. Explicit ``capabilities`` in config.toml (highest priority)
      2. OpenRouter API metadata fetch (cached, session-scoped)
      3. Name-based heuristic (lowest priority)
    """
    if model.capabilities is not None:
        return set(model.capabilities) | derive_model_capabilities(model)
    if provider is not None:
        api_caps = fetch_openrouter_modalities(model.model, provider.base_url)
        if api_caps is not None:
            return set(api_caps) | derive_model_capabilities(model)
    return derive_model_capabilities(model)


def _load_scripted_echo_scripts() -> list[str]:
    script_path = os.getenv("CONSILIUM_SCRIPTED_ECHO_SCRIPTS")
    if not script_path:
        raise ValueError("CONSILIUM_SCRIPTED_ECHO_SCRIPTS is required for _scripted_echo.")
    path = Path(script_path).expanduser()
    if not path.exists():
        raise ValueError(f"Scripted echo file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data: object = json.loads(text)
    except json.JSONDecodeError:
        scripts = [chunk.strip() for chunk in text.split("\n---\n") if chunk.strip()]
        if scripts:
            return scripts
        raise ValueError(
            "Scripted echo file must be a JSON array of strings or a text file "
            "split by '\\n---\\n'."
        ) from None
    if isinstance(data, list):
        data_list = cast(list[object], data)
        if all(isinstance(item, str) for item in data_list):
            return cast(list[str], data_list)
    raise ValueError("Scripted echo JSON must be an array of strings.")
