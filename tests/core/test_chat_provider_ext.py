"""Tests for chat-provider instant-cancellation extensions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from consilium.chat_provider_ext import patch_chat_provider


class TestPatchChatProvider:
    @pytest.mark.asyncio
    async def test_patches_openai_like_provider(self) -> None:
        provider = MagicMock()
        provider.__class__.__module__ = "kosong.chat_provider.kimi"
        provider.__class__.__name__ = "Kimi"
        provider.client = MagicMock()
        provider._client = MagicMock()
        provider._api_key = "test-key"
        provider._base_url = "http://test"
        provider._client_kwargs = {}

        patch_chat_provider(provider)

        assert hasattr(provider, "force_abort")
        old_client = provider.client
        with patch("kosong.chat_provider.openai_common.create_openai_client") as mock_create:
            mock_create.return_value = MagicMock()
            task = provider.force_abort()
            # The abort marker must be set synchronously — BEFORE the async
            # client-close task runs — so the recovery layer sees cancel intent
            # even if the connection error surfaces a moment later.
            assert provider._aborted is True
            await task
        old_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_patches_anthropic_provider(self) -> None:
        provider = MagicMock()
        provider.__class__.__module__ = "kosong.contrib.chat_provider.anthropic"
        provider.__class__.__name__ = "Anthropic"
        provider._client = MagicMock()
        provider._api_key = "test-key"
        provider._base_url = "http://test"
        provider._client_kwargs = {}

        old_client = provider._client
        with patch("anthropic.AsyncAnthropic") as mock_anthropic:
            patch_chat_provider(provider)
            assert hasattr(provider, "force_abort")
            task = provider.force_abort()
            # Synchronous abort marker (same contract as the OpenAI path).
            assert provider._aborted is True
            await task
            old_client.close.assert_called_once()
            mock_anthropic.assert_called_once()

    def test_noop_for_unknown_provider(self) -> None:
        provider = MagicMock()
        provider.__class__.__module__ = "some.random.module"
        provider.__class__.__name__ = "RandomProvider"

        patch_chat_provider(provider)

        assert hasattr(provider, "force_abort")
        provider.force_abort()  # should not raise

    def test_skips_if_already_has_force_abort(self) -> None:
        provider = MagicMock()
        provider.force_abort = MagicMock()

        patch_chat_provider(provider)

        # Should not replace existing force_abort
        assert provider.force_abort is not None

    def test_none_provider(self) -> None:
        patch_chat_provider(None)  # should not raise
