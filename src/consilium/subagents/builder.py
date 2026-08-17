from __future__ import annotations

from consilium.config import Config
from consilium.llm import clone_llm_with_model_alias
from consilium.soul.agent import Agent, Runtime, load_agent
from consilium.subagent_config import build_subagent_config, resolve_subagent_config
from consilium.subagents.models import AgentLaunchSpec, AgentTypeDefinition


def _default_temperature_for_model(config: Config, model_alias: str | None) -> float:
    """Return the effective model's configured temperature, or a sensible fallback."""
    if model_alias is None:
        return 0.7
    model = config.models.get(model_alias)
    if (
        model is not None
        and model.generation is not None
        and model.generation.temperature is not None
    ):
        return model.generation.temperature
    return 0.7


class SubagentBuilder:
    def __init__(self, root_runtime: Runtime):
        self._root_runtime = root_runtime

    async def build_builtin_instance(
        self,
        *,
        agent_id: str,
        type_def: AgentTypeDefinition,
        launch_spec: AgentLaunchSpec,
    ) -> Agent:
        agent_type = type_def.name
        effective_model = self.resolve_effective_model(type_def=type_def, launch_spec=launch_spec)

        # Resolve per-subagent temperature/budget overrides.
        cli_override = self._root_runtime.subagent_overrides.get(agent_type)
        resolved = resolve_subagent_config(
            agent_type,
            self._root_runtime.config,
            cli_overrides=cli_override,
            default_temperature=_default_temperature_for_model(
                self._root_runtime.config, effective_model
            ),
        )
        subagent_config = build_subagent_config(
            self._root_runtime.config,
            agent_type,
            effective_model,
            resolved,
        )

        llm_override = clone_llm_with_model_alias(
            self._root_runtime.llm,
            subagent_config,
            effective_model,
            session_id=self._root_runtime.session.id,
            oauth=self._root_runtime.oauth,
            subagent_id=agent_id,
        )
        runtime = self._root_runtime.copy_for_subagent(
            agent_id=agent_id,
            subagent_type=agent_type,
            llm_override=llm_override,
            config=subagent_config,
        )
        return await load_agent(
            type_def.agent_file,
            runtime,
            mcp_configs=[],
        )

    @staticmethod
    def resolve_effective_model(
        *, type_def: AgentTypeDefinition, launch_spec: AgentLaunchSpec
    ) -> str | None:
        return launch_spec.model_override or launch_spec.effective_model or type_def.default_model
