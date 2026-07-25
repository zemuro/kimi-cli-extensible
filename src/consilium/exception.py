from __future__ import annotations


class ConsiliumCLIException(Exception):
    """Base exception class for Consilium."""

    pass


class ConfigError(ConsiliumCLIException, ValueError):
    """Configuration error."""

    pass


class AgentSpecError(ConsiliumCLIException, ValueError):
    """Agent specification error."""

    pass


class InvalidToolError(ConsiliumCLIException, ValueError):
    """Invalid tool error."""

    pass


class SystemPromptTemplateError(ConsiliumCLIException, ValueError):
    """System prompt template error."""

    pass


class MCPConfigError(ConsiliumCLIException, ValueError):
    """MCP config error."""

    pass


class MCPRuntimeError(ConsiliumCLIException, RuntimeError):
    """MCP runtime error."""

    pass
