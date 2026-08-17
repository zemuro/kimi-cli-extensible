from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pydantic
from jinja2 import Environment as JinjaEnvironment
from jinja2 import FileSystemLoader, StrictUndefined, TemplateError, UndefinedError
from kaos.path import KaosPath
from kosong.tooling import Toolset

from consilium.agentspec import load_agent_spec
from consilium.approval_runtime import ApprovalRuntime
from consilium.auth.oauth import OAuthManager
from consilium.background import BackgroundTaskManager
from consilium.config import Config, SubagentOverrideConfig
from consilium.exception import MCPConfigError, SystemPromptTemplateError
from consilium.llm import LLM
from consilium.notifications import NotificationManager
from consilium.session import Session
from consilium.skill import (
    Skill,
    discover_skills_from_roots,
    format_skills_for_prompt,
    index_skills,
    resolve_skills_roots,
)
from consilium.soul.approval import Approval, ApprovalState
from consilium.soul.denwarenji import DenwaRenji
from consilium.soul.toolset import ConsiliumToolset
from consilium.subagents.models import AgentTypeDefinition, ToolPolicy
from consilium.subagents.registry import LaborMarket
from consilium.subagents.store import SubagentStore
from consilium.utils.environment import Environment
from consilium.utils.logging import logger
from consilium.utils.path import find_project_root, is_within_directory, list_directory
from consilium.wire.root_hub import RootWireHub

if TYPE_CHECKING:
    from fastmcp.mcp_config import MCPConfig


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltinSystemPromptArgs:
    """Builtin system prompt arguments."""

    CONSILIUM_NOW: str
    """The current datetime."""
    CONSILIUM_WORK_DIR: KaosPath
    """The absolute path of current working directory."""
    CONSILIUM_WORK_DIR_LS: str
    """The directory listing of current working directory."""
    CONSILIUM_AGENTS_MD: str  # TODO: move to first message from system prompt
    """The merged content of AGENTS.md files (from project root to work_dir)."""
    CONSILIUM_SKILLS: str
    """Formatted information about available skills."""
    CONSILIUM_ADDITIONAL_DIRS_INFO: str
    """Formatted information about additional directories in the workspace."""
    CONSILIUM_OS: str
    """The operating system kind, e.g. 'Windows', 'macOS', 'Linux'."""
    CONSILIUM_SHELL: str
    """The shell executable used by the Shell tool, e.g. 'bash (`/bin/bash`)'."""


_AGENTS_MD_MAX_BYTES = 32 * 1024  # 32 KiB


async def _dirs_root_to_leaf(work_dir: KaosPath, project_root: KaosPath) -> list[KaosPath]:
    """Return the list of directories from *project_root* down to *work_dir* (inclusive)."""
    dirs: list[KaosPath] = []
    current = work_dir
    while True:
        dirs.append(current)
        if current == project_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    dirs.reverse()  # root → leaf
    return dirs


async def load_agents_md(work_dir: KaosPath) -> str | None:
    """Discover and merge ``AGENTS.md`` files from the project root down to *work_dir*.

    For each directory on the path, the following candidates are checked in order:

    1. ``.consilium/AGENTS.md``  — project-local kimi config (highest priority)
    2. ``AGENTS.md``        — standard location
    3. ``agents.md``        — lowercase variant (mutually exclusive with 2)

    Within a single directory, ``.consilium/AGENTS.md`` and ``AGENTS.md``/``agents.md``
    are **both** loaded (with ``.consilium/`` first), but ``AGENTS.md`` and ``agents.md``
    are mutually exclusive (uppercase wins).

    All discovered files are concatenated root→leaf, separated by ``\\n\\n``, with
    source annotations.  Total size is capped at :data:`_AGENTS_MD_MAX_BYTES`.
    Budget is allocated leaf-first so deeper (more specific) files are never
    truncated in favour of shallower ones.
    """
    project_root = await find_project_root(work_dir)
    dirs = await _dirs_root_to_leaf(work_dir, project_root)

    # Phase 1: collect all candidate files (root → leaf order)
    discovered: list[tuple[KaosPath, str]] = []  # (path, content)
    for d in dirs:
        # .consilium/AGENTS.md is always checked independently (can coexist with root-level file)
        kimi_path = d / ".consilium" / "AGENTS.md"
        # AGENTS.md and agents.md are mutually exclusive (uppercase wins)
        root_candidates = [d / "AGENTS.md", d / "agents.md"]

        candidates: list[KaosPath] = []
        if await kimi_path.is_file():
            candidates.append(kimi_path)
        for rc in root_candidates:
            if await rc.is_file():
                candidates.append(rc)
                break

        for path in candidates:
            content = (await path.read_text()).strip()
            if content:
                discovered.append((path, content))
                logger.info("Loaded agents.md: {path}", path=path)

    if not discovered:
        logger.info(
            "No AGENTS.md found from {root} to {cwd}",
            root=project_root,
            cwd=work_dir,
        )
        return None

    # Phase 2: allocate budget leaf-first so deeper (more specific) files
    # are never truncated in favour of shallower ones.
    # The annotation overhead (<!-- From: ... -->\n and \n\n separators)
    # is included in the budget so the final output never exceeds the limit.
    remaining = _AGENTS_MD_MAX_BYTES
    budgeted: list[tuple[KaosPath, str]] = [None] * len(discovered)  # type: ignore[list-item]
    for i in reversed(range(len(discovered))):
        path, content = discovered[i]
        annotation = f"<!-- From: {path} -->\n"
        # Reserve space for the annotation and the \n\n separator between parts
        separator_cost = len(b"\n\n") if i < len(discovered) - 1 else 0
        overhead = len(annotation.encode()) + separator_cost
        remaining -= overhead
        if remaining <= 0:
            budgeted[i] = (path, "")
            remaining = 0
            continue
        encoded = content.encode()
        if len(encoded) > remaining:
            content = encoded[:remaining].decode(errors="ignore").strip()
            logger.warning("AGENTS.md truncated due to size limit: {path}", path=path)
        remaining -= len(content.encode())
        budgeted[i] = (path, content)

    # Phase 3: assemble in root → leaf order, skipping entries emptied by truncation
    parts: list[str] = []
    for path, content in budgeted:
        if content:
            parts.append(f"<!-- From: {path} -->\n{content}")

    return "\n\n".join(parts) if parts else None


@dataclass(slots=True, kw_only=True)
class Runtime:
    """Agent runtime."""

    config: Config
    oauth: OAuthManager
    llm: LLM | None  # we do not freeze the `Runtime` dataclass because LLM can be changed
    compaction_llm: LLM | None = None
    session: Session
    builtin_args: BuiltinSystemPromptArgs
    denwa_renji: DenwaRenji
    approval: Approval
    labor_market: LaborMarket
    environment: Environment
    notifications: NotificationManager
    background_tasks: BackgroundTaskManager
    skills: dict[str, Skill]
    additional_dirs: list[KaosPath]
    skills_dirs: list[KaosPath]
    subagent_store: SubagentStore | None = None
    approval_runtime: ApprovalRuntime | None = None
    root_wire_hub: RootWireHub | None = None
    subagent_id: str | None = None
    subagent_type: str | None = None
    subagent_role_overrides: dict[str, Path] = field(default_factory=lambda: {})
    subagent_overrides: dict[str, SubagentOverrideConfig] = field(default_factory=lambda: {})
    role: Literal["root", "subagent"] = "root"
    ui_mode: str = "shell"
    resumed: bool = False
    hook_engine: Any = None
    """HookEngine instance, set by ConsiliumCLI after soul creation."""

    def __post_init__(self) -> None:
        if self.subagent_store is None:
            self.subagent_store = SubagentStore(self.session)
        if self.root_wire_hub is None:
            self.root_wire_hub = RootWireHub()
        if self.approval_runtime is None:
            self.approval_runtime = ApprovalRuntime()
        self.approval_runtime.bind_root_wire_hub(self.root_wire_hub)
        self.approval.set_runtime(self.approval_runtime)
        self.background_tasks.bind_runtime(self)

    @staticmethod
    async def create(
        config: Config,
        oauth: OAuthManager,
        llm: LLM | None,
        compaction_llm: LLM | None,
        session: Session,
        yolo: bool,
        afk: bool = False,
        runtime_afk: bool = False,
        skills_dirs: list[KaosPath] | None = None,
        subagent_role_overrides: dict[str, Path] | None = None,
        subagent_overrides: dict[str, SubagentOverrideConfig] | None = None,
    ) -> Runtime:
        ls_output, agents_md, environment = await asyncio.gather(
            list_directory(session.work_dir),
            load_agents_md(session.work_dir),
            Environment.detect(),
        )

        # Discover and format skills (grouped by scope for the system prompt).
        scoped_roots = await resolve_skills_roots(
            session.work_dir,
            skills_dirs=skills_dirs,
            merge_brands=config.merge_all_available_skills,
            extra_skill_dirs=config.extra_skill_dirs or None,
        )
        # Canonicalize so symlinked skill directories match resolved paths
        skills_roots_canonical = [s.root.canonical() for s in scoped_roots]
        skills = await discover_skills_from_roots(scoped_roots)
        skills_by_name = index_skills(skills)
        logger.info("Discovered {count} skill(s)", count=len(skills))
        skills_formatted = format_skills_for_prompt(skills)

        # Restore additional directories from session state, pruning stale entries
        additional_dirs: list[KaosPath] = []
        pruned = False
        valid_dir_strs: list[str] = []
        for dir_str in session.state.additional_dirs:
            d = KaosPath(dir_str).canonical()
            if await d.is_dir():
                additional_dirs.append(d)
                valid_dir_strs.append(dir_str)
            else:
                logger.warning(
                    "Additional directory no longer exists, removing from state: {dir}",
                    dir=dir_str,
                )
                pruned = True
        if pruned:
            session.state.additional_dirs = valid_dir_strs
            session.save_state()

        # Format additional dirs info for system prompt
        additional_dirs_info = ""
        if additional_dirs:
            parts: list[str] = []
            for d in additional_dirs:
                try:
                    dir_ls = await list_directory(d)
                except OSError:
                    logger.warning(
                        "Cannot list additional directory, skipping listing: {dir}", dir=d
                    )
                    dir_ls = "[directory not readable]"
                parts.append(f"### `{d}`\n\n```\n{dir_ls}\n```")
            additional_dirs_info = "\n\n".join(parts)

        # Merge invocation flags with persisted session state.
        effective_yolo = yolo or session.state.approval.yolo
        if afk and not session.state.approval.afk:
            session.state.approval.afk = True
            session.save_state()
        saved_actions = set(session.state.approval.auto_approve_actions)

        def _on_approval_change() -> None:
            session.state.approval.yolo = approval_state.yolo
            session.state.approval.afk = approval_state.afk
            session.state.approval.auto_approve_actions = set(approval_state.auto_approve_actions)
            session.save_state()

        approval_state = ApprovalState(
            yolo=effective_yolo,
            afk=session.state.approval.afk,
            runtime_afk=runtime_afk,
            auto_approve_actions=saved_actions,
            on_change=_on_approval_change,
        )
        notifications = NotificationManager(
            session.context_file.parent / "notifications",
            config.notifications,
        )

        return Runtime(
            config=config,
            oauth=oauth,
            llm=llm,
            session=session,
            builtin_args=BuiltinSystemPromptArgs(
                CONSILIUM_NOW=datetime.now().astimezone().isoformat(),
                CONSILIUM_WORK_DIR=session.work_dir,
                CONSILIUM_WORK_DIR_LS=ls_output,
                CONSILIUM_AGENTS_MD=agents_md or "",
                CONSILIUM_SKILLS=skills_formatted or "No skills found.",
                CONSILIUM_ADDITIONAL_DIRS_INFO=additional_dirs_info,
                CONSILIUM_OS=environment.os_kind,
                CONSILIUM_SHELL=f"{environment.shell_name} (`{environment.shell_path}`)",
            ),
            denwa_renji=DenwaRenji(),
            approval=Approval(state=approval_state),
            labor_market=LaborMarket(),
            environment=environment,
            notifications=notifications,
            background_tasks=BackgroundTaskManager(
                session,
                config.background,
                notifications=notifications,
            ),
            skills=skills_by_name,
            additional_dirs=additional_dirs,
            # Only expose skills roots outside the workspace for Glob access;
            # project-level roots are already within work_dir.
            skills_dirs=[
                r for r in skills_roots_canonical if not is_within_directory(r, session.work_dir)
            ],
            subagent_store=SubagentStore(session),
            approval_runtime=ApprovalRuntime(),
            root_wire_hub=RootWireHub(),
            role="root",
            subagent_role_overrides=subagent_role_overrides or {},
            subagent_overrides=subagent_overrides or {},
        )

    def copy_for_subagent(
        self,
        *,
        agent_id: str,
        subagent_type: str,
        llm_override: LLM | None = None,
        config: Config | None = None,
    ) -> Runtime:
        """Clone runtime for a subagent."""
        return Runtime(
            config=config if config is not None else self.config,
            oauth=self.oauth,
            llm=llm_override if llm_override is not None else self.llm,
            session=self.session,
            builtin_args=self.builtin_args,
            denwa_renji=DenwaRenji(),  # subagent must have its own DenwaRenji
            approval=self.approval.copy_with_yolo(True),
            labor_market=self.labor_market,
            environment=self.environment,
            notifications=self.notifications,
            background_tasks=self.background_tasks.copy_for_role("subagent"),
            skills=self.skills,
            # Share the same list reference so /add-dir mutations propagate to all agents
            additional_dirs=self.additional_dirs,
            skills_dirs=self.skills_dirs,
            subagent_store=self.subagent_store,
            approval_runtime=self.approval_runtime,
            root_wire_hub=self.root_wire_hub,
            subagent_id=agent_id,
            subagent_type=subagent_type,
            subagent_role_overrides=self.subagent_role_overrides,
            subagent_overrides=self.subagent_overrides,
            role="subagent",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Agent:
    """The loaded agent."""

    name: str
    system_prompt: str
    toolset: Toolset
    runtime: Runtime
    """Each agent has its own runtime, which should be derived from its main agent."""


def _parent_has_image_capability(runtime: Runtime) -> bool:
    """Return True when the parent model can already see images.

    The core ``vision`` subagent exists to give text-only models an eyes. When
    the parent model itself supports ``image_in``, the subagent is redundant
    and should not be advertised.
    """
    llm = getattr(runtime, "llm", None)
    if llm is None:
        return False
    caps = getattr(llm, "capabilities", None)
    return bool(caps) and "image_in" in caps


def _register_discovered_subagents(
    runtime: Runtime,
    agent_dir: Path,
    *,
    source: str,
) -> None:
    """Register declarable subagent YAML files found next to an agent file.

    Any ``*.yaml`` in the agent directory (other than main-agent files such as
    ``agent.yaml``/``do.yaml``/``think.yaml``) becomes an invocable subagent
    type named after the file stem. Explicit ``subagents:`` entries are
    registered before this runs, so they win on name conflicts.
    """
    from consilium.agentspec import discover_project_subagent_files

    discovered = discover_project_subagent_files(agent_dir)
    for subagent_name, spec_path in discovered.items():
        if runtime.labor_market.get_builtin_type(subagent_name) is not None:
            logger.debug(
                "Skipping discovered subagent {name}: already registered (explicit/builtin wins)",
                name=subagent_name,
            )
            continue
        try:
            builtin_spec = load_agent_spec(spec_path)
            tool_policy = (
                ToolPolicy(mode="allowlist", tools=tuple(builtin_spec.allowed_tools))
                if builtin_spec.allowed_tools is not None
                else ToolPolicy(mode="inherit")
            )
            runtime.labor_market.add_builtin_type(
                AgentTypeDefinition(
                    name=subagent_name,
                    description=builtin_spec.when_to_use or subagent_name,
                    agent_file=spec_path,
                    when_to_use=builtin_spec.when_to_use,
                    default_model=builtin_spec.model,
                    tool_policy=tool_policy,
                    min_summary_length=(
                        builtin_spec.min_summary_length
                        if builtin_spec.min_summary_length is not None
                        else 200
                    ),
                )
            )
            logger.debug(
                "Registered {source} discovered subagent type: {name} ({path})",
                source=source,
                name=subagent_name,
                path=spec_path,
            )
        except Exception as e:
            logger.warning(
                "Failed to register {source} discovered subagent {name} from {path}: {e}",
                source=source,
                name=subagent_name,
                path=spec_path,
                e=e,
            )


async def load_agent(
    agent_file: Path,
    runtime: Runtime,
    *,
    mcp_configs: list[MCPConfig] | list[dict[str, Any]],
    start_mcp_loading: bool = True,
) -> Agent:
    """
    Load agent from specification file.

    Raises:
        FileNotFoundError: When the agent file is not found.
        AgentSpecError(ConsiliumCLIException, ValueError): When the agent specification is invalid.
        SystemPromptTemplateError(ConsiliumCLIException, ValueError): When the system prompt template
            is invalid.
        InvalidToolError(ConsiliumCLIException, ValueError): When any tool cannot be loaded.
        MCPConfigError(ConsiliumCLIException, ValueError): When any MCP configuration is invalid.
        MCPRuntimeError(ConsiliumCLIException, RuntimeError): When any MCP server cannot be connected.
    """
    logger.info("Loading agent: {agent_file}", agent_file=agent_file)
    agent_spec = load_agent_spec(agent_file)

    # Apply subagent role override if one was provided for this subagent type.
    if (
        runtime.subagent_type
        and runtime.subagent_type in runtime.subagent_role_overrides
    ):
        override_path = runtime.subagent_role_overrides[runtime.subagent_type]
        try:
            agent_spec.system_prompt_args["ROLE_ADDITIONAL"] = override_path.read_text(
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(
                "Failed to load subagent role override for {subagent_type} from {path}: {error}. "
                "Falling back to built-in role.",
                subagent_type=runtime.subagent_type,
                path=override_path,
                error=e,
            )

    system_prompt = _load_system_prompt(
        agent_spec.system_prompt_path,
        agent_spec.system_prompt_args,
        runtime.builtin_args,
        config=runtime.config,
    )

    # Register built-in subagent types before loading tools because some tools render
    # descriptions from the labor market on initialization.
    for subagent_name, subagent_spec in agent_spec.subagents.items():
        # The core vision subagent is redundant when the parent model already
        # supports image input — hide it so the model doesn't waste calls on it.
        if subagent_name == "vision" and _parent_has_image_capability(runtime):
            logger.debug(
                "Skipping vision subagent: parent model already supports image input"
            )
            continue
        logger.debug(
            "Registering builtin subagent type: {subagent_name}", subagent_name=subagent_name
        )
        builtin_spec = load_agent_spec(subagent_spec.path)
        tool_policy = (
            ToolPolicy(mode="allowlist", tools=tuple(builtin_spec.allowed_tools))
            if builtin_spec.allowed_tools is not None
            else ToolPolicy(mode="inherit")
        )
        runtime.labor_market.add_builtin_type(
            AgentTypeDefinition(
                name=subagent_name,
                description=subagent_spec.description,
                agent_file=subagent_spec.path,
                when_to_use=builtin_spec.when_to_use,
                default_model=builtin_spec.model,
                tool_policy=tool_policy,
                min_summary_length=(
                    builtin_spec.min_summary_length
                    if builtin_spec.min_summary_length is not None
                    else 200
                ),
            )
        )

    # Auto-discover declarable project subagents: any *.yaml next to the loaded
    # agent file (other than main-agent files) becomes an invocable subagent
    # type. Explicit subagents: entries above win on name conflicts.
    _register_discovered_subagents(runtime, agent_file.parent, source="project")

    toolset = ConsiliumToolset()
    tool_deps = {
        ConsiliumToolset: toolset,
        Runtime: runtime,
        # TODO: remove all the following dependencies and use Runtime instead
        Config: runtime.config,
        BuiltinSystemPromptArgs: runtime.builtin_args,
        Session: runtime.session,
        DenwaRenji: runtime.denwa_renji,
        Approval: runtime.approval,
        LaborMarket: runtime.labor_market,
        Environment: runtime.environment,
    }
    tools = agent_spec.allowed_tools if agent_spec.allowed_tools is not None else agent_spec.tools
    if agent_spec.exclude_tools:
        logger.debug("Excluding tools: {tools}", tools=agent_spec.exclude_tools)
        tools = [tool for tool in tools if tool not in agent_spec.exclude_tools]
    toolset.load_tools(tools, tool_deps)

    # Load plugin tools
    from consilium.plugin.manager import get_plugins_dir
    from consilium.plugin.tool import load_plugin_tools

    plugin_tools = load_plugin_tools(get_plugins_dir(), runtime.config, approval=runtime.approval)
    for plugin_tool in plugin_tools:
        if toolset.find(plugin_tool.name) is not None:
            logger.warning(
                "Plugin tool '{name}' conflicts with an existing tool, skipping",
                name=plugin_tool.name,
            )
            continue
        toolset.add(plugin_tool)

    if mcp_configs:
        validated_mcp_configs: list[MCPConfig] = []
        if mcp_configs:
            from fastmcp.mcp_config import MCPConfig

            for mcp_config in mcp_configs:
                try:
                    validated_mcp_configs.append(
                        mcp_config
                        if isinstance(mcp_config, MCPConfig)
                        else MCPConfig.model_validate(mcp_config)
                    )
                except pydantic.ValidationError as e:
                    raise MCPConfigError(f"Invalid MCP config: {e}") from e
        if start_mcp_loading:
            await toolset.load_mcp_tools(validated_mcp_configs, runtime, in_background=True)
        else:
            toolset.defer_mcp_tool_loading(validated_mcp_configs, runtime)

    return Agent(
        name=agent_spec.name,
        system_prompt=system_prompt,
        toolset=toolset,
        runtime=runtime,
    )


def _load_system_prompt(
    path: Path,
    args: dict[str, str],
    builtin_args: BuiltinSystemPromptArgs,
    config: Config | None = None,
) -> str:
    logger.info("Loading system prompt: {path}", path=path)
    system_prompt = path.read_text(encoding="utf-8").strip()

    from consilium.prompts.system import assemble_system_prompt, is_assembled_prompt

    if is_assembled_prompt(system_prompt):
        logger.debug("Assembling system prompt from sections")
        overrides = config.system_prompt_overrides if config else {}
        system_prompt = assemble_system_prompt(overrides=overrides or None)

    logger.debug(
        "Substituting system prompt with builtin args: {builtin_args}, spec args: {spec_args}",
        builtin_args=builtin_args,
        spec_args=args,
    )
    env = JinjaEnvironment(
        loader=FileSystemLoader(path.parent),
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        variable_start_string="${",
        variable_end_string="}",
        undefined=StrictUndefined,
    )
    try:
        template = env.from_string(system_prompt)
        return template.render(asdict(builtin_args), **args)
    except UndefinedError as exc:
        raise SystemPromptTemplateError(f"Missing system prompt arg in {path}: {exc}") from exc
    except TemplateError as exc:
        raise SystemPromptTemplateError(f"Invalid system prompt template: {path}: {exc}") from exc
