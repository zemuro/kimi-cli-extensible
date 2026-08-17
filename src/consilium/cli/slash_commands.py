"""CLI command that lists slash commands without building a full soul.

The VS Code extension used to spawn a `--wire` CLI process at webview startup
just to learn the slash-command list (the "verifyWire probe"). That spawned a
full soul/agent/MCP build and then immediately killed it — slow and, on
Windows, left an orphaned process tree. This command returns the same
slash-command metadata from the static registries without building a soul.
"""

from __future__ import annotations

import json
import sys
from typing import Annotated, Any

import typer

cli = typer.Typer(help="List available slash commands.")


def _collect() -> list[dict[str, Any]]:
    from consilium.soul.slash import registry as soul_slash_registry
    from consilium.think.slash import think_registry

    commands: dict[str, dict[str, Any]] = {}

    def _add(slash: Any) -> None:
        name = slash.name
        commands[name] = {
            "name": name,
            "description": slash.description,
            "aliases": list(slash.aliases),
        }

    for slash in think_registry.list_commands():
        _add(slash)
    for slash in soul_slash_registry.list_commands():
        _add(slash)

    return list(commands.values())


@cli.callback(invoke_without_command=True)
def slash_commands(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the slash commands as JSON.",
        ),
    ] = False,
) -> None:
    """Show available slash commands."""
    commands = _collect()
    if json_output:
        json.dump(commands, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    for cmd in commands:
        if cmd["aliases"]:
            typer.echo(f"/{cmd['name']} (aliases: {', '.join(cmd['aliases'])})")
        else:
            typer.echo(f"/{cmd['name']}")
        if cmd["description"]:
            typer.echo(f"    {cmd['description']}")
