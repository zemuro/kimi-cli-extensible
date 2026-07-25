"""Worker module for running ConsiliumCLI in a subprocess.

This module is the entry point for the subprocess that runs ConsiliumCLI in wire mode.
It reads the session configuration from disk and runs ConsiliumCLI.run_wire_stdio().

Usage:
    python -m consilium.web.runner.worker <session_id>
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from uuid import UUID

from consilium import logger
from consilium.app import ConsiliumCLI, enable_logging
from consilium.cli.mcp import get_global_mcp_config_file
from consilium.exception import MCPConfigError
from consilium.web.store.sessions import load_session_by_id


async def run_worker(session_id: UUID) -> None:
    """Run the ConsiliumCLI worker for a session."""
    # Find session by ID using the web store
    joint_session = load_session_by_id(session_id)
    if joint_session is None:
        raise ValueError(f"Session not found: {session_id}")

    # Get the consilium session object
    session = joint_session.consilium_session

    # Load default MCP config file if it exists
    default_mcp_file = get_global_mcp_config_file()
    mcp_configs: list[dict[str, Any]] = []
    if default_mcp_file.exists():
        raw = default_mcp_file.read_text(encoding="utf-8")
        try:
            mcp_configs = [json.loads(raw)]
        except json.JSONDecodeError:
            logger.warning(
                "Invalid JSON in MCP config file: {path}",
                path=default_mcp_file,
            )

    # Detect whether this is a resumed session (has prior state on disk)
    # vs a brand-new session that should honor config.default_plan_mode.
    resumed = (session.dir / "state.json").exists()

    # Create ConsiliumCLI instance with MCP configuration
    try:
        consilium = await ConsiliumCLI.create(
            session, mcp_configs=mcp_configs or None, resumed=resumed, ui_mode="wire"
        )
    except MCPConfigError as exc:
        logger.warning(
            "Invalid MCP config in {path}: {error}. Starting without MCP.",
            path=default_mcp_file,
            error=exc,
        )
        consilium = await ConsiliumCLI.create(session, mcp_configs=None, resumed=resumed, ui_mode="wire")

    # Run in wire stdio mode
    await consilium.run_wire_stdio()


def main() -> None:
    """Entry point for the worker subprocess."""
    from consilium.utils.proctitle import set_process_title
    from consilium.utils.proxy import normalize_proxy_env

    normalize_proxy_env()
    set_process_title("consilium-code-worker")

    if len(sys.argv) < 2:
        print("Usage: python -m consilium.web.runner.worker <session_id>", file=sys.stderr)
        sys.exit(1)

    try:
        session_id = UUID(sys.argv[1])
    except ValueError:
        print(f"Invalid session ID: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)

    # Enable logging for the subprocess
    enable_logging(debug=False)

    # Run the async worker
    asyncio.run(run_worker(session_id))


if __name__ == "__main__":
    main()
