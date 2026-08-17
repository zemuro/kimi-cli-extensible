"""Unit tests for ACPServer.initialize — argv handling."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from consilium.acp.server import ACPServer

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "argv, expected_command, expected_terminal_args",
    [
        # Standard entry-point: kimi acp
        (["/usr/local/bin/kimi", "acp"], "/usr/local/bin/kimi", ["login"]),
        # kimi-code entry-point (JetBrains scenario)
        (["/usr/local/bin/kimi-code", "acp"], "/usr/local/bin/kimi-code", ["login"]),
        # kimi-cli entry-point
        (["/usr/local/bin/kimi-cli", "acp"], "/usr/local/bin/kimi-cli", ["login"]),
        # Arbitrary wrapper script
        (["/opt/wrapper.sh", "acp"], "/opt/wrapper.sh", ["login"]),
    ],
    ids=["kimi", "kimi-code", "kimi-cli", "wrapper-script"],
)
async def test_initialize_argv_handling(
    argv: list[str],
    expected_command: str,
    expected_terminal_args: list[str],
):
    """initialize() should not crash regardless of sys.argv content."""
    server = ACPServer()

    with patch("consilium.acp.server.sys") as mock_sys, patch(
        "consilium.acp.server.load_config"
    ) as mock_load_config:
        # Make load_config return a config that has managed:kimi-code configured
        # (independent of the developer's real config.toml) so the terminal-auth
        # method is built.
        from consilium.config import Config

        mock_config = Config()
        mock_config.providers["managed:kimi-code"] = type("P", (), {})()
        mock_load_config.return_value = mock_config

        mock_sys.argv = argv
        resp = await server.initialize(protocol_version=1)

    assert resp.protocol_version == 1
    assert resp.auth_methods is not None
    assert len(resp.auth_methods) == 1

    auth_method = resp.auth_methods[0]
    assert auth_method.field_meta is not None
    terminal_auth = auth_method.field_meta["terminal-auth"]
    assert terminal_auth["command"] == expected_command
    assert terminal_auth["args"] == expected_terminal_args
