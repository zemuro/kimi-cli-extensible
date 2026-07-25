from __future__ import annotations

import os

# Automatically sync KIMI_ and CONSILIUM_ environment variables for backward/forward compatibility
for env_key, env_value in list(os.environ.items()):
    if env_key.startswith("KIMI_"):
        consilium_key = env_key.replace("KIMI_", "CONSILIUM_", 1)
        if consilium_key not in os.environ:
            os.environ[consilium_key] = env_value
    elif env_key.startswith("CONSILIUM_"):
        kimi_key = env_key.replace("CONSILIUM_", "KIMI_", 1)
        if kimi_key not in os.environ:
            os.environ[kimi_key] = env_value

from typing import Any, cast


class _LazyLogger:
    """Import loguru only when logging is actually used."""

    def __init__(self) -> None:
        self._logger: Any | None = None

    def _get(self) -> Any:
        if self._logger is None:
            from loguru import logger as real_logger

            # Disable logging by default for library usage.
            # Application entry points (e.g., consilium.cli) should call logger.enable("consilium")
            # to enable logging.
            real_logger.disable("consilium")
            self._logger = real_logger
        return self._logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


logger = cast(Any, _LazyLogger())

__all__ = ["logger"]
