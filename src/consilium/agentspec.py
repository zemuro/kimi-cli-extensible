from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from pydantic import BaseModel, Field

from consilium.exception import AgentSpecError

DEFAULT_AGENT_SPEC_VERSION = "1"
SUPPORTED_AGENT_SPEC_VERSIONS = (DEFAULT_AGENT_SPEC_VERSION,)


def get_agents_dir() -> Path:
    return Path(__file__).parent / "agents"


DEFAULT_AGENT_FILE = get_agents_dir() / "default" / "agent.yaml"
OKABE_AGENT_FILE = get_agents_dir() / "okabe" / "agent.yaml"
WORKSPACE_AGENT_FILE = Path(".consilium") / "agents" / "agent.yaml"


def find_workspace_agent_file(work_dir: Path) -> Path | None:
    """Return the workspace-level agent file if it exists, otherwise None."""
    candidate = work_dir / WORKSPACE_AGENT_FILE
    if candidate.is_file():
        return candidate
    return None


# Files that define the *main* agent (or assembled system prompt) rather than a
# subagent. These are never auto-discovered as subagent types.
MAIN_AGENT_FILES = {"agent.yaml", "do.yaml", "think.yaml", "system.yaml", "system.md"}


def discover_project_subagent_files(agent_dir: Path) -> dict[str, Path]:
    """Scan an agent override directory for declarable subagent YAML files.

    Any ``*.yaml`` in the directory (except main-agent files such as
    ``agent.yaml``/``do.yaml``/``think.yaml``) is treated as a subagent spec
    whose type name is the file stem (e.g. ``vision.yaml`` -> ``vision``).
    This lets a project declare task-specific subagents simply by dropping a
    YAML file into ``.consilium/agents/`` — no need to hand-list them in the
    ``subagents:`` block of ``agent.yaml``.

    Explicit ``subagents:`` entries take precedence at registration time
    (they are registered first), so an explicit block can override a
    discovered file of the same name.

    Returns:
        Mapping of subagent type name -> spec file path, sorted for
        deterministic registration order.
    """
    result: dict[str, Path] = {}
    if agent_dir is None or not agent_dir.is_dir():
        return result
    for candidate in sorted(agent_dir.iterdir()):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() != ".yaml":
            continue
        if candidate.name in MAIN_AGENT_FILES:
            continue
        result[candidate.stem] = candidate
    return result


class Inherit(NamedTuple):
    """Marker class for inheritance in agent spec."""


inherit = Inherit()


class AgentSpec(BaseModel):
    """Agent specification."""

    extend: str | None = Field(default=None, description="Agent file to extend")
    name: str | Inherit = Field(default=inherit, description="Agent name")  # required
    system_prompt_path: Path | Inherit = Field(
        default=inherit, description="System prompt path"
    )  # required
    system_prompt_args: dict[str, str] = Field(
        default_factory=dict, description="System prompt arguments"
    )
    system_prompt_args_files: dict[str, Path] = Field(
        default_factory=dict, description="System prompt arguments loaded from files"
    )
    model: str | None = Field(default=None, description="Default model alias")
    when_to_use: str | None = Field(default=None, description="Usage guidance")
    when_to_use_file: Path | None = Field(default=None, description="Path to usage guidance file")
    tools: list[str] | None | Inherit = Field(default=inherit, description="Tools")  # required
    allowed_tools: list[str] | None | Inherit = Field(default=inherit, description="Allowed tools")
    exclude_tools: list[str] | None | Inherit = Field(
        default=inherit, description="Tools to exclude"
    )
    subagents: dict[str, SubagentSpec] | None | Inherit = Field(
        default=inherit, description="Subagents"
    )
    min_summary_length: int | None = Field(
        default=None,
        description="Minimum summary length in chars. 0 disables continuation.",
    )


class SubagentSpec(BaseModel):
    """Subagent specification."""

    path: Path = Field(description="Subagent file path")
    description: str = Field(description="Subagent description")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedAgentSpec:
    """Resolved agent specification."""

    name: str
    system_prompt_path: Path
    system_prompt_args: dict[str, str]
    model: str | None
    when_to_use: str
    tools: list[str]
    allowed_tools: list[str] | None
    exclude_tools: list[str]
    subagents: dict[str, SubagentSpec]
    min_summary_length: int | None


def load_agent_spec(agent_file: Path) -> ResolvedAgentSpec:
    """
    Load agent specification from file.

    Raises:
        FileNotFoundError: If the agent spec file is not found.
        AgentSpecError: If the agent spec is not valid.
    """
    agent_spec = _load_agent_spec(agent_file)
    assert agent_spec.extend is None, "agent extension should be recursively resolved"
    if isinstance(agent_spec.name, Inherit):
        raise AgentSpecError("Agent name is required")
    if isinstance(agent_spec.system_prompt_path, Inherit):
        raise AgentSpecError("System prompt path is required")
    if isinstance(agent_spec.tools, Inherit):
        raise AgentSpecError("Tools are required")
    if isinstance(agent_spec.allowed_tools, Inherit):
        agent_spec.allowed_tools = None
    if isinstance(agent_spec.exclude_tools, Inherit):
        agent_spec.exclude_tools = []
    if isinstance(agent_spec.subagents, Inherit):
        agent_spec.subagents = {}
    return ResolvedAgentSpec(
        name=agent_spec.name,
        system_prompt_path=agent_spec.system_prompt_path,
        system_prompt_args=agent_spec.system_prompt_args,
        model=agent_spec.model,
        when_to_use=agent_spec.when_to_use or "",
        tools=agent_spec.tools or [],
        allowed_tools=agent_spec.allowed_tools,
        exclude_tools=agent_spec.exclude_tools or [],
        subagents=agent_spec.subagents or {},
        min_summary_length=agent_spec.min_summary_length,
    )


def _load_agent_spec(agent_file: Path) -> AgentSpec:
    if not agent_file.exists():
        raise AgentSpecError(f"Agent spec file not found: {agent_file}")
    if not agent_file.is_file():
        raise AgentSpecError(f"Agent spec path is not a file: {agent_file}")
    try:
        with open(agent_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise AgentSpecError(f"Invalid YAML in agent spec file: {e}") from e

    version = str(data.get("version", DEFAULT_AGENT_SPEC_VERSION))
    if version not in SUPPORTED_AGENT_SPEC_VERSIONS:
        raise AgentSpecError(f"Unsupported agent spec version: {version}")

    agent_spec = AgentSpec(**data.get("agent", {}))
    if isinstance(agent_spec.system_prompt_path, Path):
        agent_spec.system_prompt_path = (
            agent_file.parent / agent_spec.system_prompt_path
        ).absolute()
    if isinstance(agent_spec.subagents, dict):
        for v in agent_spec.subagents.values():
            v.path = (agent_file.parent / v.path).absolute()
    # Load when_to_use from file if specified (file wins over inline)
    if agent_spec.when_to_use_file is not None:
        when_to_use_path = (agent_file.parent / agent_spec.when_to_use_file).absolute()
        if not when_to_use_path.is_file():
            raise AgentSpecError(f"when_to_use file not found: {when_to_use_path}")
        agent_spec.when_to_use = when_to_use_path.read_text(encoding="utf-8")
    # Load system_prompt_args from files if specified (files win over inline)
    if agent_spec.system_prompt_args_files:
        for key, file_path in agent_spec.system_prompt_args_files.items():
            resolved_path = (agent_file.parent / file_path).absolute()
            if not resolved_path.is_file():
                raise AgentSpecError(f"system_prompt_args file not found: {resolved_path}")
            agent_spec.system_prompt_args[key] = resolved_path.read_text(encoding="utf-8")
    if agent_spec.extend:
        if agent_spec.extend == "default":
            base_agent_file = DEFAULT_AGENT_FILE
        else:
            base_agent_file = (agent_file.parent / agent_spec.extend).absolute()
        base_agent_spec = _load_agent_spec(base_agent_file)
        if not isinstance(agent_spec.name, Inherit):
            base_agent_spec.name = agent_spec.name
        if not isinstance(agent_spec.system_prompt_path, Inherit):
            base_agent_spec.system_prompt_path = agent_spec.system_prompt_path
        for k, v in agent_spec.system_prompt_args.items():
            # system prompt args should be merged instead of overwritten
            base_agent_spec.system_prompt_args[k] = v
        for k, v in agent_spec.system_prompt_args_files.items():
            base_agent_spec.system_prompt_args_files[k] = v
        if agent_spec.model is not None:
            base_agent_spec.model = agent_spec.model
        if agent_spec.when_to_use is not None:
            base_agent_spec.when_to_use = agent_spec.when_to_use
        if not isinstance(agent_spec.tools, Inherit):
            base_agent_spec.tools = agent_spec.tools
        if not isinstance(agent_spec.allowed_tools, Inherit):
            base_agent_spec.allowed_tools = agent_spec.allowed_tools
        if not isinstance(agent_spec.exclude_tools, Inherit):
            base_agent_spec.exclude_tools = agent_spec.exclude_tools
        if not isinstance(agent_spec.subagents, Inherit):
            base_agent_spec.subagents = agent_spec.subagents
        if agent_spec.min_summary_length is not None:
            base_agent_spec.min_summary_length = agent_spec.min_summary_length
        agent_spec = base_agent_spec
    return agent_spec
