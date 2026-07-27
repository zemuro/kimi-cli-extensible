from __future__ import annotations

from pathlib import Path

_BUILTIN_SECTIONS_DIR = Path(__file__).parent

DEFAULT_SECTION_ORDER = [
    "identity",
    "prompt_and_tool_use",
    "coding_guidelines",
    "research_guidelines",
    "working_environment",
    "project_info",
    "skills",
    "ultimate_reminders",
]

_ASSEMBLE_MARKER = "<!-- assembled-from-sections -->"


def is_assembled_prompt(text: str) -> bool:
    """Check whether a system prompt text is the assembly marker."""
    return text.strip() == _ASSEMBLE_MARKER


def load_section(name: str, overrides: dict[str, str] | None = None) -> str:
    """Load a single system prompt section.

    Args:
        name: Section name (e.g. "identity").
        overrides: Optional map of section name → override file path.

    Returns:
        Section text.

    Raises:
        FileNotFoundError: If the section file is not found.
    """
    if overrides and name in overrides:
        path = Path(overrides[name]).expanduser().resolve()
    else:
        path = _BUILTIN_SECTIONS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"System prompt section not found: {path} "
            f"(check your system_prompt_overrides config or section file)"
        )
    return path.read_text(encoding="utf-8")


def assemble_system_prompt(overrides: dict[str, str] | None = None) -> str:
    """Assemble the full system prompt from sections.

    Args:
        overrides: Optional map of section name → override file path.

    Returns:
        Assembled system prompt text with one blank line between sections.
    """
    parts: list[str] = []
    for name in DEFAULT_SECTION_ORDER:
        content = load_section(name, overrides=overrides).rstrip("\n")
        if content:
            parts.append(content)
    return "\n\n".join(parts)
