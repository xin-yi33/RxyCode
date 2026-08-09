"""Built-in agent registration.

B13 · Loads the default agents from ``config/agents/`` and registers them
as non-overridable built-ins. Provides the standard registry used by
``init_manager`` at bootstrap.
"""

from __future__ import annotations

from pathlib import Path

from .definitions import AgentDefinitionRegistry, load_agent_definitions

# Default built-in agent directory (repo-relative)
_DEFAULT_BUILTIN_DIR = (
    Path(__file__).resolve().parent.parent.parent / "config" / "agents"
)


def load_builtin_agents(
    registry: AgentDefinitionRegistry | None = None,
    builtin_dir: str | None = None,
) -> AgentDefinitionRegistry:
    """Load built-in agents into a registry (or a fresh one).

    Args:
        registry: Existing registry to populate.
        builtin_dir: Override the built-in directory (defaults to
                     ``config/agents``).

    Returns:
        The populated registry.
    """
    # `or` would be wrong: an empty registry is falsy (__len__).
    reg = registry if registry is not None else AgentDefinitionRegistry()
    load_agent_definitions(
        builtin_dir=builtin_dir or str(_DEFAULT_BUILTIN_DIR),
        registry=reg,
    )
    return reg


def builtin_agent_ids() -> list[str]:
    """Return the ids of the default built-in agents."""
    reg = load_builtin_agents()
    return sorted(a.id for a in reg.list_all())
