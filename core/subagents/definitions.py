"""AgentDefinition loading, validation, and registry.

Handles static validation of AgentDefinition fields and maintains the
singleton registry used by ChildSessionManager at runtime.
"""

from __future__ import annotations

import re

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    PermissionSpec,
    TaskPermissionSpec,
    WorkspaceMode,
)

from .config_loader import (
    ConfigLoadError,
    AgentDefDict,
    load_agent_from_json,
    load_agent_from_markdown,
    load_agent_from_yaml,
    normalize_raw_config,
)

# ---------------------------------------------------------------------------
# Reserved agent ids that cannot be overridden by user definitions
# ---------------------------------------------------------------------------

RESERVED_IDS: frozenset[str] = frozenset({"primary", "system", "root", "admin"})

# Valid agent id pattern: lowercase alphanumeric, hyphens, underscores
_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class DefinitionError(ValueError):
    """Raised when an AgentDefinition fails static validation."""

    def __init__(self, message: str, *, field: str = "", agent_id: str = ""):
        super().__init__(message)
        self.field = field
        self.agent_id = agent_id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_agent_definition(raw: AgentDefDict) -> AgentDefinition:
    """Validate and build an immutable AgentDefinition from a normalized dict.

    Raises DefinitionError with field/agent_id context on failure.
    """

    agent_id = raw.get("id", "")
    if not agent_id:
        raise DefinitionError("Agent id is required", field="id")

    # -- id validation -------------------------------------------------------

    if not _AGENT_ID_RE.match(agent_id):
        raise DefinitionError(
            f"Agent id '{agent_id}' must match pattern: lowercase start, "
            f"alphanumeric/hyphen/underscore, max 64 chars",
            field="id",
            agent_id=agent_id,
        )

    if agent_id in RESERVED_IDS:
        raise DefinitionError(
            f"Agent id '{agent_id}' is reserved and cannot be used",
            field="id",
            agent_id=agent_id,
        )

    # -- description ---------------------------------------------------------

    description = raw.get("description", "")
    if not description or not description.strip():
        raise DefinitionError(
            "Agent description is required",
            field="description",
            agent_id=agent_id,
        )

    # -- mode ----------------------------------------------------------------

    mode_str = raw.get("mode", "subagent")
    try:
        mode = AgentMode(mode_str)
    except ValueError as exc:
        raise DefinitionError(
            f"Invalid mode '{mode_str}'; must be one of: primary, subagent, all",
            field="mode",
            agent_id=agent_id,
        ) from exc

    # -- steps ---------------------------------------------------------------

    steps = raw.get("steps")
    if steps is not None:
        if not isinstance(steps, int) or steps < 1:
            raise DefinitionError(
                f"steps must be a positive integer, got {steps!r}",
                field="steps",
                agent_id=agent_id,
            )

    # -- subagent_depth ------------------------------------------------------

    subagent_depth = raw.get("subagent_depth", 1)
    if not isinstance(subagent_depth, int) or subagent_depth < 0:
        raise DefinitionError(
            f"subagent_depth must be a non-negative integer, got {subagent_depth!r}",
            field="subagent_depth",
            agent_id=agent_id,
        )

    # -- workspace_scope -----------------------------------------------------

    workspace_str = raw.get("workspace_scope", "read_only")
    try:
        workspace_scope = WorkspaceMode(workspace_str)
    except ValueError as exc:
        raise DefinitionError(
            f"Invalid workspace_scope '{workspace_str}'; "
            f"must be one of: read_only, leased_write, isolated_worktree",
            field="workspace_scope",
            agent_id=agent_id,
        ) from exc

    # -- permission ----------------------------------------------------------

    permission_raw = raw.get("permission")
    permission = PermissionSpec.from_raw(permission_raw)

    # -- task_permission — MUST only come from permission.task ----------------

    # Detect if the raw config has a top-level "task_permission" key
    if "task_permission" in raw:
        raise DefinitionError(
            "Top-level 'task_permission' is not allowed. "
            "Task permissions must be defined under 'permission.task'.",
            field="task_permission",
            agent_id=agent_id,
        )

    task_permission = TaskPermissionSpec.from_raw(
        permission_raw.get("task") if permission_raw else None
    )

    # -- hidden --------------------------------------------------------------

    hidden = bool(raw.get("hidden", False))

    # -- prompt / model ------------------------------------------------------

    prompt = raw.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise DefinitionError(
            f"prompt must be a string or null, got {type(prompt).__name__}",
            field="prompt",
            agent_id=agent_id,
        )

    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        raise DefinitionError(
            f"model must be a string or null, got {type(model).__name__}",
            field="model",
            agent_id=agent_id,
        )

    # -- extra ---------------------------------------------------------------

    extra = {
        k: v for k, v in raw.items()
        if k not in {
            "id", "description", "mode", "prompt", "model", "steps",
            "permission", "hidden", "subagent_depth", "workspace_scope",
            "task_permission",
        }
    }

    return AgentDefinition(
        id=agent_id,
        description=description,
        mode=mode,
        prompt=prompt,
        model=model,
        steps=steps,
        permission=permission,
        task_permission=task_permission,
        hidden=hidden,
        subagent_depth=subagent_depth,
        workspace_scope=workspace_scope,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class AgentDefinitionRegistry:
    """Thread-safe registry of validated AgentDefinitions.

    Built-in agents are registered first and CANNOT be overridden by
    user-space definitions. System hard-reject rules always take precedence
    over agent-level permissions.
    """

    def __init__(self):
        self._agents: dict[str, AgentDefinition] = {}
        self._builtin_ids: set[str] = set()

    # -- registration --------------------------------------------------------

    def register(self, definition: AgentDefinition, *, builtin: bool = False) -> None:
        """Register an agent definition.

        Args:
            definition: Validated AgentDefinition.
            builtin: If True, marks this as a system built-in that cannot be
                     overridden by user definitions.

        Raises:
            DefinitionError: If a user definition tries to override a builtin,
                             or if a duplicate non-builtin id is registered.
        """
        if definition.id in self._builtin_ids:
            if not builtin:
                raise DefinitionError(
                    f"Cannot override built-in agent '{definition.id}'",
                    agent_id=definition.id,
                )
            # Re-registering the same builtin is a no-op
            return

        if builtin:
            self._builtin_ids.add(definition.id)

        self._agents[definition.id] = definition

    def register_builtin(self, definition: AgentDefinition) -> None:
        """Register a built-in agent (shortcut)."""
        self.register(definition, builtin=True)

    def register_user(self, definition: AgentDefinition) -> None:
        """Register a user-defined agent."""
        self.register(definition, builtin=False)

    # -- lookup --------------------------------------------------------------

    def get(self, agent_id: str) -> AgentDefinition | None:
        """Return the agent definition, or None if not found."""
        return self._agents.get(agent_id)

    def list_visible(self) -> list[AgentDefinition]:
        """Return agents visible in @ autocomplete (not hidden, subagent-capable)."""
        return [
            a for a in self._agents.values()
            if a.is_subagent_capable and not a.hidden
        ]

    def list_all(self) -> list[AgentDefinition]:
        """Return all registered agents."""
        return list(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def __iter__(self):
        return iter(self._agents.values())


# ---------------------------------------------------------------------------
# High-level loader
# ---------------------------------------------------------------------------

def load_agent_definitions(
    builtin_dir: str | None = None,
    user_dir: str | None = None,
    *,
    registry: AgentDefinitionRegistry | None = None,
) -> AgentDefinitionRegistry:
    """Load built-in and user agent definitions into a registry.

    Args:
        builtin_dir: Directory containing built-in .json / .md / .yaml agent defs.
        user_dir: Directory containing user .json / .md / .yaml agent defs.
        registry: Optional existing registry to populate.

    Returns:
        Populated AgentDefinitionRegistry.
    """

    # NOTE: `registry or AgentDefinitionRegistry()` is WRONG here — an empty
    # registry is falsy (it defines __len__), which would silently replace a
    # caller-provided empty registry with a fresh one.
    reg = registry if registry is not None else AgentDefinitionRegistry()

    _load_from_directory(reg, builtin_dir, builtin=True)
    _load_from_directory(reg, user_dir, builtin=False)

    return reg


def _load_from_directory(
    registry: AgentDefinitionRegistry,
    directory: str | None,
    *,
    builtin: bool,
) -> None:
    """Load all agent definition files from a directory."""
    from pathlib import Path

    if directory is None:
        return

    dir_path = Path(directory)
    if not dir_path.is_dir():
        return

    for file_path in sorted(dir_path.iterdir()):
        suffix = file_path.suffix.lower()
        if suffix not in (".json", ".md", ".yaml", ".yml"):
            continue

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigLoadError(
                f"Cannot read agent definition file: {file_path}: {exc}",
                path=str(file_path),
            ) from exc

        try:
            if suffix == ".json":
                raw = load_agent_from_json(raw_text)
            elif suffix in (".yaml", ".yml"):
                raw = load_agent_from_yaml(raw_text)
            else:
                raw = load_agent_from_markdown(raw_text)
        except ConfigLoadError:
            raise
        except Exception as exc:
            raise ConfigLoadError(
                f"Failed to parse agent definition: {file_path}: {exc}",
                path=str(file_path),
            ) from exc

        normalized = normalize_raw_config(raw)
        definition = validate_agent_definition(normalized)

        if builtin:
            registry.register_builtin(definition)
        else:
            registry.register_user(definition)
