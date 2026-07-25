from __future__ import annotations

from inline_snapshot import snapshot
from pydantic import SecretStr

from consilium.config import GenerationConfig, LLMModel, LLMProvider
from consilium.llm import create_llm


def test_create_llm_consilium_overrides_config():
    """CLI --temperature/--top-p/--max-tokens override config values."""
    provider = LLMProvider(
        type="kimi",
        base_url="https://api.test/v1",
        api_key=SecretStr("test-key"),
    )
    model = LLMModel(
        provider="kimi",
        model="kimi-base",
        max_context_size=4096,
        generation=GenerationConfig(
            temperature=0.1,
            top_p=0.5,
            max_tokens=16000,
        ),
    )

    llm = create_llm(
        provider,
        model,
        generation_overrides={"temperature": 0.9, "top_p": 0.95, "max_tokens": 2048},
    )
    assert llm is not None

    assert llm.chat_provider.model_parameters == snapshot(
        {
            "base_url": "https://api.test/v1/",
            "temperature": 0.9,
            "top_p": 0.95,
            "max_tokens": 2048,
        }
    )


def test_create_llm_consilium_overrides_env(monkeypatch):
    """CLI overrides win over env vars."""
    monkeypatch.setenv("CONSILIUM_MODEL_TEMPERATURE", "0.2")
    monkeypatch.setenv("CONSILIUM_MODEL_MAX_TOKENS", "1234")

    provider = LLMProvider(
        type="kimi",
        base_url="https://api.test/v1",
        api_key=SecretStr("test-key"),
    )
    model = LLMModel(
        provider="kimi",
        model="kimi-base",
        max_context_size=4096,
    )

    llm = create_llm(
        provider,
        model,
        generation_overrides={"temperature": 0.99, "max_tokens": 9999},
    )
    assert llm is not None

    assert llm.chat_provider.model_parameters == snapshot(
        {
            "base_url": "https://api.test/v1/",
            "temperature": 0.99,
            "max_tokens": 9999,
        }
    )


def test_create_llm_openai_responses_cli_max_tokens_mapping():
    """CLI --max-tokens is mapped to max_output_tokens for OpenAI Responses."""
    from kosong.contrib.chat_provider.openai_responses import OpenAIResponses

    provider = LLMProvider(
        type="openai_responses",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("test-key"),
    )
    model = LLMModel(
        provider="openai",
        model="gpt-5-codex",
        max_context_size=128000,
    )

    llm = create_llm(
        provider,
        model,
        generation_overrides={"max_tokens": 4096},
    )
    assert llm is not None
    assert isinstance(llm.chat_provider, OpenAIResponses)
    assert llm.chat_provider.model_parameters["max_output_tokens"] == 4096


def test_create_llm_gemini_cli_max_tokens_mapping():
    """CLI --max-tokens is mapped to max_output_tokens for Gemini."""
    from kosong.contrib.chat_provider.google_genai import GoogleGenAI

    provider = LLMProvider(
        type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        api_key=SecretStr("test-key"),
    )
    model = LLMModel(
        provider="google",
        model="gemini-2.5-pro",
        max_context_size=1000000,
    )

    llm = create_llm(
        provider,
        model,
        generation_overrides={"max_tokens": 2048},
    )
    assert llm is not None
    assert isinstance(llm.chat_provider, GoogleGenAI)
    assert llm.chat_provider.model_parameters["max_output_tokens"] == 2048
