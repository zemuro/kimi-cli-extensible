"""Per-subagent temperature and budget override resolution."""

from __future__ import annotations

import os

from consilium.config import (
    Config,
    GenerationConfig,
    ResolvedSubagentConfig,
    SubagentOverrideConfig,
)
from consilium.utils.logging import logger


def _read_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _read_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _env_name(agent_type: str, field: str, prefix: str) -> str:
    return f"{prefix}_{agent_type.upper()}_{field.upper()}"


def _clamp_temperature(value: float) -> float:
    if value < 0.0 or value > 2.0:
        logger.warning(
            "Subagent temperature {value} out of range; clamping to [0.0, 2.0]",
            value=value,
        )
        return max(0.0, min(2.0, value))
    return value


def resolve_subagent_config(
    agent_type: str,
    config: Config,
    *,
    cli_overrides: SubagentOverrideConfig | None = None,
    default_temperature: float = 0.7,
    env_prefix: str = "CONSILIUM_SUBAGENT",
) -> ResolvedSubagentConfig:
    """Resolve per-subagent runtime configuration.

    Resolution order for each field:
      1. ``cli_overrides.<field>`` if explicitly provided.
      2. Environment variable ``<PREFIX>_<TYPE>_<FIELD>`` if parseable.
      3. ``config.subagents.overrides[agent_type].<field>`` if present.
      4. Global default.

    Temperature is clamped to [0.0, 2.0] with a warning.
    """
    file_overrides = config.subagents.overrides.get(agent_type)
    budget = config.subagents.budget

    def _resolve_int(field: str, cli: int | None, file: int | None, default: int) -> int:
        if cli is not None:
            return cli
        env = _read_int(os.environ.get(_env_name(agent_type, field, env_prefix), ""))
        if env is not None:
            return env
        if file is not None:
            return file
        return default

    def _resolve_float(field: str, cli: float | None, file: float | None, default: float) -> float:
        if cli is not None:
            return cli
        env = _read_float(os.environ.get(_env_name(agent_type, field, env_prefix), ""))
        if env is not None:
            return env
        if file is not None:
            return file
        return default

    resolved_temperature = _resolve_float(
        "temperature",
        cli_overrides.temperature if cli_overrides is not None else None,
        file_overrides.temperature if file_overrides is not None else None,
        default_temperature,
    )
    resolved_max_tokens = _resolve_int(
        "max_tokens_per_task",
        cli_overrides.max_tokens_per_task if cli_overrides is not None else None,
        file_overrides.max_tokens_per_task if file_overrides is not None else None,
        budget.max_tokens_per_task,
    )
    resolved_max_tools = _resolve_int(
        "max_tool_calls_per_task",
        cli_overrides.max_tool_calls_per_task if cli_overrides is not None else None,
        file_overrides.max_tool_calls_per_task if file_overrides is not None else None,
        budget.max_tool_calls_per_task,
    )
    resolved_timeout = _resolve_int(
        "timeout_seconds",
        cli_overrides.timeout_seconds if cli_overrides is not None else None,
        file_overrides.timeout_seconds if file_overrides is not None else None,
        config.subagents.timeout_seconds,
    )

    return ResolvedSubagentConfig(
        temperature=_clamp_temperature(resolved_temperature),
        max_tokens_per_task=max(1, resolved_max_tokens),
        max_tool_calls_per_task=max(1, resolved_max_tools),
        timeout_seconds=max(10, resolved_timeout),
    )


def _get_or_create_generation(
    model_generation: GenerationConfig | None,
    temperature: float,
) -> GenerationConfig:
    """Clone a model's GenerationConfig, setting temperature."""
    if model_generation is None:
        return GenerationConfig(temperature=temperature)
    return model_generation.model_copy(update={"temperature": temperature}, deep=True)


def build_subagent_config(
    root_config: Config,
    agent_type: str,
    model_alias: str | None,
    resolved: ResolvedSubagentConfig,
) -> Config:
    """Create an isolated Config for a subagent runtime.

    The returned config has:
      - The effective model's ``GenerationConfig`` cloned with the resolved temperature.
      - ``SubagentBudgetConfig`` cloned with the resolved token/tool limits.
      - ``SubagentsConfig.timeout_seconds`` set to the resolved timeout.

    The root config is never mutated.
    """
    # Deep clone so nested mutations are isolated from the parent runtime.
    subagent_config = root_config.model_copy(deep=True)

    # Apply temperature to the effective model's GenerationConfig.
    if model_alias is not None and model_alias in subagent_config.models:
        model = subagent_config.models[model_alias]
        new_generation = _get_or_create_generation(model.generation, resolved.temperature)
        subagent_config.models[model_alias] = model.model_copy(
            update={"generation": new_generation}, deep=True
        )

    # Apply budget and timeout overrides.
    new_budget = subagent_config.subagents.budget.model_copy(
        update={
            "max_tokens_per_task": resolved.max_tokens_per_task,
            "max_tool_calls_per_task": resolved.max_tool_calls_per_task,
        },
        deep=True,
    )
    new_subagents = subagent_config.subagents.model_copy(
        update={
            "budget": new_budget,
            "timeout_seconds": resolved.timeout_seconds,
        },
        deep=True,
    )
    subagent_config = subagent_config.model_copy(
        update={"subagents": new_subagents}, deep=True
    )

    logger.debug(
        "Subagent {agent_type} resolved config: temperature={temperature}, "
        "max_tokens={max_tokens}, max_tools={max_tools}, timeout={timeout}",
        agent_type=agent_type,
        temperature=resolved.temperature,
        max_tokens=resolved.max_tokens_per_task,
        max_tools=resolved.max_tool_calls_per_task,
        timeout=resolved.timeout_seconds,
    )

    return subagent_config
