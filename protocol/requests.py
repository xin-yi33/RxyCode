"""Client -> server JSON-RPC requests."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .types import JsonObject


class InitializeRequest(BaseModel):
    """JSON-RPC handshake on connect (future ``python -m appserver``).

    ``client_name`` / ``client_version`` identify the OpenTUI or Desktop client;
    ``protocol_version`` must fall in ``PROTOCOL_VERSION_MIN``..``MAX`` (empty
    is unspecified/legacy); unknown extra fields are ignored.
    ``capabilities`` is an optional client feature manifest (unused in HTTP mode).
    ``client_info`` / ``client_capabilities`` / ``requested_features`` are
    PhaseG-B2 optional fields (G §5.1); they do not replace the older keys.
    """

    method: Literal["initialize"] = "initialize"
    client_name: str
    client_version: str
    protocol_version: str
    capabilities: JsonObject | None = None
    client_info: JsonObject | None = None
    client_capabilities: JsonObject | None = None
    requested_features: list[str] | None = None


class NewSessionRequest(BaseModel):
    """Bind a workspace and chat namespace (maps ``_activate_session`` in api_server.py).

    ``workspace_root`` is the repo root passed to AgentV2 tools (today ``Path.cwd()``);
    ``model`` optionally overrides the default from ``config/settings.py``.
    """

    method: Literal["session/new"] = "session/new"
    workspace_root: str
    model: str | None = None


class PromptRequest(BaseModel):
    """One user turn (maps ``POST /chat`` ``ChatRequest`` in api_server.py).

    ``session_id`` uses ``memory.long_term.validate_session_id``; ``text`` is
    ``ChatRequest.message``; ``timeout_seconds`` mirrors execution tool timeout
    semantics when appserver enforces wall-clock limits.
    ``mode`` selects AgentV2 run mode; ``thinking_expanded`` gates reasoning
    stream emission on ``ProtocolTui``.
    """

    method: Literal["session/prompt"] = "session/prompt"
    session_id: str
    text: str
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional wall-clock limit for this prompt (maps execution.tool_timeout_seconds semantics).",
    )
    mode: str | None = Field(
        default=None,
        description="Agent run mode (build/plan/compose); defaults to build.",
    )
    thinking_expanded: bool | None = Field(
        default=None,
        description="When true, ProtocolTui emits event/reasoning_snapshot chunks.",
    )


class InterruptRequest(BaseModel):
    """Cancel the in-flight run (maps ``POST /cancel`` + ``Session.interrupt`` in api_server.py).

    ``session_id`` matches the active ``ChatRequest.session_id`` namespace.
    """

    method: Literal["session/interrupt"] = "session/interrupt"
    session_id: str


class SetThinkingExpandedRequest(BaseModel):
    """Sync OpenTUI /thinking expand state into appserver ProtocolTui.

    ``expanded`` mirrors the client Thought panel; when a prompt is in flight the
    bound worker TUI is updated so mid-run expand can push an accumulated snapshot.
    """

    method: Literal["session/set_thinking_expanded"] = "session/set_thinking_expanded"
    session_id: str
    expanded: bool


class WarmSessionRequest(BaseModel):
    """Pre-bootstrap AgentV2 for a session so the first prompt is not cold-start.

    Maps appserver ``AgentHost.ensure_bootstrapped`` without running a user turn.
    """

    method: Literal["session/warm"] = "session/warm"
    session_id: str
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional wall-clock limit for bootstrap (defaults to appserver warm timeout).",
    )


class SessionSetModelRequest(BaseModel):
    """Select a model for one task without changing the global CLI default.

    Maps ``session/set_model``. The worker rejects this request while its
    prompt is active; the selected model is persisted on the task summary.
    """

    method: Literal["session/set_model"] = "session/set_model"
    session_id: str
    model_id: str


class SessionsListRequest(BaseModel):
    """List persisted Desktop tasks without exposing workspace contents."""

    method: Literal["sessions/list"] = "sessions/list"
    include_trashed: bool = False


class SessionEventsRequest(BaseModel):
    """Replay persisted task events after a cursor."""

    method: Literal["session/events"] = "session/events"
    session_id: str
    cursor: int = Field(default=0, ge=0)


class SessionRenameRequest(BaseModel):
    """Rename a Desktop task; workspace files are never touched."""

    method: Literal["session/rename"] = "session/rename"
    session_id: str
    title: str


class SessionTrashRequest(BaseModel):
    """Soft-delete a Desktop task into Recently Deleted."""

    method: Literal["session/trash"] = "session/trash"
    session_id: str


class SessionRestoreRequest(BaseModel):
    """Restore a soft-deleted Desktop task."""

    method: Literal["session/restore"] = "session/restore"
    session_id: str


class SessionPurgeRequest(BaseModel):
    """Permanently delete only a previously trashed task."""

    method: Literal["session/purge"] = "session/purge"
    session_id: str


class SubagentCapabilityRequest(BaseModel):
    """Discover worker-owned isolated-subagent feature flags."""

    method: Literal["subagents/capability"] = "subagents/capability"
    root_session_id: str | None = None


class SubagentsListRequest(BaseModel):
    """List visible AgentDefinitions for mention/autocomplete UI."""

    method: Literal["subagents/list"] = "subagents/list"
    root_session_id: str


class AgentInvokeRequest(BaseModel):
    """Explicit user ``@agent`` invocation in a Primary/Child tree."""

    method: Literal["agent/invoke"] = "agent/invoke"
    root_session_id: str
    parent_session_id: str | None = None
    request_id: str | None = None
    agent_id: str
    prompt: str
    output_schema: str | None = None
    requested_budget: JsonObject | None = None
    requested_workspace: JsonObject | None = None


class TaskStartRequest(BaseModel):
    """Start a model-driven isolated child task asynchronously."""

    method: Literal["task/start"] = "task/start"
    root_session_id: str
    parent_session_id: str | None = None
    request_id: str | None = None
    agent_id: str
    prompt: str
    output_schema: str | None = None
    requested_budget: JsonObject | None = None
    requested_workspace: JsonObject | None = None


class ChildSessionsListRequest(BaseModel):
    """Return the current persisted child-session tree for a Primary."""

    method: Literal["child_sessions/list"] = "child_sessions/list"
    root_session_id: str


class ChildSessionEventsRequest(BaseModel):
    """Replay child events after a monotonic cursor for reconnect recovery."""

    method: Literal["child_sessions/events"] = "child_sessions/events"
    root_session_id: str
    cursor: int = Field(default=0, ge=0)


class ChildSessionCancelRequest(BaseModel):
    """Cancel one child subtree, or all children when session_id is omitted."""

    method: Literal["child_sessions/cancel"] = "child_sessions/cancel"
    root_session_id: str
    session_id: str | None = None


class ChildSessionRetryRequest(BaseModel):
    """Retry a terminal child with its immutable original request snapshot."""

    method: Literal["child_sessions/retry"] = "child_sessions/retry"
    root_session_id: str
    session_id: str
    request_id: str | None = None


class ShutdownRequest(BaseModel):
    """Graceful appserver shutdown (future ``appserver`` lifespan teardown).

    ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
    """

    method: Literal["shutdown"] = "shutdown"
    reason: str | None = None


class ModelsListRequest(BaseModel):
    """List configured models with provider grouping and Phase 3 limit summary.

    Maps ``models/list``. Response carries ``models``, ``active``, ``recent``.
    """

    method: Literal["models/list"] = "models/list"


class ModelsPresetsRequest(BaseModel):
    """List provider connection presets (base URL only, no model ids).

    Maps ``models/presets``; the client discovers ids via ``models/discover``.
    """

    method: Literal["models/presets"] = "models/presets"


class ModelsDiscoverRequest(BaseModel):
    """Probe a provider catalogue with a credential; never persists.

    Maps ``models/discover``. ``api_key`` is never stored or echoed.
    """

    method: Literal["models/discover"] = "models/discover"
    api_key: str
    base_url: str


class ModelsOnboardRequest(BaseModel):
    """Probe credentials in memory and persist a working model mapping.

    Maps ``models/onboard``. ``api_key`` is stored by the backend
    credential_store (Windows DPAPI) and never returned.
    """

    method: Literal["models/onboard"] = "models/onboard"
    provider_model_id: str
    api_key: str
    base_url: str
    nickname: str | None = None


class ModelsOnboardBatchRequest(BaseModel):
    """Probe + persist multiple models with one credential.

    Maps ``models/onboard_batch``.
    """

    method: Literal["models/onboard_batch"] = "models/onboard_batch"
    api_key: str
    base_url: str
    model_ids: list[str]
    provider_id: str | None = None
    provider_name: str | None = None
    active_model_id: str | None = None
    skip_probe: bool = True


class ModelsRemoveRequest(BaseModel):
    """Remove a model by config key.

    Maps ``models/remove``.
    """

    method: Literal["models/remove"] = "models/remove"
    id: str


class ModelsSetActiveRequest(BaseModel):
    """Switch the active model.

    Maps ``models/set_active``.

    ``effort``（optional_field，2026-08-12）：同时设置全局思考强度档位
    （/effort 命令与设置页共用；厂商档位值或 fast/balanced/deep 抽象档位）。
    缺失 = 不改动当前档位。
    """

    method: Literal["models/set_active"] = "models/set_active"
    id: str
    effort: str | None = None


class ModelsTestConnectionRequest(BaseModel):
    """Live credential test for an existing model.

    Maps ``models/test_connection``.
    """

    method: Literal["models/test_connection"] = "models/test_connection"
    id: str


class CredentialsUpsertRequest(BaseModel):
    """Store/refresh a model API key (backend DPAPI, never echoed).

    Maps ``credentials/upsert``.
    """

    method: Literal["credentials/upsert"] = "credentials/upsert"
    id: str
    api_key: str


class CredentialsDeleteRequest(BaseModel):
    """Clear a model's stored API key reference.

    Maps ``credentials/delete``.
    """

    method: Literal["credentials/delete"] = "credentials/delete"
    id: str


class TeamListRequest(BaseModel):
    """F18b: list registered teams as L1 summaries only."""

    method: Literal["team/list"] = "team/list"


class TeamGroupsRequest(BaseModel):
    """F18b: list groups and member team ids."""

    method: Literal["team/groups"] = "team/groups"


class TeamGroupRenameRequest(BaseModel):
    """F18b: rename a user group. Builtin groups are rejected."""

    method: Literal["team/group_rename"] = "team/group_rename"
    old: str
    new: str


class TeamInstallRequest(BaseModel):
    """F18b: expose F18 team_install two-step ask. No second approval UX."""

    method: Literal["team/install"] = "team/install"
    name: str
    url: str = ""
    confirm: bool = False
    group: str = ""


class TeamSetActiveRequest(BaseModel):
    """F18b: set the session's active team. Idempotent."""

    method: Literal["team/set_active"] = "team/set_active"
    session_id: str
    team_id: str


CLIENT_REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    InitializeRequest,
    NewSessionRequest,
    PromptRequest,
    InterruptRequest,
    SetThinkingExpandedRequest,
    WarmSessionRequest,
    SessionSetModelRequest,
    SessionsListRequest,
    SessionEventsRequest,
    SessionRenameRequest,
    SessionTrashRequest,
    SessionRestoreRequest,
    SessionPurgeRequest,
    SubagentCapabilityRequest,
    SubagentsListRequest,
    AgentInvokeRequest,
    TaskStartRequest,
    ChildSessionsListRequest,
    ChildSessionEventsRequest,
    ChildSessionCancelRequest,
    ChildSessionRetryRequest,
    ShutdownRequest,
    ModelsListRequest,
    ModelsPresetsRequest,
    ModelsDiscoverRequest,
    ModelsOnboardRequest,
    ModelsOnboardBatchRequest,
    ModelsRemoveRequest,
    ModelsSetActiveRequest,
    ModelsTestConnectionRequest,
    CredentialsUpsertRequest,
    CredentialsDeleteRequest,
    TeamListRequest,
    TeamGroupsRequest,
    TeamGroupRenameRequest,
    TeamInstallRequest,
    TeamSetActiveRequest,
)

ClientRequest = Annotated[
    Union[
        InitializeRequest,
        NewSessionRequest,
        PromptRequest,
        InterruptRequest,
        SetThinkingExpandedRequest,
        WarmSessionRequest,
        SessionSetModelRequest,
        SessionsListRequest,
        SessionEventsRequest,
        SessionRenameRequest,
        SessionTrashRequest,
        SessionRestoreRequest,
        SessionPurgeRequest,
        SubagentCapabilityRequest,
        SubagentsListRequest,
        AgentInvokeRequest,
        TaskStartRequest,
        ChildSessionsListRequest,
        ChildSessionEventsRequest,
        ChildSessionCancelRequest,
        ChildSessionRetryRequest,
        ShutdownRequest,
    ],
    Field(discriminator="method"),
]
