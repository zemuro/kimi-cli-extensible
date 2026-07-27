from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
import sys
import time
import warnings
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import kaos
from kaos.path import KaosPath
from pydantic import SecretStr

from consilium.agentspec import DEFAULT_AGENT_FILE, find_workspace_agent_file
from consilium.auth.oauth import CONSILIUM_CODE_OAUTH_KEY, OAuthManager, get_device_id
from consilium.background.models import is_terminal_status
from consilium.cli import InputFormat, OutputFormat
from consilium.config import Config, LLMModel, LLMProvider, SubagentOverrideConfig, load_config
from consilium.constant import VERSION
from consilium.llm import augment_provider_with_env_vars, create_llm, model_display_name
from consilium.session import Session
from consilium.share import get_share_dir
from consilium.soul import RunCancelled, run_soul
from consilium.soul.agent import Runtime, _load_system_prompt, load_agent
from consilium.soul.context import Context
from consilium.soul.consiliumsoul import ConsiliumSoul
from consilium.utils.aioqueue import QueueShutDown
from consilium.utils.envvar import get_env_bool
from consilium.utils.logging import logger, open_original_stderr, redirect_stderr_to_logger
from consilium.utils.path import shorten_home
from consilium.wire import Wire, WireUISide
from consilium.wire.types import ApprovalRequest, ApprovalResponse, ContentPart, WireMessage

if TYPE_CHECKING:
    from fastmcp.mcp_config import MCPConfig


def _patch_session_id(record: dict[str, Any]) -> None:
    """Inject the current session ID (from ContextVar) into log records."""
    try:
        from consilium.soul.toolset import get_session_id

        sid = get_session_id()
        record["extra"]["sid"] = sid if sid else ""
    except Exception:
        record["extra"].setdefault("sid", "")


def enable_logging(debug: bool = False, *, redirect_stderr: bool = True) -> None:
    # NOTE: stderr redirection is implemented by swapping the process-level fd=2 (dup2).
    # That can hide Click/Typer error output during CLI startup, so some entrypoints delay
    # installing it until after critical initialization succeeds.
    logger.remove()  # Remove default stderr handler
    logger.enable("consilium")
    if debug:
        logger.enable("kosong")
    logger.add(
        get_share_dir() / "logs" / "kimi.log",
        # FIXME: configure level for different modules
        level="TRACE" if debug else "INFO",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {extra[sid]} - {message}"
        ),
        rotation="06:00",
        retention="10 days",
    )
    logger.configure(extra={"sid": ""}, patcher=_patch_session_id)
    if redirect_stderr:
        redirect_stderr_to_logger()


def _write_original_stderr(text: str) -> None:
    """Write a user-facing notice to the terminal even if ``fd=2`` has been
    redirected into the logger by ``redirect_stderr_to_logger``.

    Falls back to ``sys.stderr`` when no redirector is installed (tests,
    early-startup code paths), matching the semantics of ``_emit_fatal_error``
    in ``cli/__init__.py``.
    """
    with open_original_stderr() as stream:
        if stream is not None:
            stream.write(text.encode("utf-8", errors="replace"))
            stream.flush()
            return
    sys.stderr.write(text)


async def _refresh_managed_models_silent(config: Config) -> None:
    from consilium.auth.platforms import refresh_managed_models

    try:
        await refresh_managed_models(config)
    except Exception as exc:
        logger.warning("Background managed-model refresh failed: {error}", error=exc)


def _cleanup_stale_foreground_subagents(runtime: Runtime) -> None:
    subagent_store = getattr(runtime, "subagent_store", None)
    if subagent_store is None:
        return

    stale_agent_ids = [
        record.agent_id
        for record in subagent_store.list_instances()
        if record.status == "running_foreground"
    ]
    for agent_id in stale_agent_ids:
        logger.warning(
            "Marking stale foreground subagent instance as failed during startup: {agent_id}",
            agent_id=agent_id,
        )
        subagent_store.update_instance(agent_id, status="failed")


def _resolve_model_and_provider(
    config: Config, model_name: str | None
) -> tuple[LLMModel, LLMProvider]:
    """Resolve model and provider from config and CLI overrides."""
    model: LLMModel | None = None
    provider: LLMProvider | None = None
    if not model_name and config.default_model and config.default_model in config.models:
        model = config.models[config.default_model]
        provider = config.providers[model.provider]
    elif not model_name and config.default_model:
        # Fallback if default model is not in config.models
        model_name = config.default_model
        
    if model_name and model_name in config.models:
        model = config.models[model_name]
        provider = config.providers[model.provider]
        
    if not model:
        provider_type = os.getenv("CONSILIUM_PROVIDER", "kimi")
        base_url = ""
        api_key = SecretStr("")
        for p in config.providers.values():
            if p.type == provider_type and (p.base_url or p.api_key.get_secret_value()):
                base_url = p.base_url
                api_key = p.api_key
                break
        model = LLMModel(provider=provider_type, model=model_name or "", max_context_size=100_000)
        provider = LLMProvider(type=provider_type, base_url=base_url, api_key=api_key)
    assert provider is not None
    assert model is not None
    return model, provider


async def create_think_soul(
    session: Session,
    config: Config | Path | None,
    model_name: str | None,
    thinking: bool | None,
    generation_overrides: dict[str, Any] | None,
    budget_tokens: int | None,
    agent_file: Path | None = None,
    subagent_role_overrides: dict[str, Path] | None = None,
    subagent_overrides: dict[str, SubagentOverrideConfig] | None = None,
    yolo: bool = False,
) -> tuple[Any, dict[str, str]]:
    """Create a ThinkSoul with the given configuration."""
    from consilium.think import ThinkSoul
    from consilium.think.models import ThinkSession
    from consilium.think.storage import load_session as load_think_session

    _config = config if isinstance(config, Config) else load_config(config)
    if budget_tokens is not None:
        _config.budget_tokens = budget_tokens

    model, provider = _resolve_model_and_provider(_config, model_name)
    env_overrides = augment_provider_with_env_vars(provider, model)
    _thinking = _config.default_thinking if thinking is None else thinking

    from consilium.auth.oauth import OAuthManager

    oauth = OAuthManager(_config)
    llm = create_llm(
        provider,
        model,
        thinking=_thinking,
        session_id=session.id,
        oauth=oauth,
        generation_overrides=generation_overrides,
    )

    work_dir = Path(session.work_dir.unsafe_to_local_path()) if session.work_dir else None
    think_session = load_think_session(session.id, work_dir=work_dir)
    if think_session is None:
        think_session = ThinkSession(id=session.id)

        # Migrate legacy Do history to Think history if available
        if not session.is_empty():
            import json
            import time
            from uuid import uuid4
            from consilium.think.models import ThinkMessage
            from consilium.think.storage import save_session

            try:
                with session.context_file.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        role = data.get("role")
                        if role not in ("user", "assistant"):
                            continue

                        content = data.get("content", "")
                        if isinstance(content, list):
                            text_parts = [
                                p.get("text", "")
                                for p in content
                                if isinstance(p, dict) and p.get("type") == "text"
                            ]
                            content = "".join(text_parts)
                        elif not isinstance(content, str):
                            content = str(content)

                        if content.strip():
                            think_session.messages.append(
                                ThinkMessage(
                                    id=f"msg_{uuid4().hex[:8]}",
                                    role=role,
                                    content=content,
                                    timestamp=time.time(),
                                )
                            )
                if think_session.messages:
                    save_session(think_session)
                    logger.info(
                        "Migrated {n} messages from legacy session to Think mode",
                        n=len(think_session.messages),
                    )
            except Exception:
                logger.exception("Failed to migrate legacy session to Think mode")

    compaction_llm = llm
    if _config.compaction_model:
        c_model, c_provider = _resolve_model_and_provider(_config, _config.compaction_model)
        if c_model and c_provider:
            c_env_overrides = augment_provider_with_env_vars(c_provider, c_model)
            compaction_llm = create_llm(
                c_provider,
                c_model,
                thinking=False,
                session_id=session.id,
                oauth=oauth,
            )

    # Create a lightweight Runtime for subagent support in Think mode
    from consilium.soul.agent import Runtime

    runtime = await Runtime.create(
        _config,
        oauth,
        llm,
        compaction_llm,
        session,
        yolo=yolo,
        afk=False,
        subagent_role_overrides=subagent_role_overrides,
        subagent_overrides=subagent_overrides,
    )

    from consilium.agentspec import load_agent_spec
    from consilium.subagents.models import AgentTypeDefinition, ToolPolicy

    def _register_subagents_from_spec(agent_spec_path: Path, source: str) -> None:
        spec = load_agent_spec(agent_spec_path)
        for subagent_name, subagent_spec in spec.subagents.items():
            try:
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
                logger.debug(
                    "Registered {source} subagent type: {subagent_name}",
                    source=source,
                    subagent_name=subagent_name,
                )
            except Exception as e:
                logger.warning(
                    "Failed to register {source} subagent type {subagent_name} from {path}: {e}",
                    source=source,
                    subagent_name=subagent_name,
                    path=subagent_spec.path,
                    e=e,
                )

    # Register built-in subagent types.
    builtin_agent_file = Path(__file__).parent / "agents" / "default" / "agent.yaml"
    _register_subagents_from_spec(builtin_agent_file, "builtin")
    # Register workspace-level overrides if they exist.
    workspace_agent_file = find_workspace_agent_file(Path(str(session.work_dir)))
    if workspace_agent_file is not None:
        _register_subagents_from_spec(workspace_agent_file, "workspace")

    # Load custom system prompt from agent file if provided.
    system_prompt: str | None = None
    if agent_file is not None:
        from consilium.agentspec import load_agent_spec

        try:
            spec = load_agent_spec(agent_file)
            system_prompt = _load_system_prompt(
                spec.system_prompt_path,
                spec.system_prompt_args,
                runtime.builtin_args,
                config=_config,
            )
        except Exception as e:
            logger.warning("Failed to load custom Think agent file {agent_file}: {error}. Falling back to built-in system prompt.", agent_file=agent_file, error=e)

    return ThinkSoul(session, llm, _config, think_session, runtime=runtime, system_prompt=system_prompt), env_overrides


class ConsiliumCLI:
    @staticmethod
    async def create(
        session: Session,
        *,
        # Basic configuration
        config: Config | Path | None = None,
        model_name: str | None = None,
        thinking: bool | None = None,
        # Run mode
        yolo: bool = False,
        afk: bool = False,
        runtime_afk: bool = False,
        plan_mode: bool = False,
        resumed: bool = False,
        ui_mode: str = "shell",
        # Extensions
        agent_file: Path | None = None,
        subagent_role_overrides: dict[str, Path] | None = None,
        subagent_overrides: dict[str, SubagentOverrideConfig] | None = None,
        mcp_configs: list[MCPConfig] | list[dict[str, Any]] | None = None,
        skills_dirs: list[KaosPath] | None = None,
        # Generation overrides (CLI > env > config)
        generation_overrides: dict[str, Any] | None = None,
        # Loop control
        max_steps_per_turn: int | None = None,
        max_retries_per_step: int | None = None,
        max_ralph_iterations: int | None = None,
        startup_progress: Callable[[str], None] | None = None,
        defer_mcp_loading: bool = False,
        budget_tokens: int | None = None,
        do_mode: bool = False,
        seed_from_think: str | None = None,
        plan_file: Path | None = None,
        phase: str | None = None,
    ) -> ConsiliumCLI:
        """Create a ConsiliumCLI instance.

        Args:
            session (Session): A session created by `Session.create` or `Session.continue_`.
            config (Config | Path | None, optional): Configuration to use, or path to config file.
                Defaults to None.
            model_name (str | None, optional): Name of the model to use. Defaults to None.
            thinking (bool | None, optional): Whether to enable thinking mode. Defaults to None.
            yolo (bool, optional): Approve all actions without confirmation. Defaults to False.
            afk (bool, optional): Invocation-level away-from-keyboard mode (no user is present
                to answer questions or approve actions). Implies auto-approve. Defaults to False.
            runtime_afk (bool, optional): Internal invocation-only afk overlay, used by print mode
                so it stays non-interactive without changing persisted session afk. Defaults to
                False.
            agent_file (Path | None, optional): Path to the agent file. Defaults to None.
            mcp_configs (list[MCPConfig | dict[str, Any]] | None, optional): MCP configs to load
                MCP tools from. Defaults to None.
            skills_dirs (list[KaosPath] | None, optional): Custom skills directories that
                override default user/project discovery. Defaults to None.
            max_steps_per_turn (int | None, optional): Maximum number of steps in one turn.
                Defaults to None.
            max_retries_per_step (int | None, optional): Maximum number of retries in one step.
                Defaults to None.
            max_ralph_iterations (int | None, optional): Extra iterations after the first turn in
                Ralph mode. Defaults to None.
            startup_progress (Callable[[str], None] | None, optional): Progress callback used by
                interactive startup UI. Defaults to None.
            defer_mcp_loading (bool, optional): Defer MCP startup until the interactive shell is
                ready. Defaults to False.

        Raises:
            FileNotFoundError: When the agent file is not found.
            ConfigError(ConsiliumCLIException, ValueError): When the configuration is invalid.
            AgentSpecError(ConsiliumCLIException, ValueError): When the agent specification is invalid.
            SystemPromptTemplateError(ConsiliumCLIException, ValueError): When the system prompt
                template is invalid.
            InvalidToolError(ConsiliumCLIException, ValueError): When any tool cannot be loaded.
            MCPConfigError(ConsiliumCLIException, ValueError): When any MCP configuration is invalid.
            MCPRuntimeError(ConsiliumCLIException, RuntimeError): When any MCP server cannot be
                connected.
        """
        _create_t0 = time.monotonic()
        _phase_timings_ms: dict[str, int] = {}

        if startup_progress is not None:
            startup_progress("Loading configuration...")

        _phase_t = time.monotonic()
        config = config if isinstance(config, Config) else load_config(config)
        _phase_timings_ms["config_ms"] = int((time.monotonic() - _phase_t) * 1000)
        if max_steps_per_turn is not None:
            config.loop_control.max_steps_per_turn = max_steps_per_turn
        if max_retries_per_step is not None:
            config.loop_control.max_retries_per_step = max_retries_per_step
        if max_ralph_iterations is not None:
            config.loop_control.max_ralph_iterations = max_ralph_iterations
        if budget_tokens is not None:
            config.budget_tokens = budget_tokens
        logger.info("Loaded config: {config}", config=config)

        _phase_t = time.monotonic()
        oauth = OAuthManager(config)

        bg_refresh_task = asyncio.create_task(_refresh_managed_models_silent(config))

        model: LLMModel | None = None
        provider: LLMProvider | None = None

        # try to use config file
        if not model_name and config.default_model:
            # no --model specified && default model is set in config
            model = config.models[config.default_model]
            provider = config.providers[model.provider]
        if model_name and model_name in config.models:
            # --model specified && model is set in config
            model = config.models[model_name]
            provider = config.providers[model.provider]

        if not model:
            from consilium.config import OAuthRef
            from consilium.auth.oauth import CONSILIUM_CODE_OAUTH_KEY

            model = LLMModel(
                provider="kimi", model=model_name or "kimi-for-coding", max_context_size=128_000
            )
            provider = LLMProvider(
                type="kimi",
                base_url="https://api.moonshot.cn/v1",
                api_key=SecretStr(""),
                oauth=OAuthRef(storage="file", key=CONSILIUM_CODE_OAUTH_KEY),
            )

        # try overwrite with environment variables
        assert provider is not None
        assert model is not None
        env_overrides = augment_provider_with_env_vars(provider, model)

        # determine thinking mode
        thinking = config.default_thinking if thinking is None else thinking

        # determine yolo mode
        yolo = yolo if yolo else config.default_yolo

        # determine plan mode (only for new sessions, not restored)
        if not resumed:
            plan_mode = plan_mode if plan_mode else config.default_plan_mode

        llm = create_llm(
            provider,
            model,
            thinking=thinking,
            session_id=session.id,
            oauth=oauth,
            generation_overrides=generation_overrides,
        )
        if llm is not None:
            from consilium.chat_provider_ext import patch_chat_provider

            patch_chat_provider(llm.chat_provider)
            logger.info("Using LLM provider: {provider}", provider=provider)
            logger.info("Using LLM model: {model}", model=model)
            logger.info("Thinking mode: {thinking}", thinking=thinking)

        compaction_llm = llm
        if config.compaction_model:
            c_model, c_provider = _resolve_model_and_provider(config, config.compaction_model)
            if c_model and c_provider:
                c_env_overrides = augment_provider_with_env_vars(c_provider, c_model)
                compaction_llm = create_llm(
                    c_provider,
                    c_model,
                    thinking=False,
                    session_id=session.id,
                    oauth=oauth,
                )

        if startup_progress is not None:
            startup_progress("Scanning workspace...")

        runtime = await Runtime.create(
            config,
            oauth,
            llm,
            compaction_llm,
            session,
            yolo,
            afk=afk,
            runtime_afk=runtime_afk,
            skills_dirs=skills_dirs,
            subagent_role_overrides=subagent_role_overrides,
            subagent_overrides=subagent_overrides,
        )
        runtime.ui_mode = ui_mode
        runtime.resumed = resumed
        runtime.notifications.recover()
        runtime.background_tasks.reconcile()
        _cleanup_stale_foreground_subagents(runtime)
        _phase_timings_ms["init_ms"] = int((time.monotonic() - _phase_t) * 1000)

        # Refresh plugin configs with fresh credentials (e.g. OAuth tokens)
        try:
            from consilium.plugin.manager import (
                collect_host_values,
                get_plugins_dir,
                refresh_plugin_configs,
            )

            host_values = collect_host_values(config, oauth)
            if host_values.get("api_key"):
                refresh_plugin_configs(get_plugins_dir(), host_values)
        except Exception:
            logger.debug("Failed to refresh plugin configs, skipping")

        if agent_file is None:
            workspace_agent_file = find_workspace_agent_file(session.work_dir.unsafe_to_local_path())
            if workspace_agent_file is not None:
                logger.info(
                    "Using workspace agent file: {workspace_agent_file}",
                    workspace_agent_file=workspace_agent_file,
                )
            agent_file = workspace_agent_file if workspace_agent_file is not None else DEFAULT_AGENT_FILE
        if startup_progress is not None:
            startup_progress("Loading agent...")

        _phase_t = time.monotonic()
        agent = await load_agent(
            agent_file,
            runtime,
            mcp_configs=mcp_configs or [],
            start_mcp_loading=not defer_mcp_loading,
        )
        _phase_timings_ms["mcp_ms"] = int((time.monotonic() - _phase_t) * 1000)

        if startup_progress is not None:
            startup_progress("Restoring conversation...")
        context = Context(session.context_file)
        await context.restore()

        if context.system_prompt is not None:
            agent = dataclasses.replace(agent, system_prompt=context.system_prompt)
        else:
            await context.write_system_prompt(agent.system_prompt)

        # Auto-migrate: if starting Do mode but think.jsonl exists and has newer messages,
        # fast-forward context.jsonl from think.jsonl. This handles resuming legacy Think
        # sessions in the new Do tab.
        if do_mode and resumed:
            from consilium.think.storage import think_path
            import json
            from kosong.message import Message, TextPart
            from pathlib import Path

            tf = think_path(session.id, work_dir=Path(str(session.work_dir)))
            if tf.exists():
                imported = 0
                existing_texts = set()
                for m in context.history:
                    # simplistic deduplication by content string
                    existing_texts.add(str(m.content))

                with open(tf, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            role = entry.get("role")
                            if role not in ("user", "assistant"):
                                continue

                            content = entry.get("content", "")
                            if isinstance(content, str):
                                msg = Message(role=role, content=[TextPart(text=content)])
                            else:
                                msg = Message(role=role, content=content)

                            # Deduplicate
                            if str(msg.content) not in existing_texts:
                                await context.append_message(msg)
                                existing_texts.add(str(msg.content))
                                imported += 1
                        except Exception:
                            continue

                if imported > 0:
                    break_msg = Message(
                        role="user",
                        content=[
                            TextPart(
                                text="<EPHEMERAL_MESSAGE>\nThe user has opened this session in the Do tab. You now have full access to tools and the filesystem. You are no longer restricted to reasoning. You can and should execute tools to solve the user's task. Disregard any previous constraints about not executing commands or modifying files.\n</EPHEMERAL_MESSAGE>"
                            )
                        ],
                    )
                    await context.append_message(break_msg)
                    logger.info(
                        "Auto-migrated {count} missing messages from think.jsonl to context.jsonl for session {sid}",
                        count=imported,
                        sid=session.id,
                    )

        # Seed Do-mode context from Think session (explicit flag)
        if seed_from_think and do_mode:
            import json

            from kosong.message import Message, TextPart

            from consilium.session import Session
            from consilium.think.storage import think_path
            from pathlib import Path

            imported = 0

            # Primary path: Think mode JSONL storage
            think_file = think_path(seed_from_think, work_dir=Path(str(session.work_dir)))
            if think_file.exists():
                with open(think_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        role = entry.get("role")
                        if role not in ("user", "assistant"):
                            continue
                        content = entry.get("content", "")
                        if isinstance(content, str):
                            msg = Message(role=role, content=[TextPart(text=content)])
                        else:
                            msg = Message(role=role, content=content)
                        await context.append_message(msg)
                        imported += 1
                logger.info(
                    "Seeded Do session with {count} messages from Think session {sid}",
                    count=imported,
                    sid=seed_from_think,
                )
            else:
                # Fallback: regular session context.jsonl
                think_session = await Session.find(session.work_dir, seed_from_think)
                if think_session and think_session.context_file.exists():
                    imported = await context.import_from_session(
                        think_session.context_file,
                        max_messages=100,
                    )
                    logger.info(
                        "Seeded Do session with {count} messages from regular session {sid}",
                        count=imported,
                        sid=seed_from_think,
                    )
                else:
                    logger.warning(
                        "Think session not found for seeding: {sid}",
                        sid=seed_from_think,
                    )

        soul = ConsiliumSoul(agent, context=context)

        # Wire up Do mode versioning (git snapshotting + change journal)
        if do_mode and config.do.auto_git_snapshot:
            from consilium.do.registry import register_do_session
            from consilium.do.session import DoSession

            do_session = DoSession(
                soul,
                work_dir=session.work_dir.unsafe_to_local_path(),
                plan_file=plan_file,
                phase=phase,
            )
            await do_session.start()

            soul.register_pre_tool_hook(do_session.capture_baseline)
            soul.register_post_tool_hook(do_session.on_tool_result)

            register_do_session(session.id, do_session)

            # Link Do session to Think session via dispatch
            if do_mode:
                from consilium.plan.dispatch import read_dispatch

                dispatch = read_dispatch()
                if dispatch and dispatch.think_session_id:
                    session.state.paired_session_id = dispatch.think_session_id
                    session.save_state()

        # Activate plan mode if requested (for new sessions or --plan flag)
        if plan_mode and not soul.plan_mode:
            await soul.set_plan_mode_from_manual(True)
        elif plan_mode and soul.plan_mode:
            # Already in plan mode from restored session, trigger activation reminder
            soul.schedule_plan_activation_reminder()

        # Create and inject hook engine
        from consilium.hooks.engine import HookEngine

        hook_engine = HookEngine(config.hooks, cwd=str(session.work_dir))
        soul.set_hook_engine(hook_engine)
        runtime.hook_engine = hook_engine

        # --- Initialize telemetry ---
        from consilium.telemetry import attach_sink, set_context
        from consilium.telemetry import disable as disable_telemetry

        telemetry_disabled = not config.telemetry or get_env_bool("CONSILIUM_DISABLE_TELEMETRY")
        if telemetry_disabled:
            disable_telemetry()
        else:
            device_id = get_device_id()
            set_context(device_id=device_id, session_id=session.id)
            from consilium.telemetry.sink import EventSink
            from consilium.telemetry.transport import AsyncTransport

            def _get_token() -> str | None:
                return oauth.get_cached_access_token(CONSILIUM_CODE_OAUTH_KEY)

            transport = AsyncTransport(device_id=device_id, get_access_token=_get_token)
            sink = EventSink(
                transport,
                version=VERSION,
                model=model.model if model else "",
                ui_mode=ui_mode,
            )
            attach_sink(sink)

        from consilium.telemetry import track, track_session_started_once
        from consilium.telemetry.crash import install_asyncio_handler, set_phase

        # App init finished — enter runtime phase and hook asyncio crashes.
        install_asyncio_handler()
        set_phase("runtime")

        if ui_mode != "wire":
            track_session_started_once(ui_mode=ui_mode, resumed=resumed)
        track(
            "started",
            resumed=resumed,
            yolo=runtime.approval.is_yolo(),
            afk=runtime.approval.is_afk(),
        )
        track(
            "startup_perf",
            duration_ms=int((time.monotonic() - _create_t0) * 1000),
            config_ms=_phase_timings_ms.get("config_ms", 0),
            init_ms=_phase_timings_ms.get("init_ms", 0),
            mcp_ms=_phase_timings_ms.get("mcp_ms", 0),
        )

        return ConsiliumCLI(
            soul,
            runtime,
            env_overrides,
            bg_refresh_task,
            do_mode=do_mode,
            agent_file=agent_file,
            subagent_role_overrides=subagent_role_overrides,
            yolo=yolo,
        )

    def __init__(
        self,
        _soul: ConsiliumSoul,
        _runtime: Runtime,
        _env_overrides: dict[str, str],
        _bg_refresh_task: asyncio.Task[None] | None = None,
        do_mode: bool = False,
        agent_file: Path | None = None,
        subagent_role_overrides: dict[str, Path] | None = None,
        yolo: bool = False,
    ) -> None:
        self._soul = _soul
        self._runtime = _runtime
        self._env_overrides = _env_overrides
        self._bg_refresh_task = _bg_refresh_task
        self._do_mode = do_mode
        self._agent_file = agent_file
        self._subagent_role_overrides = subagent_role_overrides
        self._yolo = yolo

    @property
    def soul(self) -> ConsiliumSoul:
        """Get the ConsiliumSoul instance."""
        return self._soul

    @property
    def session(self) -> Session:
        """Get the Session instance."""
        return self._runtime.session

    async def shutdown_background_tasks(self) -> None:
        """Kill active background tasks on exit, unless keep_alive_on_exit is configured.

        Prints a stderr notice naming each task so the user knows what is being
        terminated, waits out the configured kill grace period so SIGTERM can
        take effect, then reconciles and reports any workers that ignored the
        signal.

        This runs on the CLI's hard-shutdown path, so every failure mode must
        be contained: disk IO errors from ``list_tasks`` / ``reconcile`` or
        store corruption must not propagate and replace the real exit code
        with a traceback.
        """
        # Cancel the startup managed-model refresh task if it is still running
        # so it does not outlive the CLI process.
        if self._bg_refresh_task is not None and not self._bg_refresh_task.done():
            self._bg_refresh_task.cancel()

        bg_config = self._runtime.config.background
        if bg_config.keep_alive_on_exit:
            return

        try:
            manager = self._runtime.background_tasks
            active_views = [
                v
                for v in manager.list_tasks(status=None, limit=None)
                if not is_terminal_status(v.runtime.status)
            ]
            if not active_views:
                return

            # Split by whether the task has already been kill-requested (e.g.
            # by the ``--print`` timeout path which ran immediately before
            # this shutdown).  For those:
            #   - don't re-announce on stderr (user saw the timeout notice)
            #   - don't re-kill with a generic reason, which would overwrite
            #     the more specific ``kill_reason`` on disk
            # We still reconcile + grace-wait for them so they reach terminal
            # status before the process exits.
            fresh_targets = [v for v in active_views if v.control.kill_requested_at is None]

            if fresh_targets:
                # Build and emit the kill notice via ``open_original_stderr``
                # — ``sys.stderr.write`` alone would silently land in
                # ``kimi.log`` because ``redirect_stderr_to_logger`` has
                # replaced fd=2 with a pipe into the logger by this point.
                lines = [f"\u26a0  Killing {len(fresh_targets)} background tasks:\n"]
                for view in fresh_targets:
                    description = view.spec.description or ""
                    if len(description) > 60:
                        description = description[:57] + "..."
                    lines.append(f"  {view.spec.id}  {description}\n")
                _write_original_stderr("".join(lines))

                killed: list[str] = []
                for view in fresh_targets:
                    try:
                        manager.kill(view.spec.id, reason="CLI session ended")
                        killed.append(view.spec.id)
                    except Exception:
                        logger.exception(
                            "Failed to kill task {task_id} during shutdown",
                            task_id=view.spec.id,
                        )
                if killed:
                    logger.info(
                        "Stopped {n} background task(s) on exit: {ids}",
                        n=len(killed),
                        ids=killed,
                    )

            await asyncio.sleep(bg_config.kill_grace_period_ms / 1000)
            manager.reconcile()
            survivors = [
                v
                for v in manager.list_tasks(status=None, limit=None)
                if not is_terminal_status(v.runtime.status)
            ]
            if survivors:
                # Distinguish "worker is mid-shutdown" (kill request on record,
                # SIGTERM delivered, worker just hasn't written terminal state
                # yet) from a genuine leak (never got kill-requested, i.e.
                # ``manager.kill`` raised).  Without this split, users saw
                # ``killed N`` from the --print timeout path immediately
                # followed by ``(N tasks still alive)`` here — a direct
                # semantic contradiction.
                terminating = [s for s in survivors if s.control.kill_requested_at is not None]
                leaking = [s for s in survivors if s.control.kill_requested_at is None]
                # Report leaks first — ``stop request failed`` is strictly
                # more severe than ``still terminating`` (the latter will
                # resolve on its own once the worker writes terminal state).
                if leaking:
                    _write_original_stderr(
                        f"  ({len(leaking)} tasks still running; stop request failed)\n"
                    )
                if terminating:
                    _write_original_stderr(f"  ({len(terminating)} tasks still terminating)\n")
        except Exception:
            logger.warning("Error during background task shutdown; continuing exit", exc_info=True)

    async def await_bg_tasks_shutdown(self, timeout: float = 2.0) -> None:
        """Await completion of the model-refresh background task after cancellation."""
        task = self._bg_refresh_task
        if task is None or task.done():
            return
        # Best-effort cleanup — errors inside the task are already logged.
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    @contextlib.asynccontextmanager
    async def _env(self) -> AsyncGenerator[None]:
        original_cwd = KaosPath.cwd()
        await kaos.chdir(self._runtime.session.work_dir)
        try:
            # to ignore possible warnings from dateparser
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            async with self._runtime.oauth.refreshing(self._runtime):
                yield
        finally:
            await kaos.chdir(original_cwd)

    async def run(
        self,
        user_input: str | list[ContentPart],
        cancel_event: asyncio.Event,
        merge_wire_messages: bool = False,
    ) -> AsyncGenerator[WireMessage]:
        """
        Run the Consilium CLI instance without any UI and yield Wire messages directly.

        Args:
            user_input (str | list[ContentPart]): The user input to the agent.
            cancel_event (asyncio.Event): An event to cancel the run.
            merge_wire_messages (bool): Whether to merge Wire messages as much as possible.

        Yields:
            WireMessage: The Wire messages from the `ConsiliumSoul`.

        Raises:
            LLMNotSet: When the LLM is not set.
            LLMNotSupported: When the LLM does not have required capabilities.
            ChatProviderError: When the LLM provider returns an error.
            MaxStepsReached: When the maximum number of steps is reached.
            RunCancelled: When the run is cancelled by the cancel event.
        """
        async with self._env():
            wire_future = asyncio.Future[WireUISide]()
            stop_ui_loop = asyncio.Event()
            approval_bridge_tasks: dict[str, asyncio.Task[None]] = {}
            forwarded_approval_requests: dict[str, ApprovalRequest] = {}

            async def _bridge_approval_request(request: ApprovalRequest) -> None:
                try:
                    response = await request.wait()
                    assert self._runtime.approval_runtime is not None
                    self._runtime.approval_runtime.resolve(
                        request.id, response, feedback=request.feedback
                    )
                finally:
                    approval_bridge_tasks.pop(request.id, None)
                    forwarded_approval_requests.pop(request.id, None)

            def _forward_approval_request(wire: Wire, request: ApprovalRequest) -> None:
                if request.id in forwarded_approval_requests:
                    return
                forwarded_approval_requests[request.id] = request
                if request.id not in approval_bridge_tasks:
                    approval_bridge_tasks[request.id] = asyncio.create_task(
                        _bridge_approval_request(request)
                    )
                wire.soul_side.send(request)

            async def _ui_loop_fn(wire: Wire) -> None:
                wire_future.set_result(wire.ui_side(merge=merge_wire_messages))
                assert self._runtime.root_wire_hub is not None
                assert self._runtime.approval_runtime is not None
                root_hub_queue = self._runtime.root_wire_hub.subscribe()
                stop_task = asyncio.create_task(stop_ui_loop.wait())
                queue_task = asyncio.create_task(root_hub_queue.get())
                try:
                    for pending in self._runtime.approval_runtime.list_pending():
                        _forward_approval_request(
                            wire,
                            ApprovalRequest(
                                id=pending.id,
                                tool_call_id=pending.tool_call_id,
                                sender=pending.sender,
                                action=pending.action,
                                description=pending.description,
                                display=pending.display,
                                source_kind=pending.source.kind,
                                source_id=pending.source.id,
                                agent_id=pending.source.agent_id,
                                subagent_type=pending.source.subagent_type,
                            ),
                        )
                    while True:
                        done, _ = await asyncio.wait(
                            [stop_task, queue_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop_task in done:
                            break
                        try:
                            msg = queue_task.result()
                        except QueueShutDown:
                            break
                        match msg:
                            case ApprovalRequest() as request:
                                _forward_approval_request(wire, request)
                                queue_task = asyncio.create_task(root_hub_queue.get())
                                continue
                            case ApprovalResponse() as response:
                                if (
                                    request := forwarded_approval_requests.get(response.request_id)
                                ) and not request.resolved:
                                    request.resolve(response.response, response.feedback)
                            case _:
                                pass
                        wire.soul_side.send(msg)
                        queue_task = asyncio.create_task(root_hub_queue.get())
                finally:
                    stop_task.cancel()
                    queue_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stop_task
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue_task
                    for task in list(approval_bridge_tasks.values()):
                        task.cancel()
                    for task in list(approval_bridge_tasks.values()):
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                    approval_bridge_tasks.clear()
                    forwarded_approval_requests.clear()
                    assert self._runtime.root_wire_hub is not None
                    self._runtime.root_wire_hub.unsubscribe(root_hub_queue)

            run_cancel_event = asyncio.Event()

            async def _mirror_external_cancel() -> None:
                await cancel_event.wait()
                run_cancel_event.set()

            external_cancel_task = asyncio.create_task(
                _mirror_external_cancel(),
                name="cancel-event-mirror",
            )
            soul_task = asyncio.create_task(
                run_soul(
                    self.soul,
                    user_input,
                    _ui_loop_fn,
                    run_cancel_event,
                    self._runtime.session.wire_file if self._runtime else None,
                    runtime=self._runtime,
                )
            )

            wire_shut_down = False
            try:
                wire_ui = await wire_future
                while True:
                    msg = await wire_ui.receive()
                    yield msg
            except QueueShutDown:
                wire_shut_down = True
                pass
            finally:
                # stop consuming Wire messages
                stop_ui_loop.set()
                cleanup_cancelled_run = False
                if not wire_shut_down and not soul_task.done() and not cancel_event.is_set():
                    cleanup_cancelled_run = True
                    run_cancel_event.set()
                # wait for the soul task to finish, or raise
                try:
                    await soul_task
                except RunCancelled:
                    if not cleanup_cancelled_run:
                        raise
                finally:
                    external_cancel_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await external_cancel_task

    async def run_shell(
        self, command: str | None = None, *, prefill_text: str | None = None
    ) -> bool:
        """Run the Consilium CLI instance with shell UI."""
        from consilium.ui.shell import Shell, WelcomeInfoItem

        if command is None:
            from consilium.ui.shell.update import check_update_gate

            check_update_gate()

        welcome_info = [
            WelcomeInfoItem(
                name="Directory", value=str(shorten_home(self._runtime.session.work_dir))
            ),
            WelcomeInfoItem(name="Session", value=self._runtime.session.id),
        ]
        if base_url := self._env_overrides.get("CONSILIUM_BASE_URL"):
            welcome_info.append(
                WelcomeInfoItem(
                    name="API URL",
                    value=f"{base_url} (from CONSILIUM_BASE_URL)",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        if self._env_overrides.get("CONSILIUM_API_KEY"):
            welcome_info.append(
                WelcomeInfoItem(
                    name="API Key",
                    value="****** (from CONSILIUM_API_KEY)",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        if not self._runtime.llm:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value="not set, send /login to login",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        elif "CONSILIUM_MODEL_NAME" in self._env_overrides:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value=f"{self._soul.model_name} (from CONSILIUM_MODEL_NAME)",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        else:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value=model_display_name(
                        self._soul.model_name,
                        self._runtime.llm.model_config if self._runtime.llm else None,
                    ),
                    level=WelcomeInfoItem.Level.INFO,
                )
            )
            model_name = self._soul.model_name
            if model_name not in (
                "kimi-for-coding",
                "kimi-code",
            ) and not model_name.startswith("kimi-k2"):
                welcome_info.append(
                    WelcomeInfoItem(
                        name="Tip",
                        value="send /login to use Kimi for Coding",
                        level=WelcomeInfoItem.Level.WARN,
                    )
                )
        welcome_info.append(
            WelcomeInfoItem(
                name="\nTip",
                value=(
                    "Spot a bug or have feedback? Type /feedback right in this session"
                    " — every report makes Kimi better."
                ),
                level=WelcomeInfoItem.Level.INFO,
            )
        )
        async with self._env():
            shell = Shell(self._soul, welcome_info=welcome_info, prefill_text=prefill_text)
            return await shell.run(command)

    async def run_print(
        self,
        input_format: InputFormat,
        output_format: OutputFormat,
        command: str | None = None,
        *,
        final_only: bool = False,
    ) -> int:
        """Run the Consilium CLI instance with print UI."""
        from consilium.ui.print import Print

        async with self._env():
            print_ = Print(
                self._soul,
                input_format,
                output_format,
                self._runtime.session.context_file,
                final_only=final_only,
            )
            return await print_.run(command)

    async def run_acp(self) -> None:
        """Run the Consilium CLI instance as ACP server."""
        from consilium.ui.acp import ACP

        async with self._env():
            acp = ACP(self._soul)
            await acp.run()

    async def run_wire_stdio(self) -> None:
        """Run the Consilium CLI instance as Wire server over stdio."""
        from consilium.wire.server import WireServer

        async with self._env():
            mode = "do" if self._do_mode else "think"
            if mode == "think":
                # Think tab is designed as a stateless reasoning agent. Use ThinkSoul
                # instead of ConsiliumSoul so it only exposes the spawn_subagent tool.
                think_soul, _ = await create_think_soul(
                    self.session,
                    config=self._runtime.config,
                    model_name=self._runtime.llm.model_name,
                    thinking=None,
                    generation_overrides={},
                    budget_tokens=self._runtime.config.budget_tokens,
                    agent_file=self._agent_file,
                    subagent_role_overrides=self._subagent_role_overrides,
                    yolo=self._yolo,
                )
                server = WireServer(think_soul, session=self.session, mode=mode)
            else:
                server = WireServer(self._soul, session=self.session, mode=mode)
            await server.serve()
