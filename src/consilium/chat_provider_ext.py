"""Chat-provider extensions for instant cancellation.

Monkey-patches ``force_abort()`` onto kosong provider instances so that
in-flight HTTP requests are killed immediately when the user hits cancel.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from consilium.utils.logging import logger


async def _close_client_sync(client: Any) -> None:
    """Synchronous close of an async HTTP client — best-effort."""
    close = getattr(client, "close", None)
    if not callable(close):
        return
    try:
        result = close()
    except Exception:
        return
    if inspect.isawaitable(result):
        # We are in an async context — await it directly for immediate effect
        try:
            await result
        except Exception:
            pass


async def _force_abort_openai_like(provider: Any) -> None:
    """Close and recreate the underlying OpenAI client."""
    from kosong.chat_provider.openai_common import create_openai_client

    old_client = getattr(provider, "client", None) or getattr(provider, "_client", None)
    if old_client is not None:
        await _close_client_sync(old_client)

    api_key = getattr(provider, "_api_key", None)
    base_url = getattr(provider, "_base_url", None)
    client_kwargs = getattr(provider, "_client_kwargs", {})

    try:
        new_client = create_openai_client(
            api_key=api_key,
            base_url=base_url,
            client_kwargs=client_kwargs,
        )
    except Exception:
        logger.exception("force_abort: failed to recreate OpenAI client")
        return

    if hasattr(provider, "client"):
        provider.client = new_client
    if hasattr(provider, "_client"):
        provider._client = new_client


async def _force_abort_anthropic(provider: Any) -> None:
    """Close and recreate the underlying Anthropic client."""
    from anthropic import AsyncAnthropic

    old_client = getattr(provider, "_client", None)
    if old_client is not None:
        await _close_client_sync(old_client)

    api_key = getattr(provider, "_api_key", None)
    base_url = getattr(provider, "_base_url", None)
    client_kwargs = getattr(provider, "_client_kwargs", {})

    try:
        new_client = AsyncAnthropic(api_key=api_key, base_url=base_url, **client_kwargs)
    except Exception:
        logger.exception("force_abort: failed to recreate Anthropic client")
        return

    provider._client = new_client


def patch_chat_provider(provider: Any) -> None:
    """Add ``force_abort()`` to a provider instance if it doesn't already have one."""
    if provider is None:
        return
    # Check __dict__ directly rather than hasattr/getattr, because
    # MagicMock creates child mocks on attribute access and would
    # falsely report the attribute exists.
    if "force_abort" in provider.__dict__:
        return

    module = type(provider).__module__
    name = type(provider).__name__

    if "anthropic" in module.lower() or name.lower() == "anthropic":
        provider.force_abort = lambda: asyncio.create_task(_force_abort_anthropic(provider))  # type: ignore[method-assign]
    elif "openai" in module.lower() or name.lower().startswith("kimi"):
        provider.force_abort = lambda: asyncio.create_task(_force_abort_openai_like(provider))  # type: ignore[method-assign]
    else:
        # Unknown provider — no-op abort
        provider.force_abort = lambda: None  # type: ignore[method-assign]
