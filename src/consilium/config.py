from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import tomlkit
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_serializer,
    model_validator,
)
from tomlkit.exceptions import TOMLKitError

from consilium.exception import ConfigError
from consilium.hooks.config import HookDef
from consilium.llm import ModelCapability, ProviderType
from consilium.share import get_share_dir
from consilium.utils.logging import logger


class GenerationConfig(BaseModel):
    """Per-model generation parameters forwarded to the LLM API.

    Not all parameters are supported by every provider. Parameters that a
    provider does not recognise are silently omitted from the request. See the
    description on each field for provider compatibility.
    """

    # ── Common: supported by all providers ──
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. 0 = deterministic, higher = more random. Supported by all providers.",
    )
    top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling: only consider tokens comprising the top P probability mass. Supported by all providers.",
    )

    # ── OpenAI Chat Completions, Kimi, Anthropic ──
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of tokens to generate. Supported by: kimi, openai_legacy, anthropic. For openai_responses and gemini, use `max_output_tokens` instead.",
    )
    n: int | None = Field(
        default=None,
        ge=1,
        description="How many completions to generate for each prompt. Supported by: kimi, openai_legacy.",
    )
    presence_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Penalty for tokens already present in the generated text. Supported by: kimi, openai_legacy.",
    )
    frequency_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Penalty based on how frequently a token has appeared. Supported by: kimi, openai_legacy.",
    )
    stop: str | list[str] | None = Field(
        default=None,
        description="Stop sequence(s) that halt generation. Supported by: kimi, openai_legacy.",
    )

    # ── OpenAI Responses & Gemini ──
    max_output_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Maximum output tokens. For OpenAI Responses and Gemini. If unset, `max_tokens` is used as a fallback for those providers.",
    )

    # ── OpenAI Responses only ──
    max_tool_calls: int | None = Field(
        default=None,
        ge=1,
        description="Maximum tool calls in a single response. Supported by: openai_responses.",
    )
    top_logprobs: float | None = Field(
        default=None,
        description="Number of most likely tokens to return logprobs for. Supported by: openai_responses.",
    )
    user: str | None = Field(
        default=None,
        description="End-user identifier for tracking/auditing. Supported by: openai_responses.",
    )

    # ── Anthropic & Gemini ──
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Top-k sampling: only sample from the K most likely tokens. Supported by: anthropic, gemini.",
    )

    # ── Anthropic only ──
    tool_choice: dict[str, Any] | None = Field(
        default=None,
        description="Tool choice configuration, e.g. {type: 'auto'}. Supported by: anthropic.",
    )
    extra_headers: dict[str, str] | None = Field(
        default=None,
        description="Extra HTTP headers merged with provider-level custom_headers. Supported by: anthropic.",
    )


class OAuthRef(BaseModel):
    """Reference to OAuth credentials stored outside the config file."""

    storage: Literal["keyring", "file"] = "file"
    """Credential storage backend."""
    key: str
    """Storage key to locate OAuth credentials."""


class LLMProvider(BaseModel):
    """LLM provider configuration."""

    type: ProviderType
    """Provider type"""
    base_url: str
    """API base URL"""
    api_key: SecretStr
    """API key"""
    env: dict[str, str] | None = None
    """Environment variables to set before creating the provider instance"""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests"""
    reasoning_key: str | None = None
    """Message field name carrying reasoning content for OpenAI-compatible APIs.
    Applies to provider type ``openai_legacy``. Defaults to ``reasoning_content``
    when unset. Use an empty string to disable reasoning round-tripping."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class LLMModel(BaseModel):
    """LLM model configuration."""

    provider: str
    """Provider name"""
    model: str
    """Model name"""
    max_context_size: int
    """Maximum context size (unit: tokens)"""
    capabilities: set[ModelCapability] | None = None
    """Model capabilities"""
    display_name: str | None = None
    """Human-readable model name (sourced from the provider's models API when available)"""
    generation: GenerationConfig | None = Field(
        default=None,
        description="Per-model generation parameters forwarded to the LLM API.",
    )


class LoopControl(BaseModel):
    """Agent loop control configuration."""

    max_steps_per_turn: int = Field(
        default=1000,
        ge=1,
        validation_alias=AliasChoices("max_steps_per_turn", "max_steps_per_run"),
    )
    """Maximum number of steps in one turn"""
    max_retries_per_step: int = Field(default=3, ge=1)
    """Maximum number of retries in one step"""
    max_ralph_iterations: int = Field(default=0, ge=-1)
    """Extra iterations after the first turn in Ralph mode. Use -1 for unlimited."""
    reserved_context_size: int = Field(default=100_000, ge=1000)
    """Reserved token count for LLM response generation. Auto-compaction triggers when
    either context_tokens + reserved_context_size >= max_context_size or
    context_tokens >= max_context_size * compaction_trigger_ratio. Default is 100000."""
    compaction_trigger_ratio: float = Field(default=0.85, ge=0.5, le=0.99)
    """Context usage ratio threshold for auto-compaction. Default is 0.85 (85%).
    Auto-compaction triggers when context_tokens >= max_context_size * compaction_trigger_ratio
    or when context_tokens + reserved_context_size >= max_context_size."""
    max_preserved_messages: int = Field(default=10, ge=0, le=50)
    """Number of recent messages to preserve during context compaction.
    Higher values retain more conversation history at the cost of context window space.
    Default is 10. Set to 0 to disable compaction (not recommended)."""


class BackgroundConfig(BaseModel):
    """Background task runtime configuration."""

    max_running_tasks: int = Field(default=8, ge=1)
    read_max_bytes: int = Field(default=30_000, ge=1024)
    notification_tail_lines: int = Field(default=20, ge=1)
    notification_tail_chars: int = Field(default=3_000, ge=256)
    wait_poll_interval_ms: int = Field(default=500, ge=50)
    worker_heartbeat_interval_ms: int = Field(default=5_000, ge=100)
    worker_stale_after_ms: int = Field(default=15_000, ge=1000)
    kill_grace_period_ms: int = Field(default=2_000, ge=100)
    keep_alive_on_exit: bool = Field(
        default=False,
        description="Keep background tasks alive when CLI exits. Default: kill on exit.",
    )
    agent_task_timeout_s: int = Field(default=900, ge=60)
    """Maximum runtime in seconds for a background agent task. Default: 900 (15 min)."""
    print_wait_ceiling_s: int = Field(default=3600, ge=1)
    """Hard ceiling for how long ``--print`` mode waits for background tasks before
    killing them and exiting. The effective wait is
    ``min(max(active_task.timeout_s or agent_task_timeout_s), print_wait_ceiling_s)``.
    Default: 3600 (1 hour)."""


class NotificationConfig(BaseModel):
    """Notification runtime configuration."""

    claim_stale_after_ms: int = Field(default=15_000, ge=1000)


class WebSearchConfig(BaseModel):
    """Web Search configuration."""

    base_url: str
    """Base URL for Web Search service."""
    api_key: SecretStr
    """API key for Web Search service."""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class WebFetchConfig(BaseModel):
    """Web Fetch configuration."""

    base_url: str
    """Base URL for Web Fetch service."""
    api_key: SecretStr
    """API key for Web Fetch service."""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests."""
    oauth: OAuthRef | None = None
    """OAuth credential reference (do not store tokens here)."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class Services(BaseModel):
    """Services configuration."""

    web_search: WebSearchConfig | None = None
    """Web Search configuration."""
    web_fetch: WebFetchConfig | None = None
    """Web Fetch configuration."""


class MCPClientConfig(BaseModel):
    """MCP client configuration."""

    tool_call_timeout_ms: int = 60000
    """Timeout for tool calls in milliseconds."""


class MCPConfig(BaseModel):
    """MCP configuration."""

    client: MCPClientConfig = Field(
        default_factory=MCPClientConfig, description="MCP client configuration"
    )


class PythonConfig(BaseModel):
    """Configuration for Python execution in Think mode."""

    restriction_level: Literal["none", "restricted", "sandboxed"] = Field(
        default="restricted",
        description="Sandbox level for Python execution",
    )
    allow_network: bool = Field(default=False)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_memory_mb: int = Field(default=512, ge=64)
    auto_approve: bool = Field(default=False)


class ThinkConfig(BaseModel):
    """Think mode configuration."""

    default_temperature: float = Field(
        default=0.6, ge=0.0, le=2.0, description="Default temperature for Think mode"
    )
    max_context_tokens: int = Field(
        default=200_000, ge=1000, description="Maximum context tokens for Think mode"
    )
    enable_checkpoints: bool = Field(
        default=True, description="Enable checkpoint save/restore in Think mode"
    )
    python: PythonConfig = Field(default_factory=PythonConfig)
    compaction_enabled: bool = Field(
        default=True, description="Enable context compaction warnings and /compact command"
    )
    compaction_threshold: float = Field(
        default=0.85, ge=0.1, le=0.99, description="Context usage ratio to warn at"
    )
    compaction_preserve_messages: int = Field(
        default=6, ge=1, le=50, description="Messages to preserve during compaction"
    )


class SubagentOverrideConfig(BaseModel):
    """Optional per-subagent override for temperature and budget limits.

    All fields are optional; absence means "fall back to the next resolution
    level" (CLI flag / env var / global default).
    """

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature override for this subagent type",
    )
    max_tokens_per_task: int | None = Field(
        default=None,
        ge=1_000,
        description="Hard token limit override for this subagent type",
    )
    max_tool_calls_per_task: int | None = Field(
        default=None,
        ge=1,
        description="Hard tool-call limit override for this subagent type",
    )
    timeout_seconds: int | None = Field(
        default=None,
        ge=10,
        le=3600,
        description="Timeout override in seconds for this subagent type",
    )


class SubagentBudgetConfig(BaseModel):
    """Token and tool-call budget limits for subagent tasks."""

    max_tokens_per_task: int = Field(
        default=80_000, ge=1_000, description="Hard token limit per subagent task"
    )
    max_tool_calls_per_task: int = Field(
        default=100, ge=1, description="Hard tool-call limit per subagent task"
    )
    warn_tokens_ratio: float = Field(
        default=0.8, ge=0.1, le=1.0, description="Warn when token usage exceeds this ratio"
    )
    warn_tool_calls_ratio: float = Field(
        default=0.8, ge=0.1, le=1.0, description="Warn when tool-call usage exceeds this ratio"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedSubagentConfig:
    """Fully resolved per-subagent runtime configuration."""

    temperature: float
    max_tokens_per_task: int
    max_tool_calls_per_task: int
    timeout_seconds: int


class SubagentsConfig(BaseModel):
    """Cross-cutting subagent configuration."""

    enabled: bool = Field(default=True, description="Enable subagent spawning from Think and Do modes")
    timeout_seconds: int = Field(default=900, ge=10, le=3600)
    default_type: str = Field(default="explore", description="Default subagent type for Think mode")
    budget: SubagentBudgetConfig = Field(
        default_factory=SubagentBudgetConfig, description="Subagent budget limits"
    )
    overrides: dict[str, SubagentOverrideConfig] = Field(
        default_factory=dict,
        description="Per-subagent temperature and budget overrides keyed by agent type",
    )

    @model_validator(mode="after")
    def _validate_override_keys(self) -> Self:
        import re

        valid = re.compile(r"^[a-z][a-z0-9_]*$")
        for key in self.overrides:
            if not valid.match(key):
                raise ValueError(
                    f"Invalid subagent override key: {key!r}. "
                    "Keys must be lowercase identifiers."
                )
        return self


class PlanReviewConfig(BaseModel):
    """Nested config for plan review gate."""

    enabled: bool = Field(default=True, description="Enable plan review gate when seeded from Think")
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    model: str | None = Field(default=None, description="Optional model override for review subagent")
    system_prompt_path: Path | None = Field(
        default=None, description="Optional custom system prompt for plan review"
    )


class DoConfig(BaseModel):
    """Do mode configuration."""

    default_temperature: float = Field(
        default=0.3, ge=0.0, le=2.0, description="Default temperature for Do mode"
    )
    auto_git_snapshot: bool = Field(
        default=True, description="Automatically stash uncommitted changes on Do mode start"
    )
    max_iterations: int = Field(
        default=50, ge=1, description="Maximum iterations per turn in Do mode"
    )
    enable_change_journal: bool = Field(
        default=True, description="Record all file-modifying tool calls in the change journal"
    )
    journal_include_diffs: bool = Field(
        default=True, description="Store unified diffs in the journal (increases storage)"
    )
    journal_retention_days: int = Field(
        default=30, ge=0, description="Archive journals older than N days (0 = disable)"
    )
    plan_review: PlanReviewConfig = Field(
        default_factory=PlanReviewConfig, description="Plan review gate configuration"
    )
    enable_reverse_bridge: bool = Field(
        default=True, description="Enable Do mode to push completion/audit reports to Think inbox"
    )


class Config(BaseModel):
    """Main configuration structure."""

    is_from_default_location: bool = Field(
        default=False,
        description="Whether the config was loaded from the default location",
        exclude=True,
    )
    source_file: Path | None = Field(
        default=None,
        description="Path to the loaded config file. None when loaded from --config text.",
        exclude=True,
    )
    default_model: str = Field(default="", description="Default model to use")
    default_thinking: bool = Field(default=False, description="Default thinking mode")
    default_yolo: bool = Field(default=False, description="Default yolo (auto-approve) mode")
    compaction_model: str | None = Field(
        default=None,
        description="Optional override model specifically for compaction. If unset, uses default_model.",
    )
    skip_afk_prompt_injection: bool = Field(
        default=False,
        description=(
            "If true, suppress the afk-mode system reminder. "
            "Yolo mode does not inject a system reminder."
        ),
    )
    default_plan_mode: bool = Field(default=False, description="Default plan mode for new sessions")
    default_editor: str = Field(
        default="",
        description="Default external editor command (e.g. 'vim', 'code --wait')",
    )
    theme: Literal["dark", "light"] = Field(
        default="dark",
        description="Terminal color theme. Use 'light' for light terminal backgrounds.",
    )
    show_thinking_stream: bool = Field(
        default=True,
        description=(
            "If true, stream the raw reasoning text in the live area as a "
            "6-line scrolling preview and commit the full reasoning markdown "
            "to history when the block ends. Default true. Set to false to "
            "show only the compact 'Thinking ...' indicator and a one-line "
            "trace summary."
        ),
    )
    models: dict[str, LLMModel] = Field(default_factory=dict, description="List of LLM models")
    providers: dict[str, LLMProvider] = Field(
        default_factory=dict, description="List of LLM providers"
    )
    loop_control: LoopControl = Field(default_factory=LoopControl, description="Agent loop control")
    background: BackgroundConfig = Field(
        default_factory=BackgroundConfig, description="Background task configuration"
    )
    notifications: NotificationConfig = Field(
        default_factory=NotificationConfig, description="Notification configuration"
    )
    services: Services = Field(default_factory=Services, description="Services configuration")
    mcp: MCPConfig = Field(default_factory=MCPConfig, description="MCP configuration")
    hooks: list[HookDef] = Field(default_factory=list, description="Hook definitions")  # pyright: ignore[reportUnknownVariableType]
    merge_all_available_skills: bool = Field(
        default=True,
        description=(
            "Merge skills from all existing brand directories (kimi/claude/codex) "
            "instead of using only the first one found. Defaults to true so users "
            "who keep skills in multiple brand directories see everything out of "
            "the box; set to false to restore the first-match-only behaviour."
        ),
    )
    extra_skill_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Extra directories to discover skills from, added on top of the "
            "built-in / user / project locations. Each entry may be an absolute "
            "path, ``~``-prefixed (expanded against $HOME), or relative to the "
            "project root (the nearest ``.git`` directory above the work dir). "
            "Missing paths are silently skipped."
        ),
    )
    system_prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Override individual system prompt sections by name. "
            "Keys are section names (e.g. 'identity', 'coding_guidelines') and "
            "values are absolute or ~-prefixed paths to replacement .md files."
        ),
    )
    budget_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Maximum token budget for a session. Warns at 80%, stops at 100%.",
    )
    think: ThinkConfig = Field(
        default_factory=ThinkConfig, description="Think mode configuration"
    )
    do: DoConfig = Field(
        default_factory=DoConfig, description="Do mode configuration"
    )
    subagents: SubagentsConfig = Field(
        default_factory=SubagentsConfig, description="Subagent configuration"
    )
    telemetry: bool = Field(
        default=True,
        description="Enable anonymous telemetry to help improve consilium. Set to false to disable.",
    )

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        # if self.default_model and self.default_model not in self.models:
        #     raise ValueError(f"Default model {self.default_model} not found in models")
        for model in self.models.values():
            if model.provider not in self.providers:
                raise ValueError(f"Provider {model.provider} not found in providers")
        for section_name, path_str in self.system_prompt_overrides.items():
            path = Path(path_str).expanduser()
            if not path.is_file():
                raise ValueError(
                    f"system_prompt_overrides[{section_name!r}] file not found: {path}"
                )
        return self


def get_config_file() -> Path:
    """Get the configuration file path."""
    return get_share_dir() / "config.toml"


def get_default_config() -> Config:
    """Get the default configuration."""
    return Config(
        default_model="",
        models={},
        providers={},
        services=Services(),
    )


def _apply_env_overrides(config: Config) -> None:
    """Apply environment-variable overrides to configurable values.

    Supported variables:
    - CONSILIUM_SUBAGENTS_TIMEOUT_SECONDS
    - CONSILIUM_SUBAGENTS_BUDGET_MAX_TOKENS_PER_TASK
    - CONSILIUM_SUBAGENTS_BUDGET_MAX_TOOL_CALLS_PER_TASK
    - CONSILIUM_DO_AUTO_GIT_SNAPSHOT ("true" or "false")
    """
    import os

    def _read_int(name: str, min_val: int, max_val: int) -> int | None:
        raw = os.environ.get(name)
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError as e:
            raise ConfigError(f"Invalid integer for {name}: {raw!r}") from e
        if not (min_val <= value <= max_val):
            raise ConfigError(
                f"{name}={value} is outside allowed range [{min_val}, {max_val}]"
            )
        return value

    def _read_bool(name: str) -> bool | None:
        raw = os.environ.get(name)
        if raw is None:
            return None
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"Invalid boolean for {name}: {raw!r}")

    value = _read_int("CONSILIUM_SUBAGENTS_TIMEOUT_SECONDS", 10, 3600)
    if value is not None:
        config.subagents.timeout_seconds = value

    value = _read_int("CONSILIUM_SUBAGENTS_BUDGET_MAX_TOKENS_PER_TASK", 1_000, 1_000_000)
    if value is not None:
        config.subagents.budget.max_tokens_per_task = value

    value = _read_int("CONSILIUM_SUBAGENTS_BUDGET_MAX_TOOL_CALLS_PER_TASK", 1, 10_000)
    if value is not None:
        config.subagents.budget.max_tool_calls_per_task = value

    value = _read_bool("CONSILIUM_DO_AUTO_GIT_SNAPSHOT")
    if value is not None:
        config.do.auto_git_snapshot = value


def load_config(config_file: Path | None = None) -> Config:
    """
    Load configuration from config file.
    If the config file does not exist, create it with default configuration.

    Args:
        config_file (Path | None): Path to the configuration file. If None, use default path.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If the configuration file is invalid.
    """
    default_config_file = get_config_file().expanduser().resolve(strict=False)
    if config_file is None:
        config_file = default_config_file
    config_file = config_file.expanduser().resolve(strict=False)
    is_default_config_file = config_file == default_config_file
    logger.debug("Loading config from file: {file}", file=config_file)

    # If the user hasn't provided an explicit config path, migrate legacy JSON config once.
    if is_default_config_file and not config_file.exists():
        _migrate_json_config_to_toml()

    if not config_file.exists():
        config = get_default_config()
        logger.debug("No config file found, creating default config: {config}", config=config)
        save_config(config, config_file)
        config.is_from_default_location = is_default_config_file
        config.source_file = config_file
        return config

    try:
        config_text = config_file.read_text(encoding="utf-8")
        if config_file.suffix.lower() == ".json":
            data = json.loads(config_text)
        else:
            data = tomlkit.loads(config_text)
        config = Config.model_validate(data)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in configuration file {config_file}: {e}") from e
    except TOMLKitError as e:
        raise ConfigError(f"Invalid TOML in configuration file {config_file}: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration file {config_file}: {e}") from e
    config.is_from_default_location = is_default_config_file
    config.source_file = config_file
    _apply_env_overrides(config)
    return config


def load_config_from_string(config_string: str) -> Config:
    """
    Load configuration from a TOML or JSON string.

    Args:
        config_string (str): TOML or JSON configuration text.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If the configuration text is invalid.
    """
    if not config_string.strip():
        raise ConfigError("Configuration text cannot be empty")

    json_error: json.JSONDecodeError | None = None
    try:
        data = json.loads(config_string)
    except json.JSONDecodeError as exc:
        json_error = exc
        data = None

    if data is None:
        try:
            data = tomlkit.loads(config_string)
        except TOMLKitError as toml_error:
            raise ConfigError(
                f"Invalid configuration text: {json_error}; {toml_error}"
            ) from toml_error

    try:
        config = Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration text: {e}") from e
    config.is_from_default_location = False
    config.source_file = None
    _apply_env_overrides(config)
    return config


def save_config(config: Config, config_file: Path | None = None):
    """
    Save configuration to config file.

    Args:
        config (Config): Config object to save.
        config_file (Path | None): Path to the configuration file. If None, use default path.
    """
    config_file = config_file or get_config_file()
    logger.debug("Saving config to file: {file}", file=config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_data = config.model_dump(mode="json", exclude_none=True)
    with open(config_file, "w", encoding="utf-8") as f:
        if config_file.suffix.lower() == ".json":
            f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
        else:
            f.write(tomlkit.dumps(config_data))  # type: ignore[reportUnknownMemberType]


def _migrate_json_config_to_toml() -> None:
    old_json_config_file = get_share_dir() / "config.json"
    new_toml_config_file = get_share_dir() / "config.toml"

    if not old_json_config_file.exists():
        return
    if new_toml_config_file.exists():
        return

    logger.info(
        "Migrating legacy config file from {old} to {new}",
        old=old_json_config_file,
        new=new_toml_config_file,
    )

    try:
        with open(old_json_config_file, encoding="utf-8") as f:
            data = json.load(f)
        config = Config.model_validate(data)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in legacy configuration file: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Invalid legacy configuration file: {e}") from e

    # Write new TOML config, then keep a backup of the original JSON file.
    save_config(config, new_toml_config_file)
    backup_path = old_json_config_file.with_name("config.json.bak")
    old_json_config_file.replace(backup_path)
    logger.info("Legacy config backed up to {file}", file=backup_path)
