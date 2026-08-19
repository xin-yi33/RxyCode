/* Auto-generated. Edit protocol/schema.json then run: bun run generate */

export type RxyCodeProtocol =
  ClientRequest | ProtocolNotification | ServerRequestMessage | AgentProtocol | HandshakeProtocol;
export type ClientRequest =
  | InitializeRequest
  | NewSessionRequest
  | PromptRequest
  | InterruptRequest
  | SetThinkingExpandedRequest
  | WarmSessionRequest
  | SessionSetModelRequest
  | SessionsListRequest
  | SessionEventsRequest
  | SessionRenameRequest
  | SessionTrashRequest
  | SessionRestoreRequest
  | SessionPurgeRequest
  | ThreadDeleteRequest
  | ThreadRestoreRequest
  | ThreadPurgeRequest
  | ThreadListDeletedRequest
  | SessionForkRequest
  | ThreadForkRequest
  | ThreadPinRequest
  | SessionTreeRequest
  | SessionArchiveRequest
  | SessionUnarchiveRequest
  | SessionItemsRequest
  | TurnStartRequest
  | TurnSteerRequest
  | TurnInterruptRequest
  | TurnRetryRequest
  | CommandStartRequest
  | ExecutionListRequest
  | ExecutionStopRequest
  | ExecutionOutputRequest
  | PermissionGetRequest
  | PermissionSetRequest
  | ApprovalDecideRequest
  | ApprovalRevokeRequest
  | ApprovalAuditRequest
  | ApprovalModeSetRequest
  | ApprovalFullAccessEnableRequest
  | ReviewStartRequest
  | ReviewReadRequest
  | ReviewCommentRequest
  | ReviewCommentAddRequest
  | ReviewCommentResolveRequest
  | CheckpointCreateRequest
  | CheckpointListRequest
  | CheckpointReadRequest
  | CheckpointRestoreRequest
  | CheckpointSnapshotCreateRequest
  | CheckpointRewindRequest
  | PlanPersistRequest
  | PlanImplementRequest
  | GitStageRequest
  | GitUnstageRequest
  | GitRevertRequest
  | FilePreviewRequest
  | FileTreeRequest
  | FileOpenExternalRequest
  | WorktreeListRequest
  | WorktreeOpenRequest
  | WorktreeCreateRequest
  | WorktreeCloseRequest
  | WorktreePruneRequest
  | WorktreeHandoffRequest
  | WorktreeHandoffRollbackRequest
  | SubagentCapabilityRequest
  | SubagentsListRequest
  | AgentInvokeRequest
  | TaskStartRequest
  | ChildSessionsListRequest
  | ChildSessionEventsRequest
  | ChildSessionCancelRequest
  | ChildSessionRetryRequest
  | ShutdownRequest
  | ModelsListRequest
  | ModelsPresetsRequest
  | ModelsDiscoverRequest
  | ModelsOnboardRequest
  | ModelsOnboardBatchRequest
  | ModelsRemoveRequest
  | ModelsSetActiveRequest
  | ModelsTestConnectionRequest
  | CredentialsUpsertRequest
  | CredentialsDeleteRequest
  | TeamListRequest
  | TeamGroupsRequest
  | TeamGroupRenameRequest
  | TeamInstallRequest
  | TeamSetActiveRequest
  | ProjectListRequest
  | ProjectAddRequest
  | ProjectRemoveRequest
  | ProjectSetActiveRequest
  | WorkspaceStatusRequest
  | WorkspaceResolveRequest
  | SettingsGetRequest
  | SettingsSetRequest
  | SettingsModelsRequest
  | SettingsDiagnoseRequest
  | SettingsRollbackRequest
  | CapabilitiesListRequest
  | CapabilitiesGetRequest
  | CapabilitiesSetEnabledRequest
  | CapabilitiesInvokeRequest
  | CapabilitiesCancelRequest
  | CapabilitiesAuditRequest
  | RecoveryStatusRequest
  | RecoveryReplayRequest
  | RecoveryReclaimRequest
  | NotificationsListRequest
  | NotificationsAckRequest
  | NotificationsCursorRequest
  | ReleaseStatusRequest
  | ReleaseDiagnoseRequest
  | CliListRequest
  | CliInstallRequest
  | CliLaunchRequest
  | CliUninstallRequest
  | CliStartRequest
  | CliStopRequest
  | CliDecideRequest
  | CliRecordFailureRequest
  | ScheduleListRequest
  | ScheduleCreateRequest
  | ScheduleUpdateRequest
  | ScheduleDeleteRequest
  | ScheduleToggleRequest
  | PluginListRequest
  | PluginInstallRequest
  | PluginUninstallRequest
  | PluginToggleRequest;
export type Method = "initialize";
export type ClientName = string;
export type ClientVersion = string;
export type ProtocolVersion = string;
export type Capabilities = {
  [k: string]: unknown;
} | null;
export type ClientInfo = {
  [k: string]: unknown;
} | null;
export type ClientCapabilities = {
  [k: string]: unknown;
} | null;
export type RequestedFeatures = string[] | null;
export type Method1 = "session/new";
export type WorkspaceRoot = string;
export type Model = string | null;
export type Method2 = "session/prompt";
export type SessionId = string;
export type Text = string;
/**
 * Optional wall-clock limit for this prompt (maps execution.tool_timeout_seconds semantics).
 */
export type TimeoutSeconds = number | null;
/**
 * Agent run mode (build/plan/compose); defaults to build.
 */
export type Mode = string | null;
/**
 * When true, ProtocolTui emits event/reasoning_snapshot chunks.
 */
export type ThinkingExpanded = boolean | null;
export type Method3 = "session/interrupt";
export type SessionId1 = string;
export type Method4 = "session/set_thinking_expanded";
export type SessionId2 = string;
export type Expanded = boolean;
export type Method5 = "session/warm";
export type SessionId3 = string;
/**
 * Optional wall-clock limit for bootstrap (defaults to appserver warm timeout).
 */
export type TimeoutSeconds1 = number | null;
export type Method6 = "session/set_model";
export type SessionId4 = string;
export type ModelId = string;
export type Method7 = "sessions/list";
export type IncludeTrashed = boolean;
export type IncludeArchived = boolean;
export type WorkspaceRoot1 = string | null;
export type ProjectId = string | null;
export type Status = string | null;
export type UpdatedAfter = string | null;
export type UpdatedBefore = string | null;
export type CreatedAfter = string | null;
export type CreatedBefore = string | null;
export type ParentSessionId = string | null;
export type Method8 = "session/events";
export type SessionId5 = string;
export type Cursor = number;
export type Method9 = "session/rename";
export type SessionId6 = string;
export type Title = string;
export type Method10 = "session/trash";
export type SessionId7 = string;
export type Method11 = "session/restore";
export type SessionId8 = string;
export type Method12 = "session/purge";
export type SessionId9 = string;
export type ConfirmPurge = boolean;
export type Method13 = "thread/delete";
export type SessionId10 = string;
export type Method14 = "thread/restore";
export type SessionId11 = string;
export type Method15 = "thread/purge";
export type SessionId12 = string;
export type ConfirmPurge1 = boolean;
export type Paths = string[] | null;
export type Method16 = "thread/list_deleted";
export type Method17 = "session/fork";
export type SessionId13 = string;
export type Method18 = "thread/fork";
export type ThreadId = string;
export type MessageId = string;
export type EditedText = string | null;
export type Method19 = "thread/pin";
export type ThreadId1 = string;
export type Pinned = boolean;
export type Method20 = "session/tree";
export type SessionId14 = string;
export type Method21 = "session/archive";
export type SessionId15 = string;
export type Method22 = "session/unarchive";
export type SessionId16 = string;
export type Method23 = "session/items";
export type SessionId17 = string;
export type Cursor1 = number;
export type Limit = number;
export type Method24 = "turn/start";
export type SessionId18 = string;
export type Text1 = string;
export type RequestId = string | null;
export type TimeoutSeconds2 = number | null;
export type Method25 = "turn/steer";
export type SessionId19 = string;
export type Text2 = string;
export type Method26 = "turn/interrupt";
export type SessionId20 = string;
export type Method27 = "turn/retry";
export type SessionId21 = string;
export type RequestId1 = string;
export type Text3 = string | null;
export type Method28 = "command/start";
export type SessionId22 = string;
export type Command = string;
export type Cwd = string | null;
export type Background = boolean;
export type TimeoutSeconds3 = number | null;
export type ApprovalId = string | null;
export type Actor = string | null;
export type ProjectId1 = string | null;
export type ExpandSandbox = boolean;
export type ExpandWritableRoots = boolean;
export type ExpandNetwork = boolean;
export type Network = boolean;
export type WritableRoots = string[] | null;
export type Method29 = "execution/list";
export type SessionId23 = string;
export type IncludeCompleted = boolean;
export type Method30 = "execution/stop";
export type SessionId24 = string;
export type TaskId = string;
export type Method31 = "execution/output";
export type SessionId25 = string;
export type TaskId1 = string;
export type Method32 = "permission/get";
export type Method33 = "permission/set";
export type ProfileId = string;
export type Scopes = PermissionScopeGrant[] | null;
export type Action = string;
export type Scope = string | null;
export type ProjectId2 = string | null;
export type ExpiresAt = string | null;
export type Method34 = "approval/decide";
export type SessionId26 = string;
export type Action1 = string;
export type Decision = string;
export type Actor1 = string;
export type Scope1 = string | null;
export type ExpiresAt1 = string | null;
export type TurnId = string | null;
export type ProjectId3 = string | null;
export type ReviewerId = string | null;
export type Reason = string | null;
export type OriginalApprovalId = string | null;
export type ExpandSandbox1 = boolean;
export type ExpandWritableRoots1 = boolean;
export type ExpandNetwork1 = boolean;
export type Method35 = "approval/revoke";
export type ApprovalId1 = string;
export type Method36 = "approval/audit";
export type SessionId27 = string | null;
export type Method37 = "approval/mode_set";
export type Preset = "ask" | "auto" | "full";
export type Method38 = "approval/full_access_enable";
export type Actor2 = string;
export type Source = string;
export type Method39 = "review/start";
export type RequestId2 = string;
export type SessionId28 = string | null;
export type ThreadId2 = string | null;
export type TurnId1 = string | null;
export type Scope2 = string;
export type BaseRef = string | null;
export type HeadRef = string | null;
export type Paths1 = string[] | null;
export type Criteria = string[] | null;
export type Reviewer = {
  [k: string]: unknown;
} | null;
export type Method40 = "review/read";
export type ReviewId = string;
export type AfterSequence = number | null;
export type Method41 = "review/comment";
export type ReviewId1 = string;
export type File = string;
export type StartLine = number;
export type EndLine = number;
export type Body = string;
export type FindingId = string | null;
export type FileHash = string | null;
export type Method42 = "review/comment/add";
export type ReviewId2 = string;
export type File1 = string;
export type Line = number;
export type HunkHash = string;
export type Body1 = string;
export type Method43 = "review/comment/resolve";
export type CommentId = string;
export type Method44 = "checkpoint/create";
export type SessionId29 = string;
export type Reason1 = string | null;
export type TurnId2 = string | null;
export type Method45 = "checkpoint/list";
export type SessionId30 = string;
export type Method46 = "checkpoint/read";
export type CheckpointId = string;
export type SessionId31 = string;
export type Method47 = "checkpoint/restore";
export type CheckpointId1 = string;
export type SessionId32 = string;
export type ApprovalId2 = string | null;
export type Method48 = "checkpoint/snapshot/create";
export type Name = string;
export type SessionId33 = string;
export type UserPrompt = string | null;
export type Method49 = "checkpoint/rewind";
export type CheckpointId2 = string;
export type Confirm = boolean;
export type SessionId34 = string;
export type Method50 = "plan/persist";
export type ThreadId3 = string;
export type Title1 = string;
export type Goal = string;
export type Steps = string[];
export type Acceptance = string[];
export type Method51 = "plan/implement";
export type PlanId = string;
export type Confirm1 = boolean;
export type Method52 = "git/stage";
export type SessionId35 = string;
export type Paths2 = string[];
export type ApprovalId3 = string | null;
export type Method53 = "git/unstage";
export type SessionId36 = string;
export type Paths3 = string[];
export type ApprovalId4 = string | null;
export type Method54 = "git/revert";
export type SessionId37 = string;
export type Paths4 = string[];
export type HunkIndex = number | null;
export type ApprovalId5 = string | null;
export type Method55 = "file/preview";
export type SessionId38 = string;
export type Path = string;
export type Method56 = "file/tree";
export type SessionId39 = string;
export type Path1 = string | null;
export type Method57 = "file/open_external";
export type SessionId40 = string;
export type Path2 = string;
export type Confirm2 = boolean;
export type Method58 = "worktree/list";
export type SessionId41 = string;
export type Method59 = "worktree/open";
export type SessionId42 = string;
export type WorktreeId = string;
export type Method60 = "worktree/create";
export type SessionId43 = string;
export type Dest = string;
export type Branch = string | null;
export type ApprovalId6 = string | null;
export type Method61 = "worktree/close";
export type SessionId44 = string;
export type WorktreeId1 = string;
export type Force = boolean;
export type Confirm3 = boolean;
export type ApprovalId7 = string | null;
export type Method62 = "worktree/prune";
export type SessionId45 = string;
export type Confirm4 = boolean;
export type ApprovalId8 = string | null;
export type Method63 = "worktree/handoff";
export type SessionId46 = string;
export type TargetSession = string;
export type TargetPath = string;
export type Confirm5 = boolean;
export type ApprovalId9 = string | null;
export type Method64 = "worktree/handoff/rollback";
export type HandoffId = string;
export type SessionId47 = string;
export type ApprovalId10 = string | null;
export type Method65 = "subagents/capability";
export type RootSessionId = string | null;
export type Method66 = "subagents/list";
export type RootSessionId1 = string;
export type Method67 = "agent/invoke";
export type RootSessionId2 = string;
export type ParentSessionId1 = string | null;
export type RequestId3 = string | null;
export type AgentId = string;
export type Prompt = string;
export type OutputSchema = string | null;
export type RequestedBudget = {
  [k: string]: unknown;
} | null;
export type RequestedWorkspace = {
  [k: string]: unknown;
} | null;
export type Method68 = "task/start";
export type RootSessionId3 = string;
export type ParentSessionId2 = string | null;
export type RequestId4 = string | null;
export type AgentId1 = string;
export type Prompt1 = string;
export type OutputSchema1 = string | null;
export type RequestedBudget1 = {
  [k: string]: unknown;
} | null;
export type RequestedWorkspace1 = {
  [k: string]: unknown;
} | null;
export type Method69 = "child_sessions/list";
export type RootSessionId4 = string;
export type Method70 = "child_sessions/events";
export type RootSessionId5 = string;
export type Cursor2 = number;
export type Method71 = "child_sessions/cancel";
export type RootSessionId6 = string;
export type SessionId48 = string | null;
export type Method72 = "child_sessions/retry";
export type RootSessionId7 = string;
export type SessionId49 = string;
export type RequestId5 = string | null;
export type Method73 = "shutdown";
export type Reason2 = string | null;
export type Method74 = "models/list";
export type Method75 = "models/presets";
export type Method76 = "models/discover";
export type ApiKey = string;
export type BaseUrl = string;
export type Method77 = "models/onboard";
export type ProviderModelId = string;
export type ApiKey1 = string;
export type BaseUrl1 = string;
export type Nickname = string | null;
export type Method78 = "models/onboard_batch";
export type ApiKey2 = string;
export type BaseUrl2 = string;
export type ModelIds = string[];
export type ProviderId = string | null;
export type ProviderName = string | null;
export type ActiveModelId = string | null;
export type SkipProbe = boolean;
export type Method79 = "models/remove";
export type Id = string;
export type Method80 = "models/set_active";
export type Id1 = string;
export type Effort = string | null;
export type Method81 = "models/test_connection";
export type Id2 = string;
export type Method82 = "credentials/upsert";
export type Id3 = string;
export type ApiKey3 = string;
export type Method83 = "credentials/delete";
export type Id4 = string;
export type Method84 = "team/list";
export type Method85 = "team/groups";
export type Method86 = "team/group_rename";
export type Old = string;
export type New = string;
export type Method87 = "team/install";
export type Name1 = string;
export type Url = string;
export type Confirm6 = boolean;
export type Group = string;
export type Method88 = "team/set_active";
export type SessionId50 = string;
export type TeamId = string;
export type Method89 = "project/list";
export type Method90 = "project/add";
export type Path3 = string;
export type DisplayName = string | null;
export type Method91 = "project/remove";
export type ProjectId4 = string;
export type Method92 = "project/set_active";
export type ProjectId5 = string;
export type Method93 = "workspace/status";
export type WorkspaceRoot2 = string;
export type Method94 = "workspace/resolve";
export type WorkspaceRoot3 = string;
export type Path4 = string;
export type Method95 = "settings/get";
export type SessionId51 = string | null;
export type ProjectId6 = string | null;
export type Workspace = string | null;
export type ThreadId4 = string | null;
export type TurnId3 = string | null;
export type Keys = string[] | null;
export type Method96 = "settings/set";
export type Layer = string;
export type SessionId52 = string | null;
export type ProjectId7 = string | null;
export type Workspace1 = string | null;
export type ThreadId5 = string | null;
export type TurnId4 = string | null;
export type Actor3 = string | null;
export type ApprovalId11 = string | null;
export type Method97 = "settings/models";
export type ProviderId1 = string;
export type ModelId1 = string;
export type MaxTokens = number | null;
export type SessionId53 = string | null;
export type Method98 = "settings/diagnose";
export type ErrorCode = string | null;
export type Message = string | null;
export type ProviderId2 = string | null;
export type ModelId2 = string | null;
export type Method99 = "settings/rollback";
export type SnapshotId = string;
export type SessionId54 = string | null;
export type Actor4 = string | null;
export type ApprovalId12 = string | null;
export type Method100 = "capabilities/list";
export type Kind = string | null;
export type AvailableOnly = boolean;
export type SessionId55 = string | null;
export type Method101 = "capabilities/get";
export type CapabilityId = string;
export type SessionId56 = string | null;
export type Method102 = "capabilities/set_enabled";
export type CapabilityId1 = string;
export type Enabled = boolean;
export type Authorize = boolean | null;
export type SessionId57 = string | null;
export type Actor5 = string | null;
export type ApprovalId13 = string | null;
export type Method103 = "capabilities/invoke";
export type CapabilityId2 = string;
export type SessionId58 = string | null;
export type TurnId5 = string | null;
export type Actor6 = string | null;
export type ApprovalId14 = string | null;
export type Background1 = boolean;
export type Method104 = "capabilities/cancel";
export type JobId = string;
export type SessionId59 = string | null;
export type Method105 = "capabilities/audit";
export type CapabilityId3 = string | null;
export type SessionId60 = string | null;
export type Method106 = "recovery/status";
export type SessionId61 = string | null;
export type Method107 = "recovery/replay";
export type SessionId62 = string;
export type Cursor3 = number | null;
export type Limit1 = number;
export type Method108 = "recovery/reclaim";
export type Method109 = "notifications/list";
export type SessionId63 = string | null;
export type IncludeAcked = boolean;
export type Method110 = "notifications/ack";
export type NotificationId = string;
export type Method111 = "notifications/cursor";
export type SessionId64 = string;
export type Cursor4 = number;
export type Method112 = "release/status";
export type Method113 = "release/diagnose";
export type ProtocolVersion1 = string | null;
export type AppserverVersion = string | null;
export type SchemaDigest = string | null;
export type Method114 = "cli/list";
export type Method115 = "cli/install";
export type Name2 = string;
export type Source1 = string;
export type Method116 = "cli/launch";
export type Name3 = string;
export type Args = string[] | null;
export type Method117 = "cli/uninstall";
export type Name4 = string;
export type Method118 = "cli/start";
export type Name5 = string;
export type Args1 = string[] | null;
export type Method119 = "cli/stop";
export type Name6 = string;
export type Method120 = "cli/decide";
export type Name7 = string;
export type HasSource = boolean;
export type HasSdk = boolean;
export type Method121 = "cli/record_failure";
export type Name8 = string;
export type Stage = string;
export type Reason3 = string;
export type NextStep = string | null;
export type Method122 = "schedule/list";
export type Method123 = "schedule/create";
export type Enabled1 = boolean;
export type Method124 = "schedule/update";
export type JobId1 = string;
export type Rule1 = {
  [k: string]: unknown;
} | null;
export type Action3 = {
  [k: string]: unknown;
} | null;
export type Enabled2 = boolean | null;
export type Method125 = "schedule/delete";
export type JobId2 = string;
export type Method126 = "schedule/toggle";
export type JobId3 = string;
export type Enabled3 = boolean | null;
export type Method127 = "plugin/list";
export type Method128 = "plugin/install";
export type Source2 = string;
export type Path5 = string | null;
export type Name9 = string | null;
export type Method129 = "plugin/uninstall";
export type Name10 = string;
export type KeepUserConfig = boolean;
export type Method130 = "plugin/toggle";
export type Name11 = string;
export type Enabled4 = boolean;
export type ProtocolNotification =
  | AgentEvent
  | MessageDelta
  | ProgressUpdate
  | ReasoningSnapshot
  | PlanUpdate
  | StepProgress
  | TaskStarted
  | ToolBegin
  | ToolEnd
  | ExecutionItem
  | TaskComplete
  | TokenUsage
  | AgentUsage
  | AgentNeedsInput
  | FinalAnswer
  | RecoveryStarted
  | RecoveryAnalyzing
  | RecoveryAttempt
  | RecoveryResolved
  | RecoveryExhausted
  | ErrorNotification
  | RunComplete
  | JobStatusUpdate
  | ServerHeartbeat
  | InitializedNotification
  | ProcessStarted
  | ProcessShutdown
  | RecoveryRequired
  | ProcessFailed
  | WorkspaceChanged;
export type Method131 =
  | "event/agent_started"
  | "event/agent_tool"
  | "event/agent_progress"
  | "event/agent_done"
  | "event/agent_paused"
  | "event/agent_cancelled"
  | "event/agent_budget_exceeded"
  | "event/agent_denied"
  | "event/agent_routed"
  | "event/agent_team_created";
export type SessionId65 = string;
export type AgentId2 = string;
export type RunId = string | null;
export type Seq = number;
export type ExperimentTag = ("E0" | "E1" | "E2") | null;
export type CacheMissWarning = boolean;
export type TokensUsed = number | null;
export type BudgetUsed = number | null;
export type Source3 = ("internal" | "bridge") | null;
export type RoutingReason = string | null;
export type Method132 = "event/message_delta";
export type SessionId66 = string;
export type Text4 = string;
export type Method133 = "event/progress";
export type SessionId67 = string;
export type Text5 = string;
export type Method134 = "event/reasoning_snapshot";
export type SessionId68 = string;
export type Text6 = string;
export type Snapshot = boolean;
export type Method135 = "event/plan";
export type SessionId69 = string;
export type Steps1 = string[];
export type Method136 = "event/step";
export type SessionId70 = string;
export type Index = number;
export type Total = number;
export type Text7 = string;
export type Method137 = "event/task_started";
export type SessionId71 = string;
export type TaskId2 = string;
export type Title2 = string;
export type Method138 = "event/tool_begin";
export type SessionId72 = string;
export type CallId = string;
export type ToolName = string;
export type Method139 = "event/tool_end";
export type SessionId73 = string;
export type CallId1 = string;
export type Ok = boolean;
export type Summary = string;
export type Status1 = string | null;
export type Method140 = "event/execution";
export type SessionId74 = string;
export type TaskId3 = string;
export type Kind1 = string;
export type Origin = string;
export type Name12 = string;
export type Status2 = string;
export type ArgsSummary = string | null;
export type Risk = string | null;
export type Cwd1 = string | null;
export type EnvSummary = {
  [k: string]: string;
} | null;
export type ExitCode = number | null;
export type Unread = boolean;
export type Truncated = boolean;
export type Method141 = "event/task_complete";
export type SessionId75 = string;
export type TaskId4 = string;
export type Ok1 = boolean;
export type Method142 = "event/token_usage";
export type SessionId76 = string;
export type InputTokens = number | null;
export type OutputTokens = number | null;
export type CacheHitTokens = number | null;
export type CacheWriteTokens = number | null;
export type CacheHitRate = number | null;
export type ReportingStatus = "reported" | "partial" | "not_reported";
export type Method143 = "event/agent_usage";
export type SessionId77 = string;
export type Seq1 = number;
export type InputTokens1 = number | null;
export type OutputTokens1 = number | null;
export type CacheHitTokens1 = number | null;
export type CacheWriteTokens1 = number | null;
export type CacheHitRate1 = number | null;
export type ReportingStatus1 = ("reported" | "partial" | "not_reported") | null;
export type ContextUsed = number | null;
export type ContextWindow = number | null;
export type UsedPct = number | null;
export type Cost = number | null;
export type Currency = string | null;
export type CostAvailable = boolean;
export type Reason4 = string | null;
export type Method144 = "event/agent_needs_input";
export type SessionId78 = string | null;
export type RequestId6 = string | null;
export type Kind2 = "needs_input";
export type Preview = string | null;
export type Method145 = "event/final";
export type SessionId79 = string;
export type RunId1 = string;
export type Text8 = string;
export type Thinking = string | null;
export type InputTokens2 = number | null;
export type OutputTokens2 = number | null;
export type CacheHitTokens2 = number | null;
export type CacheWriteTokens2 = number | null;
export type CacheHitRate2 = number | null;
export type ReportingStatus2 = "reported" | "partial" | "not_reported";
export type SessionSchemaVersion = number | null;
export type SessionId80 = string;
export type RunId2 = string;
export type RecoveryId = string;
export type EventId = string;
export type Seq2 = number;
export type Timestamp = string;
export type Method146 = "event/recovery_started";
export type SourceCallId = string;
export type RecoveryKind = "transport_retry" | "model_recovery" | "graph_replan";
export type ErrorKind = string;
export type MaxAttempts = number;
export type SessionId81 = string;
export type RunId3 = string;
export type RecoveryId1 = string;
export type EventId1 = string;
export type Seq3 = number;
export type Timestamp1 = string;
export type Method147 = "event/recovery_analyzing";
export type SessionId82 = string;
export type RunId4 = string;
export type RecoveryId2 = string;
export type EventId2 = string;
export type Seq4 = number;
export type Timestamp2 = string;
export type Method148 = "event/recovery_attempt";
export type Attempt = number;
export type Strategy = "same_tool" | "corrected_arguments" | "alternative_tool" | "retry_task" | "replan";
export type ReplacementCallId = string | null;
export type DisplaySummary = string;
export type SessionId83 = string;
export type RunId5 = string;
export type RecoveryId3 = string;
export type EventId3 = string;
export type Seq5 = number;
export type Timestamp3 = string;
export type Method149 = "event/recovery_resolved";
export type Attempts = number;
export type DisplaySummary1 = string;
export type SessionId84 = string;
export type RunId6 = string;
export type RecoveryId4 = string;
export type EventId4 = string;
export type Seq6 = number;
export type Timestamp4 = string;
export type Method150 = "event/recovery_exhausted";
export type Attempts1 = number;
export type FinalError = string;
export type Method151 = "event/error";
export type SessionId85 = string;
export type Message1 = string;
export type RunId7 = string | null;
export type Status3 = ("succeeded" | "failed" | "cancelled" | "timed_out") | null;
export type Method152 = "event/done";
export type SessionId86 = string;
export type RunId8 = string;
export type Status4 = "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method153 = "event/job_status";
export type SessionId87 = string;
export type JobId4 = string;
export type State =
  "submitted" | "queued" | "running" | "approval" | "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method154 = "event/server_heartbeat";
export type UptimeSeconds = number;
export type ActiveJobs = number;
export type Degraded = boolean;
export type Method155 = "initialized";
export type ProtocolVersion2 = string;
export type ServerVersion = string;
export type Method156 = "event/process_started";
export type Pid = number;
export type StartedAt = number;
export type InstancePolicy = string;
export type Method157 = "event/process_shutdown";
export type Reason5 = string;
export type Graceful = boolean;
export type Method158 = "event/recovery_required";
export type SessionId88 = string;
export type PreviousStatus = string;
export type Status5 = string;
export type Method159 = "event/process_failed";
export type Reason6 = string;
export type ErrorCode1 = string;
export type Method160 = "event/workspace_changed";
export type ProjectId8 = string;
export type WorkspaceRoot4 = string;
export type DisplayName1 = string;
export type ServerRequestMessage = ApprovalRequest | ApprovalResponse | QuestionRequest | QuestionResponse;
export type Method161 = "approval/request";
export type SessionId89 = string;
export type RequestId7 = string;
export type RiskLevel = "READ" | "WRITE" | "DANGER";
export type Action4 = string;
export type RequestId8 = string;
export type Decision1 = "approved" | "rejected" | "allow_once" | "always_allow_level";
export type Method162 = "question/request";
export type SessionId90 = string;
export type QuestionId = string;
export type Question = string;
export type Header = string;
export type Label = string;
export type Value = string;
export type Options = QuestionOption[];
export type InputType = "choice" | "text";
export type QuestionId1 = string;
export type Answer = string | null;
export type Cancelled = boolean;
export type TimedOut = boolean;
export type Unavailable = boolean;
/**
 * Phase F expert-team types (F3). Not a session envelope; discriminated wire messages still use method on ClientRequest / ProtocolNotification / ServerRequestMessage.
 */
export type AgentProtocol =
  | AgentSpec
  | SopStage
  | TeamSpec
  | DelegateRequest
  | DelegateResult
  | ConsultRequest
  | VerdictRecord
  | TeamEvent
  | RoutingDecision
  | BridgeBudget
  | TaskDelegate
  | BridgeProgress
  | BridgeToolCall
  | BridgePlan
  | BridgeResult
  | BridgeAbort;
export type Role = string;
export type DisplayName2 = string;
export type Goal1 = string;
export type Backstory = string;
export type Constraints = string[];
export type Model1 = string | null;
export type Tools = string[] | null;
export type PromptStage = string;
export type Mechanical = boolean;
export type MemoryScope = "private" | "shared";
export type TimeoutS = number;
export type TokenBudget = number | null;
export type MayConsult = string[];
export type Name13 = string;
export type Role1 = string;
export type ExpectedOutput = string;
export type ContextKeys = string[];
export type OutputKey = string;
export type VerifyBeforeNext = string[];
export type AuditAfterVerify = boolean;
export type NextOnSuccess = string | null;
export type NextOnFailure = string | null;
export type MaxRetries = number;
export type Name14 = string;
export type DisplayName3 = string;
export type Description = string;
export type Members = AgentSpec[];
export type Stages = SopStage[];
export type EntryStage = string;
export type TotalTokenBudget = number;
export type TotalTimeoutS = number;
export type MaxDelegations = number;
export type Method163 = "agents/delegate";
export type SessionId91 = string;
export type RequestId9 = string;
export type ToRole = string;
export type Stage1 = string;
export type Task = string;
export type ExpectedOutput1 = string;
export type ContextKeys1 = string[];
export type Depth = number;
export type RequestId10 = string;
export type Role2 = string;
export type Ok2 = boolean;
export type Answer1 = string;
export type Error = string;
export type ToolsUsed = string[];
export type TokensUsed1 = number;
export type DurationS = number;
export type Method164 = "agents/consult";
export type SessionId92 = string;
export type RequestId11 = string;
export type FromRole = string;
export type ToRole1 = string;
export type Question1 = string;
export type Stage2 = string;
export type SubjectHash = string;
export type AuditorRole = string;
export type Passed = boolean;
export type Findings = string[];
export type CreatedAt = number;
export type Method165 = "event/team";
export type SessionId93 = string;
export type Role3 = string;
export type Stage3 = string;
export type Phase =
  | "stage_started"
  | "delegated"
  | "consulted"
  | "verified"
  | "audited"
  | "stage_completed"
  | "failed"
  | "budget_exceeded"
  | "team_completed";
export type Detail = string;
export type Mode1 = "solo" | "team" | "team_multi";
export type DecidedBy = "user" | "heuristic" | "llm" | "default";
export type Reason7 = string;
export type TokensUsed2 = number;
export type ExperimentTag1 = "E0" | "E1" | "E2";
export type Task1 = string;
export type Tokens = number;
export type TimeoutS1 = number;
export type Method166 = "task_delegate";
export type TaskId5 = string;
export type ParentId = string | null;
export type Goal2 = string;
export type ContextRefs = string[];
export type Acceptance1 = string[];
export type Tools1 = string[];
export type Method167 = "progress";
export type TaskId6 = string;
export type Status6 = "running" | "blocked" | "done" | "failed";
export type Stage4 = string;
export type Percent = number;
export type EtaS = number | null;
export type Notes = string;
export type Method168 = "tool_call";
export type TaskId7 = string;
export type Tool = string;
export type Status7 = "running" | "done" | "failed";
export type ResultRef = string;
export type Method169 = "plan";
export type TaskId8 = string;
export type Steps2 = string[];
export type Files = string[];
export type EstTokens = number;
export type Ack = boolean;
export type Method170 = "result";
export type TaskId9 = string;
export type Ok3 = boolean;
export type Summary1 = string;
export type ArtifactPaths = string[];
export type TokensUsed3 = number;
export type DurationS1 = number;
export type Method171 = "abort";
export type TaskId10 = string;
export type Reason8 = "budget" | "timeout" | "user";
export type Partial = boolean;
/**
 * PhaseG-B2 initialize result, capability snapshot, and stable error payload. Not a session envelope.
 */
export type HandshakeProtocol =
  | CapabilitySnapshot
  | ModelProviderSummary
  | ModelSummary
  | PermissionProfileSummary
  | PackageCompatibility
  | InitializeResult
  | ThreadMetadata
  | ProtocolErrorData;
export type Threads = boolean;
export type ThreadFork = boolean;
export type BackgroundTurns = boolean;
export type BackgroundTasks = boolean;
export type CommandExecution = boolean;
export type FileChanges = boolean;
export type Review = boolean;
export type ReviewComments = boolean;
export type Checkpoint = boolean;
export type GitHunkActions = boolean;
export type Worktree = boolean;
export type FilePreview = boolean;
export type Settings = boolean;
export type Browser = boolean;
export type Mcp = boolean;
export type Skills = boolean;
export type CapabilityPanel = boolean;
export type MultiAgent = boolean;
export type MultiModel = boolean;
export type Vision = boolean;
/**
 * Wire name approval.auto_review.
 */
export type ApprovalAutoReview = boolean;
export type ProviderId3 = string;
export type ModelId3 = string | null;
export type ModelContextWindow = number | null;
export type ModelMaxOutputTokens = number | null;
export type LimitSource = string | null;
export type IsFallback = boolean;
export type Warning = string | null;
export type ProviderId4 = string;
export type ModelId4 = string;
export type ModelContextWindow1 = number | null;
export type ModelMaxOutputTokens1 = number | null;
export type ResolvedMaxTokens = number | null;
export type LimitSource1 = string | null;
export type IsFallback1 = boolean;
export type Warning1 = string | null;
export type MatchedCatalogKey = string | null;
export type KnownModel = boolean;
export type FamilyPattern = string | null;
export type ProfileId1 = string;
export type Selectable = boolean;
export type Description1 = string;
export type Platform = string;
export type Platforms = string[];
export type AppserverVersion1 = string;
export type ProtocolVersion3 = string;
export type SchemaDigest1 = string;
export type Python = string | null;
export type Compatible = boolean;
export type Runtimes = {
  [k: string]: {
    [k: string]: unknown;
  };
} | null;
export type ProtocolVersion4 = string;
export type ProtocolMin = string;
export type ProtocolMax = string;
export type ServerName = string;
export type ServerVersion1 = string;
export type ModelProviders = ModelProviderSummary[];
export type PermissionProfiles = PermissionProfileSummary[];
export type DeletedAt = string | null;
export type RestoredAt = string | null;
export type ListCategory = string | null;
export type AssociatedFiles = string[] | null;
export type ErrorCode2 =
  | "PROTOCOL_MISMATCH"
  | "UNSUPPORTED"
  | "OVERLOADED"
  | "CONFIGURATION_MISSING"
  | "TIMEOUT"
  | "CLOSED"
  | "NOT_INITIALIZED";
export type Retryable = boolean;
export type ProtocolVersion5 = string;
export type ProtocolMin1 = string;
export type ProtocolMax1 = string;
export type ServerVersion2 = string | null;
export type Details1 = {
  [k: string]: unknown;
} | null;

/**
 * JSON-RPC handshake on connect (future ``python -m appserver``).
 *
 * ``client_name`` / ``client_version`` identify the OpenTUI or Desktop client;
 * ``protocol_version`` must fall in ``PROTOCOL_VERSION_MIN``..``MAX`` (empty
 * is unspecified/legacy); unknown extra fields are ignored.
 * ``capabilities`` is an optional client feature manifest (unused in HTTP mode).
 * ``client_info`` / ``client_capabilities`` / ``requested_features`` are
 * PhaseG-B2 optional fields (G §5.1); they do not replace the older keys.
 */
export interface InitializeRequest {
  method?: Method;
  client_name: ClientName;
  client_version: ClientVersion;
  protocol_version: ProtocolVersion;
  capabilities?: Capabilities;
  client_info?: ClientInfo;
  client_capabilities?: ClientCapabilities;
  requested_features?: RequestedFeatures;
  [k: string]: unknown;
}
/**
 * Bind a workspace and chat namespace (maps ``_activate_session`` in api_server.py).
 *
 * ``workspace_root`` is the repo root passed to AgentV2 tools (today ``Path.cwd()``);
 * ``model`` optionally overrides the default from ``config/settings.py``.
 */
export interface NewSessionRequest {
  method?: Method1;
  workspace_root: WorkspaceRoot;
  model?: Model;
  [k: string]: unknown;
}
/**
 * One user turn (maps ``POST /chat`` ``ChatRequest`` in api_server.py).
 *
 * ``session_id`` uses ``memory.long_term.validate_session_id``; ``text`` is
 * ``ChatRequest.message``; ``timeout_seconds`` mirrors execution tool timeout
 * semantics when appserver enforces wall-clock limits.
 * ``mode`` selects AgentV2 run mode; ``thinking_expanded`` gates reasoning
 * stream emission on ``ProtocolTui``.
 */
export interface PromptRequest {
  method?: Method2;
  session_id: SessionId;
  text: Text;
  timeout_seconds?: TimeoutSeconds;
  mode?: Mode;
  thinking_expanded?: ThinkingExpanded;
  [k: string]: unknown;
}
/**
 * Cancel the in-flight run (maps ``POST /cancel`` + ``Session.interrupt`` in api_server.py).
 *
 * ``session_id`` matches the active ``ChatRequest.session_id`` namespace.
 */
export interface InterruptRequest {
  method?: Method3;
  session_id: SessionId1;
  [k: string]: unknown;
}
/**
 * Sync OpenTUI /thinking expand state into appserver ProtocolTui.
 *
 * ``expanded`` mirrors the client Thought panel; when a prompt is in flight the
 * bound worker TUI is updated so mid-run expand can push an accumulated snapshot.
 */
export interface SetThinkingExpandedRequest {
  method?: Method4;
  session_id: SessionId2;
  expanded: Expanded;
  [k: string]: unknown;
}
/**
 * Pre-bootstrap AgentV2 for a session so the first prompt is not cold-start.
 *
 * Maps appserver ``AgentHost.ensure_bootstrapped`` without running a user turn.
 */
export interface WarmSessionRequest {
  method?: Method5;
  session_id: SessionId3;
  timeout_seconds?: TimeoutSeconds1;
  [k: string]: unknown;
}
/**
 * Select a model for one task without changing the global CLI default.
 *
 * Maps ``session/set_model``. The worker rejects this request while its
 * prompt is active; the selected model is persisted on the task summary.
 */
export interface SessionSetModelRequest {
  method?: Method6;
  session_id: SessionId4;
  model_id: ModelId;
  [k: string]: unknown;
}
/**
 * List persisted Desktop tasks without exposing workspace contents.
 */
export interface SessionsListRequest {
  method?: Method7;
  include_trashed?: IncludeTrashed;
  include_archived?: IncludeArchived;
  workspace_root?: WorkspaceRoot1;
  project_id?: ProjectId;
  status?: Status;
  updated_after?: UpdatedAfter;
  updated_before?: UpdatedBefore;
  created_after?: CreatedAfter;
  created_before?: CreatedBefore;
  parent_session_id?: ParentSessionId;
  [k: string]: unknown;
}
/**
 * Replay persisted task events after a cursor.
 */
export interface SessionEventsRequest {
  method?: Method8;
  session_id: SessionId5;
  cursor?: Cursor;
  [k: string]: unknown;
}
/**
 * Rename a Desktop task; workspace files are never touched.
 */
export interface SessionRenameRequest {
  method?: Method9;
  session_id: SessionId6;
  title: Title;
  [k: string]: unknown;
}
/**
 * Soft-delete a Desktop task into Recently Deleted.
 */
export interface SessionTrashRequest {
  method?: Method10;
  session_id: SessionId7;
  [k: string]: unknown;
}
/**
 * Restore a soft-deleted Desktop task.
 */
export interface SessionRestoreRequest {
  method?: Method11;
  session_id: SessionId8;
  [k: string]: unknown;
}
/**
 * Permanently delete only a previously trashed task.
 */
export interface SessionPurgeRequest {
  method?: Method12;
  session_id: SessionId9;
  confirm_purge?: ConfirmPurge;
  [k: string]: unknown;
}
/**
 * Soft-delete a thread (sets deleted_at).
 *
 * Maps ``thread/delete``.
 */
export interface ThreadDeleteRequest {
  method?: Method13;
  session_id: SessionId10;
  [k: string]: unknown;
}
/**
 * Restore a soft-deleted thread.
 *
 * Maps ``thread/restore``.
 */
export interface ThreadRestoreRequest {
  method?: Method14;
  session_id: SessionId11;
  [k: string]: unknown;
}
/**
 * Permanently purge a soft-deleted thread.
 *
 * Maps ``thread/purge``.
 */
export interface ThreadPurgeRequest {
  method?: Method15;
  session_id: SessionId12;
  confirm_purge?: ConfirmPurge1;
  paths?: Paths;
  [k: string]: unknown;
}
/**
 * List soft-deleted threads.
 *
 * Maps ``thread/list_deleted``.
 */
export interface ThreadListDeletedRequest {
  method?: Method16;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 fork a thread. Parent events and status stay unchanged.
 */
export interface SessionForkRequest {
  method?: Method17;
  session_id: SessionId13;
  [k: string]: unknown;
}
/**
 * GX8 message-level fork. Distinct from session/fork (whole-thread copy).
 */
export interface ThreadForkRequest {
  method?: Method18;
  thread_id: ThreadId;
  message_id: MessageId;
  edited_text?: EditedText;
  [k: string]: unknown;
}
/**
 * GX8 pin/unpin. Operation, not an optional field substitute.
 */
export interface ThreadPinRequest {
  method?: Method19;
  thread_id: ThreadId1;
  pinned?: Pinned;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 parent/child tree. Additive; does not replace child_sessions/list.
 */
export interface SessionTreeRequest {
  method?: Method20;
  session_id: SessionId14;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 archive. Not delete; recoverable via unarchive.
 */
export interface SessionArchiveRequest {
  method?: Method21;
  session_id: SessionId15;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 restore an archived thread to the active list.
 */
export interface SessionUnarchiveRequest {
  method?: Method22;
  session_id: SessionId16;
  [k: string]: unknown;
}
/**
 * Paginate persisted items (events) after a cursor.
 */
export interface SessionItemsRequest {
  method?: Method23;
  session_id: SessionId17;
  cursor?: Cursor1;
  limit?: Limit;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 start a turn. Wraps session/prompt without replacing it.
 */
export interface TurnStartRequest {
  method?: Method24;
  session_id: SessionId18;
  text: Text1;
  request_id?: RequestId;
  timeout_seconds?: TimeoutSeconds2;
  [k: string]: unknown;
}
/**
 * Append steering text to an in-flight turn. No-op if not running.
 */
export interface TurnSteerRequest {
  method?: Method25;
  session_id: SessionId19;
  text: Text2;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 interrupt a running turn. Wraps session/interrupt.
 */
export interface TurnInterruptRequest {
  method?: Method26;
  session_id: SessionId20;
  [k: string]: unknown;
}
/**
 * Retry last turn. Same request_id returns the stored result.
 */
export interface TurnRetryRequest {
  method?: Method27;
  session_id: SessionId21;
  request_id: RequestId1;
  text?: Text3;
  [k: string]: unknown;
}
/**
 * PhaseG-B6 user-initiated command. Distinct from agent tool calls.
 */
export interface CommandStartRequest {
  method?: Method28;
  session_id: SessionId22;
  command: Command;
  cwd?: Cwd;
  background?: Background;
  timeout_seconds?: TimeoutSeconds3;
  approval_id?: ApprovalId;
  actor?: Actor;
  project_id?: ProjectId1;
  expand_sandbox?: ExpandSandbox;
  expand_writable_roots?: ExpandWritableRoots;
  expand_network?: ExpandNetwork;
  network?: Network;
  writable_roots?: WritableRoots;
  [k: string]: unknown;
}
/**
 * List tool/command/background items for one session.
 */
export interface ExecutionListRequest {
  method?: Method29;
  session_id: SessionId23;
  include_completed?: IncludeCompleted;
  [k: string]: unknown;
}
/**
 * Stop one running tool/command/background task.
 */
export interface ExecutionStopRequest {
  method?: Method30;
  session_id: SessionId24;
  task_id: TaskId;
  [k: string]: unknown;
}
/**
 * Read persisted stdout/stderr after the process has exited.
 */
export interface ExecutionOutputRequest {
  method?: Method31;
  session_id: SessionId25;
  task_id: TaskId1;
  [k: string]: unknown;
}
/**
 * PhaseG-B7 read current permission profile and policy version.
 */
export interface PermissionGetRequest {
  method?: Method32;
  [k: string]: unknown;
}
/**
 * PhaseG-B7 set a selectable profile. full_access is rejected.
 */
export interface PermissionSetRequest {
  method?: Method33;
  profile_id: ProfileId;
  scopes?: Scopes;
  [k: string]: unknown;
}
/**
 * Durable scoped allow used only by allow_scoped_actions.
 */
export interface PermissionScopeGrant {
  action: Action;
  scope?: Scope;
  project_id?: ProjectId2;
  expires_at?: ExpiresAt;
  [k: string]: unknown;
}
/**
 * Record an approval decision. One allow does not reuse.
 */
export interface ApprovalDecideRequest {
  method?: Method34;
  session_id: SessionId26;
  action: Action1;
  decision: Decision;
  actor?: Actor1;
  scope?: Scope1;
  expires_at?: ExpiresAt1;
  turn_id?: TurnId;
  project_id?: ProjectId3;
  reviewer_id?: ReviewerId;
  reason?: Reason;
  original_approval_id?: OriginalApprovalId;
  expand_sandbox?: ExpandSandbox1;
  expand_writable_roots?: ExpandWritableRoots1;
  expand_network?: ExpandNetwork1;
  [k: string]: unknown;
}
/**
 * Revoke a previous allow. Restart only keeps persisted non-revoked policy.
 */
export interface ApprovalRevokeRequest {
  method?: Method35;
  approval_id: ApprovalId1;
  [k: string]: unknown;
}
/**
 * List approval audit records for a session or all.
 */
export interface ApprovalAuditRequest {
  method?: Method36;
  session_id?: SessionId27;
  [k: string]: unknown;
}
/**
 * GX2 UI preset mapped onto B7 policy. Request must use ``preset`` not ``mode``.
 */
export interface ApprovalModeSetRequest {
  method?: Method37;
  preset: Preset;
  [k: string]: unknown;
}
/**
 * GX2-PROTO: session-scoped unlock of B7 full_access. Restart clears it.
 */
export interface ApprovalFullAccessEnableRequest {
  method?: Method38;
  actor: Actor2;
  source?: Source;
  [k: string]: unknown;
}
/**
 * PhaseG-B8 start a read-only review. Does not modify the working tree.
 */
export interface ReviewStartRequest {
  method?: Method39;
  request_id: RequestId2;
  session_id?: SessionId28;
  thread_id?: ThreadId2;
  turn_id?: TurnId1;
  scope?: Scope2;
  base_ref?: BaseRef;
  head_ref?: HeadRef;
  paths?: Paths1;
  criteria?: Criteria;
  reviewer?: Reviewer;
  [k: string]: unknown;
}
/**
 * Reconnect/read a persisted review without restarting it.
 */
export interface ReviewReadRequest {
  method?: Method40;
  review_id: ReviewId;
  after_sequence?: AfterSequence;
  [k: string]: unknown;
}
/**
 * Line comment bound to review/finding/file hash/line range.
 */
export interface ReviewCommentRequest {
  method?: Method41;
  review_id: ReviewId1;
  file: File;
  start_line: StartLine;
  end_line: EndLine;
  body: Body;
  finding_id?: FindingId;
  file_hash?: FileHash;
  [k: string]: unknown;
}
/**
 * GX3 add inline comment. Does not replace review/comment.
 */
export interface ReviewCommentAddRequest {
  method?: Method42;
  review_id: ReviewId2;
  file: File1;
  line: Line;
  hunk_hash: HunkHash;
  body: Body1;
  [k: string]: unknown;
}
/**
 * GX3 resolve an inline comment (open or stale).
 */
export interface ReviewCommentResolveRequest {
  method?: Method43;
  comment_id: CommentId;
  [k: string]: unknown;
}
/**
 * Create a session checkpoint without writing the workspace tree.
 */
export interface CheckpointCreateRequest {
  method?: Method44;
  session_id: SessionId29;
  reason?: Reason1;
  turn_id?: TurnId2;
  [k: string]: unknown;
}
/**
 * List checkpoints for a session.
 */
export interface CheckpointListRequest {
  method?: Method45;
  session_id: SessionId30;
  [k: string]: unknown;
}
/**
 * Read one checkpoint payload.
 */
export interface CheckpointReadRequest {
  method?: Method46;
  checkpoint_id: CheckpointId;
  session_id: SessionId31;
  [k: string]: unknown;
}
/**
 * Restore a session to a previous checkpoint.
 */
export interface CheckpointRestoreRequest {
  method?: Method47;
  checkpoint_id: CheckpointId1;
  session_id: SessionId32;
  approval_id?: ApprovalId2;
  [k: string]: unknown;
}
/**
 * GX4 named snapshot. Distinct from automatic checkpoint/create.
 */
export interface CheckpointSnapshotCreateRequest {
  method?: Method48;
  name: Name;
  session_id: SessionId33;
  user_prompt?: UserPrompt;
  [k: string]: unknown;
}
/**
 * GX4 rewind: pre-rewind snapshot + B8 restore + projection + refill.
 */
export interface CheckpointRewindRequest {
  method?: Method49;
  checkpoint_id: CheckpointId2;
  confirm: Confirm;
  session_id: SessionId34;
  [k: string]: unknown;
}
/**
 * GX9 export thread plan to markdown under RXYCODE_DATA_DIR/plans.
 */
export interface PlanPersistRequest {
  method?: Method50;
  thread_id: ThreadId3;
  title: Title1;
  goal: Goal;
  steps: Steps;
  acceptance: Acceptance;
  [k: string]: unknown;
}
/**
 * GX9 start execution from a persisted plan. Requires confirm=true.
 */
export interface PlanImplementRequest {
  method?: Method51;
  plan_id: PlanId;
  confirm: Confirm1;
  [k: string]: unknown;
}
/**
 * Stage git paths inside the workspace.
 */
export interface GitStageRequest {
  method?: Method52;
  session_id: SessionId35;
  paths: Paths2;
  approval_id?: ApprovalId3;
  [k: string]: unknown;
}
/**
 * Unstage git paths inside the workspace.
 */
export interface GitUnstageRequest {
  method?: Method53;
  session_id: SessionId36;
  paths: Paths3;
  approval_id?: ApprovalId4;
  [k: string]: unknown;
}
/**
 * Revert git hunks or paths inside the workspace.
 */
export interface GitRevertRequest {
  method?: Method54;
  session_id: SessionId37;
  paths: Paths4;
  hunk_index?: HunkIndex;
  approval_id?: ApprovalId5;
  [k: string]: unknown;
}
/**
 * Preview a workspace file for the client.
 */
export interface FilePreviewRequest {
  method?: Method55;
  session_id: SessionId38;
  path: Path;
  [k: string]: unknown;
}
/**
 * List a workspace directory tree.
 */
export interface FileTreeRequest {
  method?: Method56;
  session_id: SessionId39;
  path?: Path1;
  [k: string]: unknown;
}
/**
 * Open a workspace file in an external program after confirm.
 */
export interface FileOpenExternalRequest {
  method?: Method57;
  session_id: SessionId40;
  path: Path2;
  confirm?: Confirm2;
  [k: string]: unknown;
}
/**
 * List git worktrees for the session workspace.
 */
export interface WorktreeListRequest {
  method?: Method58;
  session_id: SessionId41;
  [k: string]: unknown;
}
/**
 * Switch the session onto an existing git worktree.
 */
export interface WorktreeOpenRequest {
  method?: Method59;
  session_id: SessionId42;
  worktree_id: WorktreeId;
  [k: string]: unknown;
}
/**
 * Create a git worktree under the workspace.
 */
export interface WorktreeCreateRequest {
  method?: Method60;
  session_id: SessionId43;
  dest: Dest;
  branch?: Branch;
  approval_id?: ApprovalId6;
  [k: string]: unknown;
}
/**
 * Close a git worktree after optional confirm.
 */
export interface WorktreeCloseRequest {
  method?: Method61;
  session_id: SessionId44;
  worktree_id: WorktreeId1;
  force?: Force;
  confirm?: Confirm3;
  approval_id?: ApprovalId7;
  [k: string]: unknown;
}
/**
 * Prune stale git worktrees after confirm.
 */
export interface WorktreePruneRequest {
  method?: Method62;
  session_id: SessionId45;
  confirm?: Confirm4;
  approval_id?: ApprovalId8;
  [k: string]: unknown;
}
/**
 * Hand a worktree path to another session after confirm.
 */
export interface WorktreeHandoffRequest {
  method?: Method63;
  session_id: SessionId46;
  target_session: TargetSession;
  target_path: TargetPath;
  confirm?: Confirm5;
  approval_id?: ApprovalId9;
  [k: string]: unknown;
}
/**
 * Roll back a worktree handoff.
 */
export interface WorktreeHandoffRollbackRequest {
  method?: Method64;
  handoff_id: HandoffId;
  session_id: SessionId47;
  approval_id?: ApprovalId10;
  [k: string]: unknown;
}
/**
 * Discover worker-owned isolated-subagent feature flags.
 */
export interface SubagentCapabilityRequest {
  method?: Method65;
  root_session_id?: RootSessionId;
  [k: string]: unknown;
}
/**
 * List visible AgentDefinitions for mention/autocomplete UI.
 */
export interface SubagentsListRequest {
  method?: Method66;
  root_session_id: RootSessionId1;
  [k: string]: unknown;
}
/**
 * Explicit user ``@agent`` invocation in a Primary/Child tree.
 */
export interface AgentInvokeRequest {
  method?: Method67;
  root_session_id: RootSessionId2;
  parent_session_id?: ParentSessionId1;
  request_id?: RequestId3;
  agent_id: AgentId;
  prompt: Prompt;
  output_schema?: OutputSchema;
  requested_budget?: RequestedBudget;
  requested_workspace?: RequestedWorkspace;
  [k: string]: unknown;
}
/**
 * Start a model-driven isolated child task asynchronously.
 */
export interface TaskStartRequest {
  method?: Method68;
  root_session_id: RootSessionId3;
  parent_session_id?: ParentSessionId2;
  request_id?: RequestId4;
  agent_id: AgentId1;
  prompt: Prompt1;
  output_schema?: OutputSchema1;
  requested_budget?: RequestedBudget1;
  requested_workspace?: RequestedWorkspace1;
  [k: string]: unknown;
}
/**
 * Return the current persisted child-session tree for a Primary.
 */
export interface ChildSessionsListRequest {
  method?: Method69;
  root_session_id: RootSessionId4;
  [k: string]: unknown;
}
/**
 * Replay child events after a monotonic cursor for reconnect recovery.
 */
export interface ChildSessionEventsRequest {
  method?: Method70;
  root_session_id: RootSessionId5;
  cursor?: Cursor2;
  [k: string]: unknown;
}
/**
 * Cancel one child subtree, or all children when session_id is omitted.
 */
export interface ChildSessionCancelRequest {
  method?: Method71;
  root_session_id: RootSessionId6;
  session_id?: SessionId48;
  [k: string]: unknown;
}
/**
 * Retry a terminal child with its immutable original request snapshot.
 */
export interface ChildSessionRetryRequest {
  method?: Method72;
  root_session_id: RootSessionId7;
  session_id: SessionId49;
  request_id?: RequestId5;
  [k: string]: unknown;
}
/**
 * Graceful appserver shutdown (future ``appserver`` lifespan teardown).
 *
 * ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
 */
export interface ShutdownRequest {
  method?: Method73;
  reason?: Reason2;
  [k: string]: unknown;
}
/**
 * List configured models with provider grouping and Phase 3 limit summary.
 *
 * Maps ``models/list``. Response carries ``models``, ``active``, ``recent``.
 */
export interface ModelsListRequest {
  method?: Method74;
  [k: string]: unknown;
}
/**
 * List provider connection presets (base URL only, no model ids).
 *
 * Maps ``models/presets``; the client discovers ids via ``models/discover``.
 */
export interface ModelsPresetsRequest {
  method?: Method75;
  [k: string]: unknown;
}
/**
 * Probe a provider catalogue with a credential; never persists.
 *
 * Maps ``models/discover``. ``api_key`` is never stored or echoed.
 */
export interface ModelsDiscoverRequest {
  method?: Method76;
  api_key: ApiKey;
  base_url: BaseUrl;
  [k: string]: unknown;
}
/**
 * Probe credentials in memory and persist a working model mapping.
 *
 * Maps ``models/onboard``. ``api_key`` is stored by the backend
 * credential_store (Windows DPAPI) and never returned.
 */
export interface ModelsOnboardRequest {
  method?: Method77;
  provider_model_id: ProviderModelId;
  api_key: ApiKey1;
  base_url: BaseUrl1;
  nickname?: Nickname;
  [k: string]: unknown;
}
/**
 * Probe + persist multiple models with one credential.
 *
 * Maps ``models/onboard_batch``.
 */
export interface ModelsOnboardBatchRequest {
  method?: Method78;
  api_key: ApiKey2;
  base_url: BaseUrl2;
  model_ids: ModelIds;
  provider_id?: ProviderId;
  provider_name?: ProviderName;
  active_model_id?: ActiveModelId;
  skip_probe?: SkipProbe;
  [k: string]: unknown;
}
/**
 * Remove a model by config key.
 *
 * Maps ``models/remove``.
 */
export interface ModelsRemoveRequest {
  method?: Method79;
  id: Id;
  [k: string]: unknown;
}
/**
 * Switch the active model.
 *
 * Maps ``models/set_active``.
 *
 * ``effort``（optional_field，2026-08-12）：同时设置全局思考强度档位
 * （/effort 命令与设置页共用；厂商档位值或 fast/balanced/deep 抽象档位）。
 * 缺失 = 不改动当前档位。
 */
export interface ModelsSetActiveRequest {
  method?: Method80;
  id: Id1;
  effort?: Effort;
  [k: string]: unknown;
}
/**
 * Live credential test for an existing model.
 *
 * Maps ``models/test_connection``.
 */
export interface ModelsTestConnectionRequest {
  method?: Method81;
  id: Id2;
  [k: string]: unknown;
}
/**
 * Store/refresh a model API key (backend DPAPI, never echoed).
 *
 * Maps ``credentials/upsert``.
 */
export interface CredentialsUpsertRequest {
  method?: Method82;
  id: Id3;
  api_key: ApiKey3;
  [k: string]: unknown;
}
/**
 * Clear a model's stored API key reference.
 *
 * Maps ``credentials/delete``.
 */
export interface CredentialsDeleteRequest {
  method?: Method83;
  id: Id4;
  [k: string]: unknown;
}
/**
 * F18b: list registered teams as L1 summaries only.
 */
export interface TeamListRequest {
  method?: Method84;
  [k: string]: unknown;
}
/**
 * F18b: list groups and member team ids.
 */
export interface TeamGroupsRequest {
  method?: Method85;
  [k: string]: unknown;
}
/**
 * F18b: rename a user group. Builtin groups are rejected.
 */
export interface TeamGroupRenameRequest {
  method?: Method86;
  old: Old;
  new: New;
  [k: string]: unknown;
}
/**
 * F18b: expose F18 team_install two-step ask. No second approval UX.
 */
export interface TeamInstallRequest {
  method?: Method87;
  name: Name1;
  url?: Url;
  confirm?: Confirm6;
  group?: Group;
  [k: string]: unknown;
}
/**
 * F18b: set the session's active team. Idempotent.
 */
export interface TeamSetActiveRequest {
  method?: Method88;
  session_id: SessionId50;
  team_id: TeamId;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 list recent projects.
 */
export interface ProjectListRequest {
  method?: Method89;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 add a local directory. Display name is separate from path.
 */
export interface ProjectAddRequest {
  method?: Method90;
  path: Path3;
  display_name?: DisplayName;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 drop from recent list. Never deletes user files.
 */
export interface ProjectRemoveRequest {
  method?: Method91;
  project_id: ProjectId4;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 switch the active project without changing process cwd.
 */
export interface ProjectSetActiveRequest {
  method?: Method92;
  project_id: ProjectId5;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 report branch/worktree or NOT_A_GIT_REPO. Never chdir.
 */
export interface WorkspaceStatusRequest {
  method?: Method93;
  workspace_root: WorkspaceRoot2;
  [k: string]: unknown;
}
/**
 * Reject paths that escape the bound workspace, including symlink hops.
 */
export interface WorkspaceResolveRequest {
  method?: Method94;
  workspace_root: WorkspaceRoot3;
  path: Path4;
  [k: string]: unknown;
}
/**
 * Resolve settings through global→project→workspace→thread/turn.
 *
 * Maps ``settings/get``. Same interpretation for Desktop and CLI.
 */
export interface SettingsGetRequest {
  method?: Method95;
  session_id?: SessionId51;
  project_id?: ProjectId6;
  workspace?: Workspace;
  thread_id?: ThreadId4;
  turn_id?: TurnId3;
  keys?: Keys;
  [k: string]: unknown;
}
/**
 * Write one explicit settings layer. Secrets are not stored in values.
 *
 * Maps ``settings/set``. Requires B7 permission. Changing model does not
 * rewrite existing thread history.
 */
export interface SettingsSetRequest {
  method?: Method96;
  layer: Layer;
  values: Values;
  session_id?: SessionId52;
  project_id?: ProjectId7;
  workspace?: Workspace1;
  thread_id?: ThreadId5;
  turn_id?: TurnId4;
  actor?: Actor3;
  approval_id?: ApprovalId11;
  [k: string]: unknown;
}
export interface Values {
  [k: string]: unknown;
}
/**
 * Look up a real model_id in ModelCatalog and return a ModelSummary.
 *
 * Maps ``settings/models``. Unknown models keep their id and use the high
 * fallback with warning; they are not rewritten to a known catalog model.
 */
export interface SettingsModelsRequest {
  method?: Method97;
  provider_id: ProviderId1;
  model_id: ModelId1;
  max_tokens?: MaxTokens;
  session_id?: SessionId53;
  [k: string]: unknown;
}
/**
 * Classify key-invalid, quota, and model-unavailable as distinct codes.
 *
 * Maps ``settings/diagnose``. Messages are redacted.
 */
export interface SettingsDiagnoseRequest {
  method?: Method98;
  error_code?: ErrorCode;
  message?: Message;
  provider_id?: ProviderId2;
  model_id?: ModelId2;
  [k: string]: unknown;
}
/**
 * Restore a settings snapshot written before a previous set.
 *
 * Maps ``settings/rollback``. Requires B7 permission.
 */
export interface SettingsRollbackRequest {
  method?: Method99;
  snapshot_id: SnapshotId;
  session_id?: SessionId54;
  actor?: Actor4;
  approval_id?: ApprovalId12;
  [k: string]: unknown;
}
/**
 * Project skills, MCP servers, and the browser placeholder.
 *
 * Maps ``capabilities/list``. Unavailable items have available=false.
 */
export interface CapabilitiesListRequest {
  method?: Method100;
  kind?: Kind;
  available_only?: AvailableOnly;
  session_id?: SessionId55;
  [k: string]: unknown;
}
/**
 * Read one capability projection.
 *
 * Maps ``capabilities/get``.
 */
export interface CapabilitiesGetRequest {
  method?: Method101;
  capability_id: CapabilityId;
  session_id?: SessionId56;
  [k: string]: unknown;
}
/**
 * Enable or authorize a capability. Browser cannot be turned into a bypass.
 *
 * Maps ``capabilities/set_enabled``.
 */
export interface CapabilitiesSetEnabledRequest {
  method?: Method102;
  capability_id: CapabilityId1;
  enabled: Enabled;
  authorize?: Authorize;
  session_id?: SessionId57;
  actor?: Actor5;
  approval_id?: ApprovalId13;
  [k: string]: unknown;
}
/**
 * Invoke a capability as a normal Tool/Approval/Review job.
 *
 * Maps ``capabilities/invoke``. Failures are terminal and cancellable.
 */
export interface CapabilitiesInvokeRequest {
  method?: Method103;
  capability_id: CapabilityId2;
  session_id?: SessionId58;
  turn_id?: TurnId5;
  actor?: Actor6;
  approval_id?: ApprovalId14;
  background?: Background1;
  [k: string]: unknown;
}
/**
 * Cancel an in-flight capability job so the Thread does not stay stuck.
 *
 * Maps ``capabilities/cancel``.
 */
export interface CapabilitiesCancelRequest {
  method?: Method104;
  job_id: JobId;
  session_id?: SessionId59;
  [k: string]: unknown;
}
/**
 * Return copyable, source-located capability audit records.
 *
 * Maps ``capabilities/audit``.
 */
export interface CapabilitiesAuditRequest {
  method?: Method105;
  capability_id?: CapabilityId3;
  session_id?: SessionId60;
  [k: string]: unknown;
}
/**
 * Project session recovery state. Incomplete never becomes completed.
 *
 * Maps ``recovery/status``.
 */
export interface RecoveryStatusRequest {
  method?: Method106;
  session_id?: SessionId61;
  [k: string]: unknown;
}
/**
 * Replay events after a saved cursor and persist the new cursor.
 *
 * Maps ``recovery/replay``.
 */
export interface RecoveryReplayRequest {
  method?: Method107;
  session_id: SessionId62;
  cursor?: Cursor3;
  limit?: Limit1;
  [k: string]: unknown;
}
/**
 * Mark orphan incomplete sessions recovery_required.
 *
 * Maps ``recovery/reclaim``.
 */
export interface RecoveryReclaimRequest {
  method?: Method108;
  [k: string]: unknown;
}
/**
 * List deduped recovery notifications.
 *
 * Maps ``notifications/list``.
 */
export interface NotificationsListRequest {
  method?: Method109;
  session_id?: SessionId63;
  include_acked?: IncludeAcked;
  [k: string]: unknown;
}
/**
 * Acknowledge one notification.
 *
 * Maps ``notifications/ack``.
 */
export interface NotificationsAckRequest {
  method?: Method110;
  notification_id: NotificationId;
  [k: string]: unknown;
}
/**
 * Persist a disconnect cursor for later replay.
 *
 * Maps ``notifications/cursor``.
 */
export interface NotificationsCursorRequest {
  method?: Method111;
  session_id: SessionId64;
  cursor: Cursor4;
  [k: string]: unknown;
}
/**
 * Advertise runtime/protocol/schema bind.
 *
 * Maps ``release/status``.
 */
export interface ReleaseStatusRequest {
  method?: Method112;
  [k: string]: unknown;
}
/**
 * Diagnose client/server version or schema mismatch.
 *
 * Maps ``release/diagnose``.
 */
export interface ReleaseDiagnoseRequest {
  method?: Method113;
  protocol_version?: ProtocolVersion1;
  appserver_version?: AppserverVersion;
  schema_digest?: SchemaDigest;
  [k: string]: unknown;
}
/**
 * List CLI-Hub software ids. Names stay out of tools/registry.
 *
 * Maps ``cli/list``.
 */
export interface CliListRequest {
  method?: Method114;
  [k: string]: unknown;
}
/**
 * Install one CLI into an isolated venv.
 *
 * Maps ``cli/install``.
 */
export interface CliInstallRequest {
  method?: Method115;
  name: Name2;
  source?: Source1;
  [k: string]: unknown;
}
/**
 * Launch an installed CLI software id.
 *
 * Maps ``cli/launch``.
 */
export interface CliLaunchRequest {
  method?: Method116;
  name: Name3;
  args?: Args;
  [k: string]: unknown;
}
/**
 * Uninstall one isolated CLI software id.
 *
 * Maps ``cli/uninstall``.
 */
export interface CliUninstallRequest {
  method?: Method117;
  name: Name4;
  [k: string]: unknown;
}
/**
 * Start a long-running CLI process in its isolated venv.
 *
 * Maps ``cli/start``.
 */
export interface CliStartRequest {
  method?: Method118;
  name: Name5;
  args?: Args1;
  [k: string]: unknown;
}
/**
 * Stop a long-running CLI process.
 *
 * Maps ``cli/stop``.
 */
export interface CliStopRequest {
  method?: Method119;
  name: Name6;
  [k: string]: unknown;
}
/**
 * C-C registry-first decision for a software id.
 *
 * Maps ``cli/decide``.
 */
export interface CliDecideRequest {
  method?: Method120;
  name: Name7;
  has_source?: HasSource;
  has_sdk?: HasSdk;
  [k: string]: unknown;
}
/**
 * C-E generate-failure ladder record.
 *
 * Maps ``cli/record_failure``.
 */
export interface CliRecordFailureRequest {
  method?: Method121;
  name: Name8;
  stage: Stage;
  reason: Reason3;
  next_step?: NextStep;
  [k: string]: unknown;
}
/**
 * List application-layer scheduled jobs.
 *
 * Maps ``schedule/list``.
 */
export interface ScheduleListRequest {
  method?: Method122;
  [k: string]: unknown;
}
/**
 * Create an interval or at-time job.
 *
 * Maps ``schedule/create``.
 */
export interface ScheduleCreateRequest {
  method?: Method123;
  rule: Rule;
  action: Action2;
  enabled?: Enabled1;
  [k: string]: unknown;
}
export interface Rule {
  [k: string]: unknown;
}
export interface Action2 {
  [k: string]: unknown;
}
/**
 * Update one scheduled job.
 *
 * Maps ``schedule/update``.
 */
export interface ScheduleUpdateRequest {
  method?: Method124;
  job_id: JobId1;
  rule?: Rule1;
  action?: Action3;
  enabled?: Enabled2;
  [k: string]: unknown;
}
/**
 * Delete one scheduled job.
 *
 * Maps ``schedule/delete``.
 */
export interface ScheduleDeleteRequest {
  method?: Method125;
  job_id: JobId2;
  [k: string]: unknown;
}
/**
 * Enable or disable one scheduled job.
 *
 * Maps ``schedule/toggle``.
 */
export interface ScheduleToggleRequest {
  method?: Method126;
  job_id: JobId3;
  enabled?: Enabled3;
  [k: string]: unknown;
}
/**
 * List installed plugins.
 *
 * Maps ``plugin/list``.
 */
export interface PluginListRequest {
  method?: Method127;
  [k: string]: unknown;
}
/**
 * Install a plugin from a local directory or configured registry.
 *
 * Maps ``plugin/install``.
 */
export interface PluginInstallRequest {
  method?: Method128;
  source: Source2;
  path?: Path5;
  name?: Name9;
  [k: string]: unknown;
}
/**
 * Unregister a plugin and optionally keep user.json.
 *
 * Maps ``plugin/uninstall``.
 */
export interface PluginUninstallRequest {
  method?: Method129;
  name: Name10;
  keep_user_config?: KeepUserConfig;
  [k: string]: unknown;
}
/**
 * Enable or disable a plugin via B11 capability/set_enabled.
 *
 * Maps ``plugin/toggle``.
 */
export interface PluginToggleRequest {
  method?: Method130;
  name: Name11;
  enabled: Enabled4;
  [k: string]: unknown;
}
/**
 * Runtime agent event (Phase E4; E-layer bus carries these).
 *
 * Field matrix (PHASE-E §4.1, authoritative):
 *   method                | experiment_tag | cache_miss | tokens | budget | source | routing_reason
 *   ----------------------|--------------- |------------|--------|--------|--------|---------------
 *   agent_started         | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_tool            | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_progress        | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_done            | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_paused          | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_cancelled       | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_budget_exceeded | opt            | opt        | **req  | **req  | opt    | forbid
 *   agent_denied          | opt            | opt        | req*   | req*   | opt    | forbid
 *   agent_routed          | **req          | opt        | req*   | req*   | opt    | **req
 *   agent_team_created    | forbid         | opt        | req*   | req*   | opt    | forbid
 *
 * ``req*`` = the E3 runtime always writes these (0 at spawn, monotonic);
 * the schema compatibility layer allows them to be absent (historical
 * events).  ``**req`` = hard requirement at this layer; ``forbid`` =
 * carrying the field is rejected.  ``tokens_used``/``budget_used`` are
 * strict ints (bool/str/float rejected) and non-negative cumulative
 * snapshots.  ``source`` distinguishes bridge-replayed events; unknown
 * values are rejected on construction and deserialization.
 */
export interface AgentEvent {
  method: Method131;
  session_id: SessionId65;
  agent_id: AgentId2;
  run_id?: RunId;
  payload?: Payload;
  seq: Seq;
  experiment_tag?: ExperimentTag;
  cache_miss_warning?: CacheMissWarning;
  tokens_used?: TokensUsed;
  budget_used?: BudgetUsed;
  source?: Source3;
  routing_reason?: RoutingReason;
  [k: string]: unknown;
}
export interface Payload {
  [k: string]: unknown;
}
/**
 * SSE ``type: token`` via ``StreamTUI._buffer("token")`` / flush (api_server.py).
 */
export interface MessageDelta {
  method?: Method132;
  session_id: SessionId66;
  text: Text4;
  [k: string]: unknown;
}
/**
 * SSE ``type: progress`` from ``StreamTUI.write_progress`` (api_server.py).
 */
export interface ProgressUpdate {
  method?: Method133;
  session_id: SessionId67;
  text: Text5;
  [k: string]: unknown;
}
/**
 * SSE ``type: reasoning`` with ``snapshot: true`` from ``StreamTUI._emit_thinking_snapshot`` (api_server.py).
 */
export interface ReasoningSnapshot {
  method?: Method134;
  session_id: SessionId68;
  text: Text6;
  snapshot?: Snapshot;
  [k: string]: unknown;
}
/**
 * SSE ``type: plan`` from ``StreamTUI.write_plan`` (api_server.py).
 */
export interface PlanUpdate {
  method?: Method135;
  session_id: SessionId69;
  steps: Steps1;
  [k: string]: unknown;
}
/**
 * SSE ``type: step`` from ``StreamTUI.write_step`` (api_server.py).
 */
export interface StepProgress {
  method?: Method136;
  session_id: SessionId70;
  index: Index;
  total: Total;
  text: Text7;
  [k: string]: unknown;
}
/**
 * Structured task boundary for LangGraph runs (future emit from chat worker).
 */
export interface TaskStarted {
  method?: Method137;
  session_id: SessionId71;
  task_id: TaskId2;
  title: Title2;
  [k: string]: unknown;
}
/**
 * SSE ``type: tool_call`` from ``StreamTUI.write_tool_call`` (api_server.py).
 */
export interface ToolBegin {
  method?: Method138;
  session_id: SessionId72;
  call_id: CallId;
  tool_name: ToolName;
  arguments?: Arguments;
  [k: string]: unknown;
}
export interface Arguments {
  [k: string]: unknown;
}
/**
 * SSE ``type: tool_result`` from ``StreamTUI.write_tool_result`` (api_server.py).
 */
export interface ToolEnd {
  method?: Method139;
  session_id: SessionId73;
  call_id: CallId1;
  ok: Ok;
  summary: Summary;
  status?: Status1;
  [k: string]: unknown;
}
/**
 * PhaseG-B6 tool/command/background item snapshot.
 */
export interface ExecutionItem {
  method?: Method140;
  session_id: SessionId74;
  task_id: TaskId3;
  kind: Kind1;
  origin: Origin;
  name: Name12;
  status: Status2;
  args_summary?: ArgsSummary;
  risk?: Risk;
  cwd?: Cwd1;
  env_summary?: EnvSummary;
  exit_code?: ExitCode;
  unread?: Unread;
  truncated?: Truncated;
  [k: string]: unknown;
}
/**
 * Structured task completion paired with ``TaskStarted``.
 */
export interface TaskComplete {
  method?: Method141;
  session_id: SessionId75;
  task_id: TaskId4;
  ok: Ok1;
  [k: string]: unknown;
}
/**
 * Reported token usage; unknown provider values stay explicitly null.
 */
export interface TokenUsage {
  method?: Method142;
  session_id: SessionId76;
  input_tokens?: InputTokens;
  output_tokens?: OutputTokens;
  cache_hit_tokens?: CacheHitTokens;
  cache_write_tokens?: CacheWriteTokens;
  cache_hit_rate?: CacheHitRate;
  reporting_status?: ReportingStatus;
  [k: string]: unknown;
}
export interface AgentUsage {
  method?: Method143;
  session_id: SessionId77;
  seq: Seq1;
  input_tokens?: InputTokens1;
  output_tokens?: OutputTokens1;
  cache_hit_tokens?: CacheHitTokens1;
  cache_write_tokens?: CacheWriteTokens1;
  cache_hit_rate?: CacheHitRate1;
  reporting_status?: ReportingStatus1;
  context_used?: ContextUsed;
  context_window?: ContextWindow;
  used_pct?: UsedPct;
  cost?: Cost;
  currency?: Currency;
  cost_available?: CostAvailable;
  reason?: Reason4;
  [k: string]: unknown;
}
/**
 * GX13 agent waiting for approval or a question. Additive new_event.
 */
export interface AgentNeedsInput {
  method?: Method144;
  session_id?: SessionId78;
  request_id?: RequestId6;
  kind?: Kind2;
  preview?: Preview;
  [k: string]: unknown;
}
/**
 * SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py).
 */
export interface FinalAnswer {
  method?: Method145;
  session_id: SessionId79;
  run_id: RunId1;
  text: Text8;
  thinking?: Thinking;
  input_tokens?: InputTokens2;
  output_tokens?: OutputTokens2;
  cache_hit_tokens?: CacheHitTokens2;
  cache_write_tokens?: CacheWriteTokens2;
  cache_hit_rate?: CacheHitRate2;
  reporting_status?: ReportingStatus2;
  session_schema_version?: SessionSchemaVersion;
  [k: string]: unknown;
}
/**
 * Recovery budget opened after an operational failure.
 */
export interface RecoveryStarted {
  session_id: SessionId80;
  run_id: RunId2;
  recovery_id: RecoveryId;
  event_id: EventId;
  seq: Seq2;
  timestamp: Timestamp;
  method?: Method146;
  source_call_id: SourceCallId;
  recovery_kind: RecoveryKind;
  error_kind: ErrorKind;
  max_attempts: MaxAttempts;
  [k: string]: unknown;
}
/**
 * Recovery planner is selecting the next user-safe strategy.
 */
export interface RecoveryAnalyzing {
  session_id: SessionId81;
  run_id: RunId3;
  recovery_id: RecoveryId1;
  event_id: EventId1;
  seq: Seq3;
  timestamp: Timestamp1;
  method?: Method147;
  [k: string]: unknown;
}
/**
 * One concrete recovery strategy has been scheduled.
 */
export interface RecoveryAttempt {
  session_id: SessionId82;
  run_id: RunId4;
  recovery_id: RecoveryId2;
  event_id: EventId2;
  seq: Seq4;
  timestamp: Timestamp2;
  method?: Method148;
  attempt: Attempt;
  strategy: Strategy;
  replacement_call_id?: ReplacementCallId;
  display_summary: DisplaySummary;
  [k: string]: unknown;
}
/**
 * Recovery completed and the task returned to normal execution.
 */
export interface RecoveryResolved {
  session_id: SessionId83;
  run_id: RunId5;
  recovery_id: RecoveryId3;
  event_id: EventId3;
  seq: Seq5;
  timestamp: Timestamp3;
  method?: Method149;
  attempts: Attempts;
  display_summary: DisplaySummary1;
  [k: string]: unknown;
}
/**
 * Recovery budget was exhausted and a terminal error may be shown.
 */
export interface RecoveryExhausted {
  session_id: SessionId84;
  run_id: RunId6;
  recovery_id: RecoveryId4;
  event_id: EventId4;
  seq: Seq6;
  timestamp: Timestamp4;
  method?: Method150;
  attempts: Attempts1;
  final_error: FinalError;
  [k: string]: unknown;
}
/**
 * SSE ``type: error`` from ``StreamTUI.write_error`` and chat worker (api_server.py).
 */
export interface ErrorNotification {
  method?: Method151;
  session_id: SessionId85;
  message: Message1;
  run_id?: RunId7;
  status?: Status3;
  [k: string]: unknown;
}
/**
 * SSE ``type: done`` from chat stream teardown (api_server.py).
 */
export interface RunComplete {
  method?: Method152;
  session_id: SessionId86;
  run_id: RunId8;
  status: Status4;
  [k: string]: unknown;
}
/**
 * Background job state for watchdog / appserver (submitted|running|failed).
 */
export interface JobStatusUpdate {
  method?: Method153;
  session_id: SessionId87;
  job_id: JobId4;
  state: State;
  [k: string]: unknown;
}
/**
 * Periodic appserver liveness signal (T4 watchdog).
 */
export interface ServerHeartbeat {
  method?: Method154;
  uptime_seconds: UptimeSeconds;
  active_jobs: ActiveJobs;
  degraded: Degraded;
  [k: string]: unknown;
}
/**
 * PhaseG-B2 handshake complete. No response expected.
 */
export interface InitializedNotification {
  method?: Method155;
  protocol_version: ProtocolVersion2;
  server_version: ServerVersion;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 appserver process is up and holding the instance lock.
 */
export interface ProcessStarted {
  method?: Method156;
  pid: Pid;
  started_at: StartedAt;
  instance_policy?: InstancePolicy;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 graceful shutdown. Incomplete work is not marked completed.
 */
export interface ProcessShutdown {
  method?: Method157;
  reason: Reason5;
  graceful: Graceful;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 restart found an unfinished turn. UI must not show success.
 */
export interface RecoveryRequired {
  method?: Method158;
  session_id: SessionId88;
  previous_status: PreviousStatus;
  status?: Status5;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 failed to become the instance (lock or boot).
 */
export interface ProcessFailed {
  method?: Method159;
  reason: Reason6;
  error_code: ErrorCode1;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 active workspace changed. Does not chdir the process.
 */
export interface WorkspaceChanged {
  method?: Method160;
  project_id: ProjectId8;
  workspace_root: WorkspaceRoot4;
  display_name: DisplayName1;
  [k: string]: unknown;
}
/**
 * Maps ``ApprovalRequest.to_event()`` SSE in core/safety/approval.py.
 */
export interface ApprovalRequest {
  method?: Method161;
  session_id: SessionId89;
  request_id: RequestId7;
  risk_level: RiskLevel;
  action: Action4;
  details?: Details;
  [k: string]: unknown;
}
export interface Details {
  [k: string]: unknown;
}
/**
 * Reply consumed by ``POST /approve`` (api_server.py) / ``SseApproval``.
 */
export interface ApprovalResponse {
  request_id: RequestId8;
  decision: Decision1;
  [k: string]: unknown;
}
/**
 * Maps ``QuestionRequest.to_event()`` in core/question.py.
 */
export interface QuestionRequest {
  method?: Method162;
  session_id: SessionId90;
  question_id: QuestionId;
  question: Question;
  header?: Header;
  options?: Options;
  input_type?: InputType;
  [k: string]: unknown;
}
/**
 * One choice row in ``QuestionRequest.options`` (``core/question.py`` ``QuestionOption.to_event``).
 */
export interface QuestionOption {
  label: Label;
  value: Value;
  [k: string]: unknown;
}
/**
 * Answer payload resolved by ``SseQuestionBroker.resolve`` (core/question.py).
 */
export interface QuestionResponse {
  question_id: QuestionId1;
  answer?: Answer;
  cancelled?: Cancelled;
  timed_out?: TimedOut;
  unavailable?: Unavailable;
  [k: string]: unknown;
}
/**
 * 一个角色的静态定义。Spec 不可变；运行时实例是 AgentRuntime。
 */
export interface AgentSpec {
  role: Role;
  display_name: DisplayName2;
  goal: Goal1;
  backstory?: Backstory;
  constraints?: Constraints;
  model?: Model1;
  tools?: Tools;
  prompt_stage: PromptStage;
  mechanical?: Mechanical;
  memory_scope?: MemoryScope;
  timeout_s?: TimeoutS;
  token_budget?: TokenBudget;
  may_consult?: MayConsult;
  extra?: Extra;
  [k: string]: unknown;
}
export interface Extra {
  [k: string]: unknown;
}
/**
 * SOP 的一个阶段。
 *
 * 确定性状态机的一个节点（决策 DC4）。阶段转移由 next_on_success /
 * next_on_failure 静态决定，不由 LLM 现场发挥。
 */
export interface SopStage {
  name: Name13;
  role: Role1;
  expected_output: ExpectedOutput;
  context_keys?: ContextKeys;
  output_key: OutputKey;
  verify_before_next?: VerifyBeforeNext;
  audit_after_verify?: AuditAfterVerify;
  next_on_success?: NextOnSuccess;
  next_on_failure?: NextOnFailure;
  max_retries?: MaxRetries;
  [k: string]: unknown;
}
/**
 * 一支专家团 = 成员 + SOP。
 *
 * 团长不在 members 里：它是运行时构造的 Coordinator（DC2；不干活、
 * 工具集为空）。WorkBuddy 详情页把主理人放在成员首位——那是产品展示，
 * 不是本协议的成员表。F18 用 extra['ecosystem.is_leader'] 标记展示用主理人。
 */
export interface TeamSpec {
  name: Name14;
  display_name: DisplayName3;
  description?: Description;
  members: Members;
  stages: Stages;
  entry_stage: EntryStage;
  total_token_budget?: TotalTokenBudget;
  total_timeout_s?: TotalTimeoutS;
  max_delegations?: MaxDelegations;
  extra?: Extra1;
  [k: string]: unknown;
}
export interface Extra1 {
  [k: string]: unknown;
}
/**
 * 团长 → 成员：下发一个自包含任务。
 *
 * "自包含"是 Anthropic 的建议：目标、输出格式、工具清单、完成边界都要
 * 写清楚，否则成员会重复劳动或者不知道什么时候算完。
 */
export interface DelegateRequest {
  method?: Method163;
  session_id: SessionId91;
  request_id: RequestId9;
  to_role: ToRole;
  stage: Stage1;
  task: Task;
  expected_output: ExpectedOutput1;
  context_keys?: ContextKeys1;
  depth?: Depth;
  [k: string]: unknown;
}
/**
 * 成员 → 团长：一次委派的产出。
 */
export interface DelegateResult {
  request_id: RequestId10;
  role: Role2;
  ok: Ok2;
  answer?: Answer1;
  error?: Error;
  tools_used?: ToolsUsed;
  tokens_used?: TokensUsed1;
  duration_s?: DurationS;
  [k: string]: unknown;
}
/**
 * 成员 → 团长 → 另一个成员：咨询。
 *
 * 这是"coder 发现问题去找 architect 沟通"。它**不是**成员直连——
 * 团长会校验 may_consult、记录、计入预算，再转发（决策 DC2）。
 */
export interface ConsultRequest {
  method?: Method164;
  session_id: SessionId92;
  request_id: RequestId11;
  from_role: FromRole;
  to_role: ToRole1;
  question: Question1;
  stage: Stage2;
  [k: string]: unknown;
}
/**
 * 审计结论，绑定被审对象的哈希。
 *
 * 抄 karajan-code：审计通过的是"这一份具体的产出"。产出变了，旧结论
 * 自动失效，防止"审计通过 → 又偷偷改了 → 直接提交"。
 */
export interface VerdictRecord {
  subject_hash: SubjectHash;
  auditor_role: AuditorRole;
  passed: Passed;
  findings?: Findings;
  created_at: CreatedAt;
  [k: string]: unknown;
}
/**
 * 推给客户端的编排层生命周期通知（F 层类型）。
 *
 * 与 PHASE-E E4 的 AgentEvent 分工：
 * - AgentEvent（E4）：运行时 event/agent_*
 * - TeamEvent（本类型）：编排层 event/team（及 event/team_*）
 * 建团信号走 event/agent_team_created，不在本类型重复。
 * F 层不得再定义名为 AgentEvent 的类型。
 */
export interface TeamEvent {
  method?: Method165;
  session_id: SessionId93;
  role: Role3;
  stage?: Stage3;
  phase: Phase;
  detail?: Detail;
  [k: string]: unknown;
}
/**
 * ModeRouter 的一次路由结论（F10/F13）。进 schema 供 CLI/Desktop 展示。
 */
export interface RoutingDecision {
  mode: Mode1;
  decided_by: DecidedBy;
  reason: Reason7;
  tokens_used?: TokensUsed2;
  experiment_tag?: ExperimentTag1;
  task?: Task1;
  [k: string]: unknown;
}
/**
 * F16 task_delegate.budget — inherits F9 fuses.
 */
export interface BridgeBudget {
  tokens?: Tokens;
  timeout_s?: TimeoutS1;
  [k: string]: unknown;
}
/**
 * Leader → Worker (F16). Lineage-only: refs, never conversation history.
 */
export interface TaskDelegate {
  method?: Method166;
  task_id: TaskId5;
  parent_id?: ParentId;
  goal: Goal2;
  context_refs?: ContextRefs;
  acceptance?: Acceptance1;
  tools?: Tools1;
  budget?: BridgeBudget;
  [k: string]: unknown;
}
/**
 * Worker → Leader streaming status. notes truncated to ~2k tokens.
 */
export interface BridgeProgress {
  method?: Method167;
  task_id: TaskId6;
  status: Status6;
  stage?: Stage4;
  percent?: Percent;
  eta_s?: EtaS;
  notes?: Notes;
  [k: string]: unknown;
}
/**
 * Worker → Leader. Large results go to result_ref, never inline.
 */
export interface BridgeToolCall {
  method?: Method168;
  task_id: TaskId7;
  tool: Tool;
  args?: Args2;
  status?: Status7;
  result_ref?: ResultRef;
  [k: string]: unknown;
}
export interface Args2 {
  [k: string]: unknown;
}
/**
 * Worker → Leader execution plan before work starts.
 */
export interface BridgePlan {
  method?: Method169;
  task_id: TaskId8;
  steps?: Steps2;
  files?: Files;
  est_tokens?: EstTokens;
  ack?: Ack;
  [k: string]: unknown;
}
/**
 * Worker → Leader. summary is 1–2k tokens; artifacts are paths.
 */
export interface BridgeResult {
  method?: Method170;
  task_id: TaskId9;
  ok: Ok3;
  summary?: Summary1;
  artifact_paths?: ArtifactPaths;
  tokens_used?: TokensUsed3;
  duration_s?: DurationS1;
  [k: string]: unknown;
}
/**
 * Leader → Worker. Sent before a hard kill.
 */
export interface BridgeAbort {
  method?: Method171;
  task_id: TaskId10;
  reason: Reason8;
  partial?: Partial;
  [k: string]: unknown;
}
/**
 * Honest capability flags. False means not implemented yet, not hidden.
 */
export interface CapabilitySnapshot {
  threads?: Threads;
  thread_fork?: ThreadFork;
  background_turns?: BackgroundTurns;
  background_tasks?: BackgroundTasks;
  command_execution?: CommandExecution;
  file_changes?: FileChanges;
  review?: Review;
  review_comments?: ReviewComments;
  checkpoint?: Checkpoint;
  git_hunk_actions?: GitHunkActions;
  worktree?: Worktree;
  file_preview?: FilePreview;
  settings?: Settings;
  browser?: Browser;
  mcp?: Mcp;
  skills?: Skills;
  capability_panel?: CapabilityPanel;
  multi_agent?: MultiAgent;
  multi_model?: MultiModel;
  vision?: Vision;
  "approval.auto_review"?: ApprovalAutoReview;
  [k: string]: unknown;
}
export interface ModelProviderSummary {
  provider_id: ProviderId3;
  model_id?: ModelId3;
  model_context_window?: ModelContextWindow;
  model_max_output_tokens?: ModelMaxOutputTokens;
  limit_source?: LimitSource;
  is_fallback?: IsFallback;
  warning?: Warning;
  [k: string]: unknown;
}
/**
 * PhaseG-B10 model limit summary. limit_source is the Phase 3 resolver source.
 */
export interface ModelSummary {
  provider_id: ProviderId4;
  model_id: ModelId4;
  model_context_window?: ModelContextWindow1;
  model_max_output_tokens?: ModelMaxOutputTokens1;
  resolved_max_tokens?: ResolvedMaxTokens;
  limit_source?: LimitSource1;
  is_fallback?: IsFallback1;
  warning?: Warning1;
  matched_catalog_key?: MatchedCatalogKey;
  known_model?: KnownModel;
  family_pattern?: FamilyPattern;
  [k: string]: unknown;
}
export interface PermissionProfileSummary {
  profile_id: ProfileId1;
  selectable: Selectable;
  description: Description1;
  [k: string]: unknown;
}
/**
 * PhaseG-B13 appserver/schema/runtime bind advertised at initialize.
 */
export interface PackageCompatibility {
  platform: Platform;
  platforms: Platforms;
  appserver_version: AppserverVersion1;
  protocol_version: ProtocolVersion3;
  schema_digest: SchemaDigest1;
  python?: Python;
  compatible?: Compatible;
  runtimes?: Runtimes;
  [k: string]: unknown;
}
/**
 * Additive initialize response. Old clients ignore unknown keys.
 */
export interface InitializeResult {
  protocol_version?: ProtocolVersion4;
  protocol_min?: ProtocolMin;
  protocol_max?: ProtocolMax;
  server_name?: ServerName;
  server_version?: ServerVersion1;
  capabilities: Capabilities1;
  capability_snapshot: CapabilitySnapshot;
  model_providers: ModelProviders;
  permission_profiles: PermissionProfiles;
  package?: PackageCompatibility | null;
  [k: string]: unknown;
}
export interface Capabilities1 {
  [k: string]: unknown;
}
/**
 * PhaseG-B17 thread recycle-bin metadata.
 */
export interface ThreadMetadata {
  deleted_at?: DeletedAt;
  restored_at?: RestoredAt;
  list_category?: ListCategory;
  associated_files?: AssociatedFiles;
  [k: string]: unknown;
}
/**
 * Machine-assertable error payload in JSON-RPC ``error.data``.
 */
export interface ProtocolErrorData {
  error_code: ErrorCode2;
  retryable: Retryable;
  protocol_version?: ProtocolVersion5;
  protocol_min?: ProtocolMin1;
  protocol_max?: ProtocolMax1;
  server_version?: ServerVersion2;
  details?: Details1;
  [k: string]: unknown;
}
