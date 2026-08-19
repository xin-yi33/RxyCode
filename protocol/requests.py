"""Client -> server JSON-RPC requests."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

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
    include_archived: bool = False
    workspace_root: str | None = None
    project_id: str | None = None
    status: str | None = None
    updated_after: str | None = None
    updated_before: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    parent_session_id: str | None = None


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
    confirm_purge: bool = False


class ThreadMetadata(BaseModel):
    """PhaseG-B17 thread recycle-bin metadata."""

    deleted_at: str | None = None
    restored_at: str | None = None
    list_category: str | None = None
    associated_files: list[str] | None = None


class ThreadDeleteRequest(BaseModel):
    """Soft-delete a thread (sets deleted_at).

    Maps ``thread/delete``.
    """

    method: Literal["thread/delete"] = "thread/delete"
    session_id: str


class ThreadRestoreRequest(BaseModel):
    """Restore a soft-deleted thread.

    Maps ``thread/restore``.
    """

    method: Literal["thread/restore"] = "thread/restore"
    session_id: str


class ThreadPurgeRequest(BaseModel):
    """Permanently purge a soft-deleted thread.

    Maps ``thread/purge``.
    """

    method: Literal["thread/purge"] = "thread/purge"
    session_id: str
    confirm_purge: bool = False
    paths: list[str] | None = None


class ThreadListDeletedRequest(BaseModel):
    """List soft-deleted threads.

    Maps ``thread/list_deleted``.
    """

    method: Literal["thread/list_deleted"] = "thread/list_deleted"


class SessionForkRequest(BaseModel):
    """PhaseG-B5 fork a thread. Parent events and status stay unchanged."""

    method: Literal["session/fork"] = "session/fork"
    session_id: str


class SessionTreeRequest(BaseModel):
    """PhaseG-B5 parent/child tree. Additive; does not replace child_sessions/list."""

    method: Literal["session/tree"] = "session/tree"
    session_id: str


class SessionArchiveRequest(BaseModel):
    """PhaseG-B5 archive. Not delete; recoverable via unarchive."""

    method: Literal["session/archive"] = "session/archive"
    session_id: str


class SessionUnarchiveRequest(BaseModel):
    """PhaseG-B5 restore an archived thread to the active list."""

    method: Literal["session/unarchive"] = "session/unarchive"
    session_id: str


class SessionItemsRequest(BaseModel):
    """Paginate persisted items (events) after a cursor."""

    method: Literal["session/items"] = "session/items"
    session_id: str
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class TurnStartRequest(BaseModel):
    """PhaseG-B5 start a turn. Wraps session/prompt without replacing it."""

    method: Literal["turn/start"] = "turn/start"
    session_id: str
    text: str
    request_id: str | None = None
    timeout_seconds: float | None = None


class TurnSteerRequest(BaseModel):
    """Append steering text to an in-flight turn. No-op if not running."""

    method: Literal["turn/steer"] = "turn/steer"
    session_id: str
    text: str


class TurnInterruptRequest(BaseModel):
    """PhaseG-B5 interrupt a running turn. Wraps session/interrupt."""

    method: Literal["turn/interrupt"] = "turn/interrupt"
    session_id: str


class TurnRetryRequest(BaseModel):
    """Retry last turn. Same request_id returns the stored result."""

    method: Literal["turn/retry"] = "turn/retry"
    session_id: str
    request_id: str
    text: str | None = None


class CommandStartRequest(BaseModel):
    """PhaseG-B6 user-initiated command. Distinct from agent tool calls."""

    method: Literal["command/start"] = "command/start"
    session_id: str
    command: str
    cwd: str | None = None
    background: bool = False
    timeout_seconds: float | None = None
    approval_id: str | None = None
    actor: str | None = None
    project_id: str | None = None
    expand_sandbox: bool = False
    expand_writable_roots: bool = False
    expand_network: bool = False
    network: bool = False
    writable_roots: list[str] | None = None


class ExecutionListRequest(BaseModel):
    """List tool/command/background items for one session."""

    method: Literal["execution/list"] = "execution/list"
    session_id: str
    include_completed: bool = False


class ExecutionStopRequest(BaseModel):
    """Stop one running tool/command/background task."""

    method: Literal["execution/stop"] = "execution/stop"
    session_id: str
    task_id: str


class ExecutionOutputRequest(BaseModel):
    """Read persisted stdout/stderr after the process has exited."""

    method: Literal["execution/output"] = "execution/output"
    session_id: str
    task_id: str


class PermissionGetRequest(BaseModel):
    """PhaseG-B7 read current permission profile and policy version."""

    method: Literal["permission/get"] = "permission/get"


class PermissionScopeGrant(BaseModel):
    """Durable scoped allow used only by allow_scoped_actions."""

    action: str
    scope: str | None = None
    project_id: str | None = None
    expires_at: str | None = None


class PermissionSetRequest(BaseModel):
    """PhaseG-B7 set a selectable profile. full_access is rejected."""

    method: Literal["permission/set"] = "permission/set"
    profile_id: str
    scopes: list[PermissionScopeGrant] | None = None


class ApprovalDecideRequest(BaseModel):
    """Record an approval decision. One allow does not reuse."""

    method: Literal["approval/decide"] = "approval/decide"
    session_id: str
    action: str
    decision: str
    actor: str = "user"
    scope: str | None = None
    expires_at: str | None = None
    turn_id: str | None = None
    project_id: str | None = None
    reviewer_id: str | None = None
    reason: str | None = None
    original_approval_id: str | None = None
    expand_sandbox: bool = False
    expand_writable_roots: bool = False
    expand_network: bool = False


class ApprovalRevokeRequest(BaseModel):
    """Revoke a previous allow. Restart only keeps persisted non-revoked policy."""

    method: Literal["approval/revoke"] = "approval/revoke"
    approval_id: str


class ApprovalAuditRequest(BaseModel):
    """List approval audit records for a session or all."""

    method: Literal["approval/audit"] = "approval/audit"
    session_id: str | None = None


class ApprovalModeSetRequest(BaseModel):
    """GX2 UI preset mapped onto B7 policy. Request must use ``preset`` not ``mode``."""

    method: Literal["approval/mode_set"] = "approval/mode_set"
    preset: Literal["ask", "auto", "full"]


class ApprovalFullAccessEnableRequest(BaseModel):
    """GX2-PROTO: session-scoped unlock of B7 full_access. Restart clears it."""

    method: Literal["approval/full_access_enable"] = "approval/full_access_enable"
    actor: str
    source: str = "settings"


class ReviewStartRequest(BaseModel):
    """PhaseG-B8 start a read-only review. Does not modify the working tree."""

    method: Literal["review/start"] = "review/start"
    request_id: str
    session_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    scope: str = "working_tree"
    base_ref: str | None = None
    head_ref: str | None = None
    paths: list[str] | None = None
    criteria: list[str] | None = None
    reviewer: JsonObject | None = None


class ReviewReadRequest(BaseModel):
    """Reconnect/read a persisted review without restarting it."""

    method: Literal["review/read"] = "review/read"
    review_id: str
    after_sequence: int | None = None


class ReviewCommentRequest(BaseModel):
    """Line comment bound to review/finding/file hash/line range."""

    method: Literal["review/comment"] = "review/comment"
    review_id: str
    file: str
    start_line: int
    end_line: int
    body: str
    finding_id: str | None = None
    file_hash: str | None = None


class ReviewCommentAddRequest(BaseModel):
    """GX3 add inline comment. Does not replace review/comment."""

    method: Literal["review/comment/add"] = "review/comment/add"
    review_id: str
    file: str
    line: int
    hunk_hash: str
    body: str


class ReviewCommentResolveRequest(BaseModel):
    """GX3 resolve an inline comment (open or stale)."""

    method: Literal["review/comment/resolve"] = "review/comment/resolve"
    comment_id: str


class CheckpointCreateRequest(BaseModel):
    """Create a session checkpoint without writing the workspace tree."""

    method: Literal["checkpoint/create"] = "checkpoint/create"
    session_id: str
    reason: str | None = None
    turn_id: str | None = None


class CheckpointListRequest(BaseModel):
    """List checkpoints for a session."""

    method: Literal["checkpoint/list"] = "checkpoint/list"
    session_id: str


class CheckpointReadRequest(BaseModel):
    """Read one checkpoint payload."""

    method: Literal["checkpoint/read"] = "checkpoint/read"
    checkpoint_id: str
    session_id: str


class CheckpointRestoreRequest(BaseModel):
    """Restore a session to a previous checkpoint."""

    method: Literal["checkpoint/restore"] = "checkpoint/restore"
    checkpoint_id: str
    session_id: str
    approval_id: str | None = None


class GitStageRequest(BaseModel):
    """Stage git paths inside the workspace."""

    method: Literal["git/stage"] = "git/stage"
    session_id: str
    paths: list[str]
    approval_id: str | None = None


class GitUnstageRequest(BaseModel):
    """Unstage git paths inside the workspace."""

    method: Literal["git/unstage"] = "git/unstage"
    session_id: str
    paths: list[str]
    approval_id: str | None = None


class GitRevertRequest(BaseModel):
    """Revert git hunks or paths inside the workspace."""

    method: Literal["git/revert"] = "git/revert"
    session_id: str
    paths: list[str]
    hunk_index: int | None = None
    approval_id: str | None = None


class FilePreviewRequest(BaseModel):
    """Preview a workspace file for the client."""

    method: Literal["file/preview"] = "file/preview"
    session_id: str
    path: str


class FileTreeRequest(BaseModel):
    """List a workspace directory tree."""

    method: Literal["file/tree"] = "file/tree"
    session_id: str
    path: str | None = None


class FileOpenExternalRequest(BaseModel):
    """Open a workspace file in an external program after confirm."""

    method: Literal["file/open_external"] = "file/open_external"
    session_id: str
    path: str
    confirm: bool = False


class WorktreeListRequest(BaseModel):
    """List git worktrees for the session workspace."""

    method: Literal["worktree/list"] = "worktree/list"
    session_id: str


class WorktreeOpenRequest(BaseModel):
    """Switch the session onto an existing git worktree."""

    method: Literal["worktree/open"] = "worktree/open"
    session_id: str
    worktree_id: str


class WorktreeCreateRequest(BaseModel):
    """Create a git worktree under the workspace."""

    method: Literal["worktree/create"] = "worktree/create"
    session_id: str
    dest: str
    branch: str | None = None
    approval_id: str | None = None


class WorktreeCloseRequest(BaseModel):
    """Close a git worktree after optional confirm."""

    method: Literal["worktree/close"] = "worktree/close"
    session_id: str
    worktree_id: str
    force: bool = False
    confirm: bool = False
    approval_id: str | None = None


class WorktreePruneRequest(BaseModel):
    """Prune stale git worktrees after confirm."""

    method: Literal["worktree/prune"] = "worktree/prune"
    session_id: str
    confirm: bool = False
    approval_id: str | None = None


class WorktreeHandoffRequest(BaseModel):
    """Hand a worktree path to another session after confirm."""

    method: Literal["worktree/handoff"] = "worktree/handoff"
    session_id: str
    target_session: str
    target_path: str
    confirm: bool = False
    approval_id: str | None = None


class WorktreeHandoffRollbackRequest(BaseModel):
    """Roll back a worktree handoff."""

    method: Literal["worktree/handoff/rollback"] = "worktree/handoff/rollback"
    handoff_id: str
    session_id: str
    approval_id: str | None = None


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


class ProjectListRequest(BaseModel):
    """PhaseG-B4 list recent projects."""

    method: Literal["project/list"] = "project/list"


class ProjectAddRequest(BaseModel):
    """PhaseG-B4 add a local directory. Display name is separate from path."""

    method: Literal["project/add"] = "project/add"
    path: str
    display_name: str | None = None


class ProjectRemoveRequest(BaseModel):
    """PhaseG-B4 drop from recent list. Never deletes user files."""

    method: Literal["project/remove"] = "project/remove"
    project_id: str


class ProjectSetActiveRequest(BaseModel):
    """PhaseG-B4 switch the active project without changing process cwd."""

    method: Literal["project/set_active"] = "project/set_active"
    project_id: str


class WorkspaceStatusRequest(BaseModel):
    """PhaseG-B4 report branch/worktree or NOT_A_GIT_REPO. Never chdir."""

    method: Literal["workspace/status"] = "workspace/status"
    workspace_root: str


class WorkspaceResolveRequest(BaseModel):
    """Reject paths that escape the bound workspace, including symlink hops."""

    method: Literal["workspace/resolve"] = "workspace/resolve"
    workspace_root: str
    path: str


class SettingsGetRequest(BaseModel):
    """Resolve settings through global→project→workspace→thread/turn.

    Maps ``settings/get``. Same interpretation for Desktop and CLI.
    """

    method: Literal["settings/get"] = "settings/get"
    session_id: str | None = None
    project_id: str | None = None
    workspace: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    keys: list[str] | None = None


class SettingsSetRequest(BaseModel):
    """Write one explicit settings layer. Secrets are not stored in values.

    Maps ``settings/set``. Requires B7 permission. Changing model does not
    rewrite existing thread history.
    """

    method: Literal["settings/set"] = "settings/set"
    layer: str
    values: JsonObject
    session_id: str | None = None
    project_id: str | None = None
    workspace: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    actor: str | None = None
    approval_id: str | None = None


class SettingsModelsRequest(BaseModel):
    """Look up a real model_id in ModelCatalog and return a ModelSummary.

    Maps ``settings/models``. Unknown models keep their id and use the high
    fallback with warning; they are not rewritten to a known catalog model.
    """

    method: Literal["settings/models"] = "settings/models"
    provider_id: str
    model_id: str
    max_tokens: int | None = None
    session_id: str | None = None


class SettingsDiagnoseRequest(BaseModel):
    """Classify key-invalid, quota, and model-unavailable as distinct codes.

    Maps ``settings/diagnose``. Messages are redacted.
    """

    method: Literal["settings/diagnose"] = "settings/diagnose"
    error_code: str | None = None
    message: str | None = None
    provider_id: str | None = None
    model_id: str | None = None


class SettingsRollbackRequest(BaseModel):
    """Restore a settings snapshot written before a previous set.

    Maps ``settings/rollback``. Requires B7 permission.
    """

    method: Literal["settings/rollback"] = "settings/rollback"
    snapshot_id: str
    session_id: str | None = None
    actor: str | None = None
    approval_id: str | None = None


class CapabilitiesListRequest(BaseModel):
    """Project skills, MCP servers, and the browser placeholder.

    Maps ``capabilities/list``. Unavailable items have available=false.
    """

    method: Literal["capabilities/list"] = "capabilities/list"
    kind: str | None = None
    available_only: bool = False
    session_id: str | None = None


class CapabilitiesGetRequest(BaseModel):
    """Read one capability projection.

    Maps ``capabilities/get``.
    """

    method: Literal["capabilities/get"] = "capabilities/get"
    capability_id: str
    session_id: str | None = None


class CapabilitiesSetEnabledRequest(BaseModel):
    """Enable or authorize a capability. Browser cannot be turned into a bypass.

    Maps ``capabilities/set_enabled``.
    """

    method: Literal["capabilities/set_enabled"] = "capabilities/set_enabled"
    capability_id: str
    enabled: bool
    authorize: bool | None = None
    session_id: str | None = None
    actor: str | None = None
    approval_id: str | None = None


class CapabilitiesInvokeRequest(BaseModel):
    """Invoke a capability as a normal Tool/Approval/Review job.

    Maps ``capabilities/invoke``. Failures are terminal and cancellable.
    """

    method: Literal["capabilities/invoke"] = "capabilities/invoke"
    capability_id: str
    session_id: str | None = None
    turn_id: str | None = None
    actor: str | None = None
    approval_id: str | None = None
    background: bool = False


class CapabilitiesCancelRequest(BaseModel):
    """Cancel an in-flight capability job so the Thread does not stay stuck.

    Maps ``capabilities/cancel``.
    """

    method: Literal["capabilities/cancel"] = "capabilities/cancel"
    job_id: str
    session_id: str | None = None


class CapabilitiesAuditRequest(BaseModel):
    """Return copyable, source-located capability audit records.

    Maps ``capabilities/audit``.
    """

    method: Literal["capabilities/audit"] = "capabilities/audit"
    capability_id: str | None = None
    session_id: str | None = None


class RecoveryStatusRequest(BaseModel):
    """Project session recovery state. Incomplete never becomes completed.

    Maps ``recovery/status``.
    """

    method: Literal["recovery/status"] = "recovery/status"
    session_id: str | None = None


class RecoveryReplayRequest(BaseModel):
    """Replay events after a saved cursor and persist the new cursor.

    Maps ``recovery/replay``.
    """

    method: Literal["recovery/replay"] = "recovery/replay"
    session_id: str
    cursor: int | None = None
    limit: int = 100


class RecoveryReclaimRequest(BaseModel):
    """Mark orphan incomplete sessions recovery_required.

    Maps ``recovery/reclaim``.
    """

    method: Literal["recovery/reclaim"] = "recovery/reclaim"


class NotificationsListRequest(BaseModel):
    """List deduped recovery notifications.

    Maps ``notifications/list``.
    """

    method: Literal["notifications/list"] = "notifications/list"
    session_id: str | None = None
    include_acked: bool = False


class NotificationsAckRequest(BaseModel):
    """Acknowledge one notification.

    Maps ``notifications/ack``.
    """

    method: Literal["notifications/ack"] = "notifications/ack"
    notification_id: str


class NotificationsCursorRequest(BaseModel):
    """Persist a disconnect cursor for later replay.

    Maps ``notifications/cursor``.
    """

    method: Literal["notifications/cursor"] = "notifications/cursor"
    session_id: str
    cursor: int


class ReleaseStatusRequest(BaseModel):
    """Advertise runtime/protocol/schema bind.

    Maps ``release/status``.
    """

    method: Literal["release/status"] = "release/status"


class ReleaseDiagnoseRequest(BaseModel):
    """Diagnose client/server version or schema mismatch.

    Maps ``release/diagnose``.
    """

    method: Literal["release/diagnose"] = "release/diagnose"
    protocol_version: str | None = None
    appserver_version: str | None = None
    schema_digest: str | None = None


class CliListRequest(BaseModel):
    """List CLI-Hub software ids. Names stay out of tools/registry.

    Maps ``cli/list``.
    """

    method: Literal["cli/list"] = "cli/list"


class CliInstallRequest(BaseModel):
    """Install one CLI into an isolated venv.

    Maps ``cli/install``.
    """

    method: Literal["cli/install"] = "cli/install"
    name: str
    source: str = "cli-hub"


class CliLaunchRequest(BaseModel):
    """Launch an installed CLI software id.

    Maps ``cli/launch``.
    """

    method: Literal["cli/launch"] = "cli/launch"
    name: str
    args: list[str] | None = None


class CliUninstallRequest(BaseModel):
    """Uninstall one isolated CLI software id.

    Maps ``cli/uninstall``.
    """

    method: Literal["cli/uninstall"] = "cli/uninstall"
    name: str


class CliStartRequest(BaseModel):
    """Start a long-running CLI process in its isolated venv.

    Maps ``cli/start``.
    """

    method: Literal["cli/start"] = "cli/start"
    name: str
    args: list[str] | None = None


class CliStopRequest(BaseModel):
    """Stop a long-running CLI process.

    Maps ``cli/stop``.
    """

    method: Literal["cli/stop"] = "cli/stop"
    name: str


class CliDecideRequest(BaseModel):
    """C-C registry-first decision for a software id.

    Maps ``cli/decide``.
    """

    method: Literal["cli/decide"] = "cli/decide"
    name: str
    has_source: bool = False
    has_sdk: bool = False


class ScheduleListRequest(BaseModel):
    """List application-layer scheduled jobs.

    Maps ``schedule/list``.
    """

    method: Literal["schedule/list"] = "schedule/list"


class ScheduleCreateRequest(BaseModel):
    """Create an interval or at-time job.

    Maps ``schedule/create``.
    """

    method: Literal["schedule/create"] = "schedule/create"
    rule: dict
    action: dict
    enabled: bool = True


class ScheduleUpdateRequest(BaseModel):
    """Update one scheduled job.

    Maps ``schedule/update``.
    """

    method: Literal["schedule/update"] = "schedule/update"
    job_id: str
    rule: dict | None = None
    action: dict | None = None
    enabled: bool | None = None


class ScheduleDeleteRequest(BaseModel):
    """Delete one scheduled job.

    Maps ``schedule/delete``.
    """

    method: Literal["schedule/delete"] = "schedule/delete"
    job_id: str


class ScheduleToggleRequest(BaseModel):
    """Enable or disable one scheduled job.

    Maps ``schedule/toggle``.
    """

    method: Literal["schedule/toggle"] = "schedule/toggle"
    job_id: str
    enabled: bool | None = None


class CliRecordFailureRequest(BaseModel):
    """C-E generate-failure ladder record.

    Maps ``cli/record_failure``.
    """

    method: Literal["cli/record_failure"] = "cli/record_failure"
    name: str
    stage: str
    reason: str
    next_step: str | None = None


class PluginListRequest(BaseModel):
    """List installed plugins.

    Maps ``plugin/list``.
    """

    method: Literal["plugin/list"] = "plugin/list"


class PluginInstallRequest(BaseModel):
    """Install a plugin from a local directory or configured registry.

    Maps ``plugin/install``.
    """

    method: Literal["plugin/install"] = "plugin/install"
    source: str
    path: str | None = None
    name: str | None = None


class PluginUninstallRequest(BaseModel):
    """Unregister a plugin and optionally keep user.json.

    Maps ``plugin/uninstall``.
    """

    method: Literal["plugin/uninstall"] = "plugin/uninstall"
    name: str
    keep_user_config: bool = False

    @field_validator("keep_user_config", mode="before")
    @classmethod
    def _keep_user_config_bool(cls, value: object) -> object:
        if value is not True and value is not False:
            raise ValueError("keep_user_config must be a JSON boolean")
        return value


class PluginToggleRequest(BaseModel):
    """Enable or disable a plugin via B11 capability/set_enabled.

    Maps ``plugin/toggle``.
    """

    method: Literal["plugin/toggle"] = "plugin/toggle"
    name: str
    enabled: bool

    @field_validator("enabled", mode="before")
    @classmethod
    def _enabled_bool(cls, value: object) -> object:
        if value is not True and value is not False:
            raise ValueError("enabled must be a JSON boolean")
        return value


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
    ThreadDeleteRequest,
    ThreadRestoreRequest,
    ThreadPurgeRequest,
    ThreadListDeletedRequest,
    SessionForkRequest,
    SessionTreeRequest,
    SessionArchiveRequest,
    SessionUnarchiveRequest,
    SessionItemsRequest,
    TurnStartRequest,
    TurnSteerRequest,
    TurnInterruptRequest,
    TurnRetryRequest,
    CommandStartRequest,
    ExecutionListRequest,
    ExecutionStopRequest,
    ExecutionOutputRequest,
    PermissionGetRequest,
    PermissionSetRequest,
    ApprovalDecideRequest,
    ApprovalRevokeRequest,
    ApprovalAuditRequest,
    ApprovalModeSetRequest,
    ApprovalFullAccessEnableRequest,
    ReviewStartRequest,
    ReviewReadRequest,
    ReviewCommentRequest,
    ReviewCommentAddRequest,
    ReviewCommentResolveRequest,
    CheckpointCreateRequest,
    CheckpointListRequest,
    CheckpointReadRequest,
    CheckpointRestoreRequest,
    GitStageRequest,
    GitUnstageRequest,
    GitRevertRequest,
    FilePreviewRequest,
    FileTreeRequest,
    FileOpenExternalRequest,
    WorktreeListRequest,
    WorktreeOpenRequest,
    WorktreeCreateRequest,
    WorktreeCloseRequest,
    WorktreePruneRequest,
    WorktreeHandoffRequest,
    WorktreeHandoffRollbackRequest,
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
    ProjectListRequest,
    ProjectAddRequest,
    ProjectRemoveRequest,
    ProjectSetActiveRequest,
    WorkspaceStatusRequest,
    WorkspaceResolveRequest,
    SettingsGetRequest,
    SettingsSetRequest,
    SettingsModelsRequest,
    SettingsDiagnoseRequest,
    SettingsRollbackRequest,
    CapabilitiesListRequest,
    CapabilitiesGetRequest,
    CapabilitiesSetEnabledRequest,
    CapabilitiesInvokeRequest,
    CapabilitiesCancelRequest,
    CapabilitiesAuditRequest,
    RecoveryStatusRequest,
    RecoveryReplayRequest,
    RecoveryReclaimRequest,
    NotificationsListRequest,
    NotificationsAckRequest,
    NotificationsCursorRequest,
    ReleaseStatusRequest,
    ReleaseDiagnoseRequest,
    CliListRequest,
    CliInstallRequest,
    CliLaunchRequest,
    CliUninstallRequest,
    CliStartRequest,
    CliStopRequest,
    CliDecideRequest,
    CliRecordFailureRequest,
    ScheduleListRequest,
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    ScheduleDeleteRequest,
    ScheduleToggleRequest,
    PluginListRequest,
    PluginInstallRequest,
    PluginUninstallRequest,
    PluginToggleRequest,
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
        ThreadDeleteRequest,
        ThreadRestoreRequest,
        ThreadPurgeRequest,
        ThreadListDeletedRequest,
        SubagentCapabilityRequest,
        SubagentsListRequest,
        AgentInvokeRequest,
        TaskStartRequest,
        ChildSessionsListRequest,
        ChildSessionEventsRequest,
        ChildSessionCancelRequest,
        ChildSessionRetryRequest,
        ShutdownRequest,
        SettingsGetRequest,
        SettingsSetRequest,
        SettingsModelsRequest,
        SettingsDiagnoseRequest,
        SettingsRollbackRequest,
        CapabilitiesListRequest,
        CapabilitiesGetRequest,
        CapabilitiesSetEnabledRequest,
        CapabilitiesInvokeRequest,
        CapabilitiesCancelRequest,
        CapabilitiesAuditRequest,
        RecoveryStatusRequest,
        RecoveryReplayRequest,
        RecoveryReclaimRequest,
        NotificationsListRequest,
        NotificationsAckRequest,
        NotificationsCursorRequest,
        ReleaseStatusRequest,
        ReleaseDiagnoseRequest,
        CliListRequest,
        CliInstallRequest,
        CliLaunchRequest,
        CliUninstallRequest,
        CliStartRequest,
        CliStopRequest,
        CliDecideRequest,
        CliRecordFailureRequest,
        ScheduleListRequest,
        ScheduleCreateRequest,
        ScheduleUpdateRequest,
        ScheduleDeleteRequest,
        ScheduleToggleRequest,
        PluginListRequest,
        PluginInstallRequest,
        PluginUninstallRequest,
        PluginToggleRequest,
    ],
    Field(discriminator="method"),
]
