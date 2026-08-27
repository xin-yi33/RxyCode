"""Process-wide ChildSessionManager singleton provider.

B7 · Holds the runtime-scoped manager instance. The manager is set once at
app bootstrap and reused by tools, CLI, Desktop, and appserver routes.

This is a single read-mostly provider: it does NOT share mutable state
between child sessions. All per-child state lives in ChildSession/
AgentRuntime.
"""

from __future__ import annotations

from pathlib import Path

from .definitions import AgentDefinitionRegistry
from .manager import ChildSessionManager
from .modes import SubagentConfig, subagent_config_from_env

_manager: ChildSessionManager | None = None


def init_manager(
    registry: AgentDefinitionRegistry | None = None,
    config: SubagentConfig | None = None,
    *,
    manager: ChildSessionManager | None = None,
    load_builtins: bool = True,
    workspace_root: Path | None = None,
) -> ChildSessionManager:
    """Initialize the process-wide manager singleton.

    If *manager* is provided, it is registered directly (tests).
    Otherwise a fresh ChildSessionManager is constructed; when
    ``load_builtins`` is True (default), the default ``config/agents``
    built-ins are registered first.

    Calling this twice replaces the manager (bootstrap/teardown only).
    """
    global _manager
    if manager is not None:
        _manager = manager
        return _manager

    reg = registry
    if reg is None and load_builtins:
        from .builtin_agents import load_builtin_agents
        reg = load_builtin_agents()
    if reg is None:
        reg = AgentDefinitionRegistry()

    _manager = ChildSessionManager(
        registry=reg,
        config=config or subagent_config_from_env(),
        workspace_root=workspace_root,
    )
    return _manager


def get_manager() -> ChildSessionManager:
    """Return the process-wide manager, raising if not initialized."""
    if _manager is None:
        raise RuntimeError(
            "ChildSessionManager not initialized. Call init_manager() at bootstrap."
        )
    return _manager


def get_manager_or_none() -> ChildSessionManager | None:
    """Return the manager, or None if not initialized (for capability checks)."""
    return _manager


def reset_manager() -> None:
    """Clear the manager singleton (test teardown)."""
    global _manager
    _manager = None
