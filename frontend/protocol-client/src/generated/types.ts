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
  | SessionForkRequest
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
  | ReviewStartRequest
  | ReviewReadRequest
  | ReviewCommentRequest
  | CheckpointCreateRequest
  | CheckpointListRequest
  | CheckpointReadRequest
  | CheckpointRestoreRequest
  | GitStageRequest
  | GitUnstageRequest
  | GitRevertRequest
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
  | WorkspaceResolveRequest;
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
export type Method13 = "session/fork";
export type SessionId10 = string;
export type Method14 = "session/tree";
export type SessionId11 = string;
export type Method15 = "session/archive";
export type SessionId12 = string;
export type Method16 = "session/unarchive";
export type SessionId13 = string;
export type Method17 = "session/items";
export type SessionId14 = string;
export type Cursor1 = number;
export type Limit = number;
export type Method18 = "turn/start";
export type SessionId15 = string;
export type Text1 = string;
export type RequestId = string | null;
export type TimeoutSeconds2 = number | null;
export type Method19 = "turn/steer";
export type SessionId16 = string;
export type Text2 = string;
export type Method20 = "turn/interrupt";
export type SessionId17 = string;
export type Method21 = "turn/retry";
export type SessionId18 = string;
export type RequestId1 = string;
export type Text3 = string | null;
export type Method22 = "command/start";
export type SessionId19 = string;
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
export type Method23 = "execution/list";
export type SessionId20 = string;
export type IncludeCompleted = boolean;
export type Method24 = "execution/stop";
export type SessionId21 = string;
export type TaskId = string;
export type Method25 = "execution/output";
export type SessionId22 = string;
export type TaskId1 = string;
export type Method26 = "permission/get";
export type Method27 = "permission/set";
export type ProfileId = string;
export type Scopes = PermissionScopeGrant[] | null;
export type Action = string;
export type Scope = string | null;
export type ProjectId2 = string | null;
export type ExpiresAt = string | null;
export type Method28 = "approval/decide";
export type SessionId23 = string;
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
export type Method29 = "approval/revoke";
export type ApprovalId1 = string;
export type Method30 = "approval/audit";
export type SessionId24 = string | null;
export type Method31 = "review/start";
export type RequestId2 = string;
export type SessionId25 = string | null;
export type ThreadId = string | null;
export type TurnId1 = string | null;
export type Scope2 = string;
export type BaseRef = string | null;
export type HeadRef = string | null;
export type Paths = string[] | null;
export type Criteria = string[] | null;
export type Reviewer = {
  [k: string]: unknown;
} | null;
export type Method32 = "review/read";
export type ReviewId = string;
export type AfterSequence = number | null;
export type Method33 = "review/comment";
export type ReviewId1 = string;
export type File = string;
export type StartLine = number;
export type EndLine = number;
export type Body = string;
export type FindingId = string | null;
export type FileHash = string | null;
export type Method34 = "checkpoint/create";
export type SessionId26 = string;
export type Reason1 = string | null;
export type TurnId2 = string | null;
export type Method35 = "checkpoint/list";
export type SessionId27 = string;
export type Method36 = "checkpoint/read";
export type CheckpointId = string;
export type SessionId28 = string;
export type Method37 = "checkpoint/restore";
export type CheckpointId1 = string;
export type SessionId29 = string;
export type ApprovalId2 = string | null;
export type Method38 = "git/stage";
export type SessionId30 = string;
export type Paths1 = string[];
export type ApprovalId3 = string | null;
export type Method39 = "git/unstage";
export type SessionId31 = string;
export type Paths2 = string[];
export type ApprovalId4 = string | null;
export type Method40 = "git/revert";
export type SessionId32 = string;
export type Paths3 = string[];
export type HunkIndex = number | null;
export type ApprovalId5 = string | null;
export type Method41 = "subagents/capability";
export type RootSessionId = string | null;
export type Method42 = "subagents/list";
export type RootSessionId1 = string;
export type Method43 = "agent/invoke";
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
export type Method44 = "task/start";
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
export type Method45 = "child_sessions/list";
export type RootSessionId4 = string;
export type Method46 = "child_sessions/events";
export type RootSessionId5 = string;
export type Cursor2 = number;
export type Method47 = "child_sessions/cancel";
export type RootSessionId6 = string;
export type SessionId33 = string | null;
export type Method48 = "child_sessions/retry";
export type RootSessionId7 = string;
export type SessionId34 = string;
export type RequestId5 = string | null;
export type Method49 = "shutdown";
export type Reason2 = string | null;
export type Method50 = "models/list";
export type Method51 = "models/presets";
export type Method52 = "models/discover";
export type ApiKey = string;
export type BaseUrl = string;
export type Method53 = "models/onboard";
export type ProviderModelId = string;
export type ApiKey1 = string;
export type BaseUrl1 = string;
export type Nickname = string | null;
export type Method54 = "models/onboard_batch";
export type ApiKey2 = string;
export type BaseUrl2 = string;
export type ModelIds = string[];
export type ProviderId = string | null;
export type ProviderName = string | null;
export type ActiveModelId = string | null;
export type SkipProbe = boolean;
export type Method55 = "models/remove";
export type Id = string;
export type Method56 = "models/set_active";
export type Id1 = string;
export type Effort = string | null;
export type Method57 = "models/test_connection";
export type Id2 = string;
export type Method58 = "credentials/upsert";
export type Id3 = string;
export type ApiKey3 = string;
export type Method59 = "credentials/delete";
export type Id4 = string;
export type Method60 = "team/list";
export type Method61 = "team/groups";
export type Method62 = "team/group_rename";
export type Old = string;
export type New = string;
export type Method63 = "team/install";
export type Name = string;
export type Url = string;
export type Confirm = boolean;
export type Group = string;
export type Method64 = "team/set_active";
export type SessionId35 = string;
export type TeamId = string;
export type Method65 = "project/list";
export type Method66 = "project/add";
export type Path = string;
export type DisplayName = string | null;
export type Method67 = "project/remove";
export type ProjectId4 = string;
export type Method68 = "project/set_active";
export type ProjectId5 = string;
export type Method69 = "workspace/status";
export type WorkspaceRoot2 = string;
export type Method70 = "workspace/resolve";
export type WorkspaceRoot3 = string;
export type Path1 = string;
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
export type Method71 =
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
export type SessionId36 = string;
export type AgentId2 = string;
export type RunId = string | null;
export type Seq = number;
export type ExperimentTag = ("E0" | "E1" | "E2") | null;
export type CacheMissWarning = boolean;
export type TokensUsed = number | null;
export type BudgetUsed = number | null;
export type Source = ("internal" | "bridge") | null;
export type RoutingReason = string | null;
export type Method72 = "event/message_delta";
export type SessionId37 = string;
export type Text4 = string;
export type Method73 = "event/progress";
export type SessionId38 = string;
export type Text5 = string;
export type Method74 = "event/reasoning_snapshot";
export type SessionId39 = string;
export type Text6 = string;
export type Snapshot = boolean;
export type Method75 = "event/plan";
export type SessionId40 = string;
export type Steps = string[];
export type Method76 = "event/step";
export type SessionId41 = string;
export type Index = number;
export type Total = number;
export type Text7 = string;
export type Method77 = "event/task_started";
export type SessionId42 = string;
export type TaskId2 = string;
export type Title1 = string;
export type Method78 = "event/tool_begin";
export type SessionId43 = string;
export type CallId = string;
export type ToolName = string;
export type Method79 = "event/tool_end";
export type SessionId44 = string;
export type CallId1 = string;
export type Ok = boolean;
export type Summary = string;
export type Status1 = string | null;
export type Method80 = "event/execution";
export type SessionId45 = string;
export type TaskId3 = string;
export type Kind = string;
export type Origin = string;
export type Name1 = string;
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
export type Method81 = "event/task_complete";
export type SessionId46 = string;
export type TaskId4 = string;
export type Ok1 = boolean;
export type Method82 = "event/token_usage";
export type SessionId47 = string;
export type InputTokens = number | null;
export type OutputTokens = number | null;
export type CacheHitTokens = number | null;
export type CacheWriteTokens = number | null;
export type CacheHitRate = number | null;
export type ReportingStatus = "reported" | "partial" | "not_reported";
export type Method83 = "event/final";
export type SessionId48 = string;
export type RunId1 = string;
export type Text8 = string;
export type Thinking = string | null;
export type InputTokens1 = number | null;
export type OutputTokens1 = number | null;
export type CacheHitTokens1 = number | null;
export type CacheWriteTokens1 = number | null;
export type CacheHitRate1 = number | null;
export type ReportingStatus1 = "reported" | "partial" | "not_reported";
export type SessionSchemaVersion = number | null;
export type SessionId49 = string;
export type RunId2 = string;
export type RecoveryId = string;
export type EventId = string;
export type Seq1 = number;
export type Timestamp = string;
export type Method84 = "event/recovery_started";
export type SourceCallId = string;
export type RecoveryKind = "transport_retry" | "model_recovery" | "graph_replan";
export type ErrorKind = string;
export type MaxAttempts = number;
export type SessionId50 = string;
export type RunId3 = string;
export type RecoveryId1 = string;
export type EventId1 = string;
export type Seq2 = number;
export type Timestamp1 = string;
export type Method85 = "event/recovery_analyzing";
export type SessionId51 = string;
export type RunId4 = string;
export type RecoveryId2 = string;
export type EventId2 = string;
export type Seq3 = number;
export type Timestamp2 = string;
export type Method86 = "event/recovery_attempt";
export type Attempt = number;
export type Strategy = "same_tool" | "corrected_arguments" | "alternative_tool" | "retry_task" | "replan";
export type ReplacementCallId = string | null;
export type DisplaySummary = string;
export type SessionId52 = string;
export type RunId5 = string;
export type RecoveryId3 = string;
export type EventId3 = string;
export type Seq4 = number;
export type Timestamp3 = string;
export type Method87 = "event/recovery_resolved";
export type Attempts = number;
export type DisplaySummary1 = string;
export type SessionId53 = string;
export type RunId6 = string;
export type RecoveryId4 = string;
export type EventId4 = string;
export type Seq5 = number;
export type Timestamp4 = string;
export type Method88 = "event/recovery_exhausted";
export type Attempts1 = number;
export type FinalError = string;
export type Method89 = "event/error";
export type SessionId54 = string;
export type Message = string;
export type RunId7 = string | null;
export type Status3 = ("succeeded" | "failed" | "cancelled" | "timed_out") | null;
export type Method90 = "event/done";
export type SessionId55 = string;
export type RunId8 = string;
export type Status4 = "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method91 = "event/job_status";
export type SessionId56 = string;
export type JobId = string;
export type State =
  "submitted" | "queued" | "running" | "approval" | "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method92 = "event/server_heartbeat";
export type UptimeSeconds = number;
export type ActiveJobs = number;
export type Degraded = boolean;
export type Method93 = "initialized";
export type ProtocolVersion1 = string;
export type ServerVersion = string;
export type Method94 = "event/process_started";
export type Pid = number;
export type StartedAt = number;
export type InstancePolicy = string;
export type Method95 = "event/process_shutdown";
export type Reason3 = string;
export type Graceful = boolean;
export type Method96 = "event/recovery_required";
export type SessionId57 = string;
export type PreviousStatus = string;
export type Status5 = string;
export type Method97 = "event/process_failed";
export type Reason4 = string;
export type ErrorCode = string;
export type Method98 = "event/workspace_changed";
export type ProjectId6 = string;
export type WorkspaceRoot4 = string;
export type DisplayName1 = string;
export type ServerRequestMessage = ApprovalRequest | ApprovalResponse | QuestionRequest | QuestionResponse;
export type Method99 = "approval/request";
export type SessionId58 = string;
export type RequestId6 = string;
export type RiskLevel = "READ" | "WRITE" | "DANGER";
export type Action2 = string;
export type RequestId7 = string;
export type Decision1 = "approved" | "rejected" | "allow_once" | "always_allow_level";
export type Method100 = "question/request";
export type SessionId59 = string;
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
export type Goal = string;
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
export type Name2 = string;
export type Role1 = string;
export type ExpectedOutput = string;
export type ContextKeys = string[];
export type OutputKey = string;
export type VerifyBeforeNext = string[];
export type AuditAfterVerify = boolean;
export type NextOnSuccess = string | null;
export type NextOnFailure = string | null;
export type MaxRetries = number;
export type Name3 = string;
export type DisplayName3 = string;
export type Description = string;
export type Members = AgentSpec[];
export type Stages = SopStage[];
export type EntryStage = string;
export type TotalTokenBudget = number;
export type TotalTimeoutS = number;
export type MaxDelegations = number;
export type Method101 = "agents/delegate";
export type SessionId60 = string;
export type RequestId8 = string;
export type ToRole = string;
export type Stage = string;
export type Task = string;
export type ExpectedOutput1 = string;
export type ContextKeys1 = string[];
export type Depth = number;
export type RequestId9 = string;
export type Role2 = string;
export type Ok2 = boolean;
export type Answer1 = string;
export type Error = string;
export type ToolsUsed = string[];
export type TokensUsed1 = number;
export type DurationS = number;
export type Method102 = "agents/consult";
export type SessionId61 = string;
export type RequestId10 = string;
export type FromRole = string;
export type ToRole1 = string;
export type Question1 = string;
export type Stage1 = string;
export type SubjectHash = string;
export type AuditorRole = string;
export type Passed = boolean;
export type Findings = string[];
export type CreatedAt = number;
export type Method103 = "event/team";
export type SessionId62 = string;
export type Role3 = string;
export type Stage2 = string;
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
export type Reason5 = string;
export type TokensUsed2 = number;
export type ExperimentTag1 = "E0" | "E1" | "E2";
export type Task1 = string;
export type Tokens = number;
export type TimeoutS1 = number;
export type Method104 = "task_delegate";
export type TaskId5 = string;
export type ParentId = string | null;
export type Goal1 = string;
export type ContextRefs = string[];
export type Acceptance = string[];
export type Tools1 = string[];
export type Method105 = "progress";
export type TaskId6 = string;
export type Status6 = "running" | "blocked" | "done" | "failed";
export type Stage3 = string;
export type Percent = number;
export type EtaS = number | null;
export type Notes = string;
export type Method106 = "tool_call";
export type TaskId7 = string;
export type Tool = string;
export type Status7 = "running" | "done" | "failed";
export type ResultRef = string;
export type Method107 = "plan";
export type TaskId8 = string;
export type Steps1 = string[];
export type Files = string[];
export type EstTokens = number;
export type Ack = boolean;
export type Method108 = "result";
export type TaskId9 = string;
export type Ok3 = boolean;
export type Summary1 = string;
export type ArtifactPaths = string[];
export type TokensUsed3 = number;
export type DurationS1 = number;
export type Method109 = "abort";
export type TaskId10 = string;
export type Reason6 = "budget" | "timeout" | "user";
export type Partial = boolean;
/**
 * PhaseG-B2 initialize result, capability snapshot, and stable error payload. Not a session envelope.
 */
export type HandshakeProtocol =
  CapabilitySnapshot | ModelProviderSummary | PermissionProfileSummary | InitializeResult | ProtocolErrorData;
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
export type Browser = boolean;
export type Mcp = boolean;
export type Skills = boolean;
export type MultiAgent = boolean;
export type MultiModel = boolean;
export type Vision = boolean;
/**
 * Wire name approval.auto_review.
 */
export type ApprovalAutoReview = boolean;
export type ProviderId1 = string;
export type ModelId1 = string | null;
export type ModelContextWindow = number | null;
export type ModelMaxOutputTokens = number | null;
export type LimitSource = string | null;
export type IsFallback = boolean;
export type Warning = string | null;
export type ProfileId1 = string;
export type Selectable = boolean;
export type Description1 = string;
export type ProtocolVersion2 = string;
export type ProtocolMin = string;
export type ProtocolMax = string;
export type ServerName = string;
export type ServerVersion1 = string;
export type ModelProviders = ModelProviderSummary[];
export type PermissionProfiles = PermissionProfileSummary[];
export type ErrorCode1 =
  | "PROTOCOL_MISMATCH"
  | "UNSUPPORTED"
  | "OVERLOADED"
  | "CONFIGURATION_MISSING"
  | "TIMEOUT"
  | "CLOSED"
  | "NOT_INITIALIZED";
export type Retryable = boolean;
export type ProtocolVersion3 = string;
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
  [k: string]: unknown;
}
/**
 * PhaseG-B5 fork a thread. Parent events and status stay unchanged.
 */
export interface SessionForkRequest {
  method?: Method13;
  session_id: SessionId10;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 parent/child tree. Additive; does not replace child_sessions/list.
 */
export interface SessionTreeRequest {
  method?: Method14;
  session_id: SessionId11;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 archive. Not delete; recoverable via unarchive.
 */
export interface SessionArchiveRequest {
  method?: Method15;
  session_id: SessionId12;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 restore an archived thread to the active list.
 */
export interface SessionUnarchiveRequest {
  method?: Method16;
  session_id: SessionId13;
  [k: string]: unknown;
}
/**
 * Paginate persisted items (events) after a cursor.
 */
export interface SessionItemsRequest {
  method?: Method17;
  session_id: SessionId14;
  cursor?: Cursor1;
  limit?: Limit;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 start a turn. Wraps session/prompt without replacing it.
 */
export interface TurnStartRequest {
  method?: Method18;
  session_id: SessionId15;
  text: Text1;
  request_id?: RequestId;
  timeout_seconds?: TimeoutSeconds2;
  [k: string]: unknown;
}
/**
 * Append steering text to an in-flight turn. No-op if not running.
 */
export interface TurnSteerRequest {
  method?: Method19;
  session_id: SessionId16;
  text: Text2;
  [k: string]: unknown;
}
/**
 * PhaseG-B5 interrupt a running turn. Wraps session/interrupt.
 */
export interface TurnInterruptRequest {
  method?: Method20;
  session_id: SessionId17;
  [k: string]: unknown;
}
/**
 * Retry last turn. Same request_id returns the stored result.
 */
export interface TurnRetryRequest {
  method?: Method21;
  session_id: SessionId18;
  request_id: RequestId1;
  text?: Text3;
  [k: string]: unknown;
}
/**
 * PhaseG-B6 user-initiated command. Distinct from agent tool calls.
 */
export interface CommandStartRequest {
  method?: Method22;
  session_id: SessionId19;
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
  method?: Method23;
  session_id: SessionId20;
  include_completed?: IncludeCompleted;
  [k: string]: unknown;
}
/**
 * Stop one running tool/command/background task.
 */
export interface ExecutionStopRequest {
  method?: Method24;
  session_id: SessionId21;
  task_id: TaskId;
  [k: string]: unknown;
}
/**
 * Read persisted stdout/stderr after the process has exited.
 */
export interface ExecutionOutputRequest {
  method?: Method25;
  session_id: SessionId22;
  task_id: TaskId1;
  [k: string]: unknown;
}
/**
 * PhaseG-B7 read current permission profile and policy version.
 */
export interface PermissionGetRequest {
  method?: Method26;
  [k: string]: unknown;
}
/**
 * PhaseG-B7 set a selectable profile. full_access is rejected.
 */
export interface PermissionSetRequest {
  method?: Method27;
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
  method?: Method28;
  session_id: SessionId23;
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
  method?: Method29;
  approval_id: ApprovalId1;
  [k: string]: unknown;
}
/**
 * List approval audit records for a session or all.
 */
export interface ApprovalAuditRequest {
  method?: Method30;
  session_id?: SessionId24;
  [k: string]: unknown;
}
/**
 * PhaseG-B8 start a read-only review. Does not modify the working tree.
 */
export interface ReviewStartRequest {
  method?: Method31;
  request_id: RequestId2;
  session_id?: SessionId25;
  thread_id?: ThreadId;
  turn_id?: TurnId1;
  scope?: Scope2;
  base_ref?: BaseRef;
  head_ref?: HeadRef;
  paths?: Paths;
  criteria?: Criteria;
  reviewer?: Reviewer;
  [k: string]: unknown;
}
/**
 * Reconnect/read a persisted review without restarting it.
 */
export interface ReviewReadRequest {
  method?: Method32;
  review_id: ReviewId;
  after_sequence?: AfterSequence;
  [k: string]: unknown;
}
/**
 * Line comment bound to review/finding/file hash/line range.
 */
export interface ReviewCommentRequest {
  method?: Method33;
  review_id: ReviewId1;
  file: File;
  start_line: StartLine;
  end_line: EndLine;
  body: Body;
  finding_id?: FindingId;
  file_hash?: FileHash;
  [k: string]: unknown;
}
export interface CheckpointCreateRequest {
  method?: Method34;
  session_id: SessionId26;
  reason?: Reason1;
  turn_id?: TurnId2;
  [k: string]: unknown;
}
export interface CheckpointListRequest {
  method?: Method35;
  session_id: SessionId27;
  [k: string]: unknown;
}
export interface CheckpointReadRequest {
  method?: Method36;
  checkpoint_id: CheckpointId;
  session_id: SessionId28;
  [k: string]: unknown;
}
export interface CheckpointRestoreRequest {
  method?: Method37;
  checkpoint_id: CheckpointId1;
  session_id: SessionId29;
  approval_id?: ApprovalId2;
  [k: string]: unknown;
}
export interface GitStageRequest {
  method?: Method38;
  session_id: SessionId30;
  paths: Paths1;
  approval_id?: ApprovalId3;
  [k: string]: unknown;
}
export interface GitUnstageRequest {
  method?: Method39;
  session_id: SessionId31;
  paths: Paths2;
  approval_id?: ApprovalId4;
  [k: string]: unknown;
}
export interface GitRevertRequest {
  method?: Method40;
  session_id: SessionId32;
  paths: Paths3;
  hunk_index?: HunkIndex;
  approval_id?: ApprovalId5;
  [k: string]: unknown;
}
/**
 * Discover worker-owned isolated-subagent feature flags.
 */
export interface SubagentCapabilityRequest {
  method?: Method41;
  root_session_id?: RootSessionId;
  [k: string]: unknown;
}
/**
 * List visible AgentDefinitions for mention/autocomplete UI.
 */
export interface SubagentsListRequest {
  method?: Method42;
  root_session_id: RootSessionId1;
  [k: string]: unknown;
}
/**
 * Explicit user ``@agent`` invocation in a Primary/Child tree.
 */
export interface AgentInvokeRequest {
  method?: Method43;
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
  method?: Method44;
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
  method?: Method45;
  root_session_id: RootSessionId4;
  [k: string]: unknown;
}
/**
 * Replay child events after a monotonic cursor for reconnect recovery.
 */
export interface ChildSessionEventsRequest {
  method?: Method46;
  root_session_id: RootSessionId5;
  cursor?: Cursor2;
  [k: string]: unknown;
}
/**
 * Cancel one child subtree, or all children when session_id is omitted.
 */
export interface ChildSessionCancelRequest {
  method?: Method47;
  root_session_id: RootSessionId6;
  session_id?: SessionId33;
  [k: string]: unknown;
}
/**
 * Retry a terminal child with its immutable original request snapshot.
 */
export interface ChildSessionRetryRequest {
  method?: Method48;
  root_session_id: RootSessionId7;
  session_id: SessionId34;
  request_id?: RequestId5;
  [k: string]: unknown;
}
/**
 * Graceful appserver shutdown (future ``appserver`` lifespan teardown).
 *
 * ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
 */
export interface ShutdownRequest {
  method?: Method49;
  reason?: Reason2;
  [k: string]: unknown;
}
/**
 * List configured models with provider grouping and Phase 3 limit summary.
 *
 * Maps ``models/list``. Response carries ``models``, ``active``, ``recent``.
 */
export interface ModelsListRequest {
  method?: Method50;
  [k: string]: unknown;
}
/**
 * List provider connection presets (base URL only, no model ids).
 *
 * Maps ``models/presets``; the client discovers ids via ``models/discover``.
 */
export interface ModelsPresetsRequest {
  method?: Method51;
  [k: string]: unknown;
}
/**
 * Probe a provider catalogue with a credential; never persists.
 *
 * Maps ``models/discover``. ``api_key`` is never stored or echoed.
 */
export interface ModelsDiscoverRequest {
  method?: Method52;
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
  method?: Method53;
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
  method?: Method54;
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
  method?: Method55;
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
  method?: Method56;
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
  method?: Method57;
  id: Id2;
  [k: string]: unknown;
}
/**
 * Store/refresh a model API key (backend DPAPI, never echoed).
 *
 * Maps ``credentials/upsert``.
 */
export interface CredentialsUpsertRequest {
  method?: Method58;
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
  method?: Method59;
  id: Id4;
  [k: string]: unknown;
}
/**
 * F18b: list registered teams as L1 summaries only.
 */
export interface TeamListRequest {
  method?: Method60;
  [k: string]: unknown;
}
/**
 * F18b: list groups and member team ids.
 */
export interface TeamGroupsRequest {
  method?: Method61;
  [k: string]: unknown;
}
/**
 * F18b: rename a user group. Builtin groups are rejected.
 */
export interface TeamGroupRenameRequest {
  method?: Method62;
  old: Old;
  new: New;
  [k: string]: unknown;
}
/**
 * F18b: expose F18 team_install two-step ask. No second approval UX.
 */
export interface TeamInstallRequest {
  method?: Method63;
  name: Name;
  url?: Url;
  confirm?: Confirm;
  group?: Group;
  [k: string]: unknown;
}
/**
 * F18b: set the session's active team. Idempotent.
 */
export interface TeamSetActiveRequest {
  method?: Method64;
  session_id: SessionId35;
  team_id: TeamId;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 list recent projects.
 */
export interface ProjectListRequest {
  method?: Method65;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 add a local directory. Display name is separate from path.
 */
export interface ProjectAddRequest {
  method?: Method66;
  path: Path;
  display_name?: DisplayName;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 drop from recent list. Never deletes user files.
 */
export interface ProjectRemoveRequest {
  method?: Method67;
  project_id: ProjectId4;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 switch the active project without changing process cwd.
 */
export interface ProjectSetActiveRequest {
  method?: Method68;
  project_id: ProjectId5;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 report branch/worktree or NOT_A_GIT_REPO. Never chdir.
 */
export interface WorkspaceStatusRequest {
  method?: Method69;
  workspace_root: WorkspaceRoot2;
  [k: string]: unknown;
}
/**
 * Reject paths that escape the bound workspace, including symlink hops.
 */
export interface WorkspaceResolveRequest {
  method?: Method70;
  workspace_root: WorkspaceRoot3;
  path: Path1;
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
  method: Method71;
  session_id: SessionId36;
  agent_id: AgentId2;
  run_id?: RunId;
  payload?: Payload;
  seq: Seq;
  experiment_tag?: ExperimentTag;
  cache_miss_warning?: CacheMissWarning;
  tokens_used?: TokensUsed;
  budget_used?: BudgetUsed;
  source?: Source;
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
  method?: Method72;
  session_id: SessionId37;
  text: Text4;
  [k: string]: unknown;
}
/**
 * SSE ``type: progress`` from ``StreamTUI.write_progress`` (api_server.py).
 */
export interface ProgressUpdate {
  method?: Method73;
  session_id: SessionId38;
  text: Text5;
  [k: string]: unknown;
}
/**
 * SSE ``type: reasoning`` with ``snapshot: true`` from ``StreamTUI._emit_thinking_snapshot`` (api_server.py).
 */
export interface ReasoningSnapshot {
  method?: Method74;
  session_id: SessionId39;
  text: Text6;
  snapshot?: Snapshot;
  [k: string]: unknown;
}
/**
 * SSE ``type: plan`` from ``StreamTUI.write_plan`` (api_server.py).
 */
export interface PlanUpdate {
  method?: Method75;
  session_id: SessionId40;
  steps: Steps;
  [k: string]: unknown;
}
/**
 * SSE ``type: step`` from ``StreamTUI.write_step`` (api_server.py).
 */
export interface StepProgress {
  method?: Method76;
  session_id: SessionId41;
  index: Index;
  total: Total;
  text: Text7;
  [k: string]: unknown;
}
/**
 * Structured task boundary for LangGraph runs (future emit from chat worker).
 */
export interface TaskStarted {
  method?: Method77;
  session_id: SessionId42;
  task_id: TaskId2;
  title: Title1;
  [k: string]: unknown;
}
/**
 * SSE ``type: tool_call`` from ``StreamTUI.write_tool_call`` (api_server.py).
 */
export interface ToolBegin {
  method?: Method78;
  session_id: SessionId43;
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
  method?: Method79;
  session_id: SessionId44;
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
  method?: Method80;
  session_id: SessionId45;
  task_id: TaskId3;
  kind: Kind;
  origin: Origin;
  name: Name1;
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
  method?: Method81;
  session_id: SessionId46;
  task_id: TaskId4;
  ok: Ok1;
  [k: string]: unknown;
}
/**
 * Reported token usage; unknown provider values stay explicitly null.
 */
export interface TokenUsage {
  method?: Method82;
  session_id: SessionId47;
  input_tokens?: InputTokens;
  output_tokens?: OutputTokens;
  cache_hit_tokens?: CacheHitTokens;
  cache_write_tokens?: CacheWriteTokens;
  cache_hit_rate?: CacheHitRate;
  reporting_status?: ReportingStatus;
  [k: string]: unknown;
}
/**
 * SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py).
 */
export interface FinalAnswer {
  method?: Method83;
  session_id: SessionId48;
  run_id: RunId1;
  text: Text8;
  thinking?: Thinking;
  input_tokens?: InputTokens1;
  output_tokens?: OutputTokens1;
  cache_hit_tokens?: CacheHitTokens1;
  cache_write_tokens?: CacheWriteTokens1;
  cache_hit_rate?: CacheHitRate1;
  reporting_status?: ReportingStatus1;
  session_schema_version?: SessionSchemaVersion;
  [k: string]: unknown;
}
/**
 * Recovery budget opened after an operational failure.
 */
export interface RecoveryStarted {
  session_id: SessionId49;
  run_id: RunId2;
  recovery_id: RecoveryId;
  event_id: EventId;
  seq: Seq1;
  timestamp: Timestamp;
  method?: Method84;
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
  session_id: SessionId50;
  run_id: RunId3;
  recovery_id: RecoveryId1;
  event_id: EventId1;
  seq: Seq2;
  timestamp: Timestamp1;
  method?: Method85;
  [k: string]: unknown;
}
/**
 * One concrete recovery strategy has been scheduled.
 */
export interface RecoveryAttempt {
  session_id: SessionId51;
  run_id: RunId4;
  recovery_id: RecoveryId2;
  event_id: EventId2;
  seq: Seq3;
  timestamp: Timestamp2;
  method?: Method86;
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
  session_id: SessionId52;
  run_id: RunId5;
  recovery_id: RecoveryId3;
  event_id: EventId3;
  seq: Seq4;
  timestamp: Timestamp3;
  method?: Method87;
  attempts: Attempts;
  display_summary: DisplaySummary1;
  [k: string]: unknown;
}
/**
 * Recovery budget was exhausted and a terminal error may be shown.
 */
export interface RecoveryExhausted {
  session_id: SessionId53;
  run_id: RunId6;
  recovery_id: RecoveryId4;
  event_id: EventId4;
  seq: Seq5;
  timestamp: Timestamp4;
  method?: Method88;
  attempts: Attempts1;
  final_error: FinalError;
  [k: string]: unknown;
}
/**
 * SSE ``type: error`` from ``StreamTUI.write_error`` and chat worker (api_server.py).
 */
export interface ErrorNotification {
  method?: Method89;
  session_id: SessionId54;
  message: Message;
  run_id?: RunId7;
  status?: Status3;
  [k: string]: unknown;
}
/**
 * SSE ``type: done`` from chat stream teardown (api_server.py).
 */
export interface RunComplete {
  method?: Method90;
  session_id: SessionId55;
  run_id: RunId8;
  status: Status4;
  [k: string]: unknown;
}
/**
 * Background job state for watchdog / appserver (submitted|running|failed).
 */
export interface JobStatusUpdate {
  method?: Method91;
  session_id: SessionId56;
  job_id: JobId;
  state: State;
  [k: string]: unknown;
}
/**
 * Periodic appserver liveness signal (T4 watchdog).
 */
export interface ServerHeartbeat {
  method?: Method92;
  uptime_seconds: UptimeSeconds;
  active_jobs: ActiveJobs;
  degraded: Degraded;
  [k: string]: unknown;
}
/**
 * PhaseG-B2 handshake complete. No response expected.
 */
export interface InitializedNotification {
  method?: Method93;
  protocol_version: ProtocolVersion1;
  server_version: ServerVersion;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 appserver process is up and holding the instance lock.
 */
export interface ProcessStarted {
  method?: Method94;
  pid: Pid;
  started_at: StartedAt;
  instance_policy?: InstancePolicy;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 graceful shutdown. Incomplete work is not marked completed.
 */
export interface ProcessShutdown {
  method?: Method95;
  reason: Reason3;
  graceful: Graceful;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 restart found an unfinished turn. UI must not show success.
 */
export interface RecoveryRequired {
  method?: Method96;
  session_id: SessionId57;
  previous_status: PreviousStatus;
  status?: Status5;
  [k: string]: unknown;
}
/**
 * PhaseG-B3 failed to become the instance (lock or boot).
 */
export interface ProcessFailed {
  method?: Method97;
  reason: Reason4;
  error_code: ErrorCode;
  [k: string]: unknown;
}
/**
 * PhaseG-B4 active workspace changed. Does not chdir the process.
 */
export interface WorkspaceChanged {
  method?: Method98;
  project_id: ProjectId6;
  workspace_root: WorkspaceRoot4;
  display_name: DisplayName1;
  [k: string]: unknown;
}
/**
 * Maps ``ApprovalRequest.to_event()`` SSE in core/safety/approval.py.
 */
export interface ApprovalRequest {
  method?: Method99;
  session_id: SessionId58;
  request_id: RequestId6;
  risk_level: RiskLevel;
  action: Action2;
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
  request_id: RequestId7;
  decision: Decision1;
  [k: string]: unknown;
}
/**
 * Maps ``QuestionRequest.to_event()`` in core/question.py.
 */
export interface QuestionRequest {
  method?: Method100;
  session_id: SessionId59;
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
  goal: Goal;
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
  name: Name2;
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
  name: Name3;
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
  method?: Method101;
  session_id: SessionId60;
  request_id: RequestId8;
  to_role: ToRole;
  stage: Stage;
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
  request_id: RequestId9;
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
  method?: Method102;
  session_id: SessionId61;
  request_id: RequestId10;
  from_role: FromRole;
  to_role: ToRole1;
  question: Question1;
  stage: Stage1;
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
  method?: Method103;
  session_id: SessionId62;
  role: Role3;
  stage?: Stage2;
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
  reason: Reason5;
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
  method?: Method104;
  task_id: TaskId5;
  parent_id?: ParentId;
  goal: Goal1;
  context_refs?: ContextRefs;
  acceptance?: Acceptance;
  tools?: Tools1;
  budget?: BridgeBudget;
  [k: string]: unknown;
}
/**
 * Worker → Leader streaming status. notes truncated to ~2k tokens.
 */
export interface BridgeProgress {
  method?: Method105;
  task_id: TaskId6;
  status: Status6;
  stage?: Stage3;
  percent?: Percent;
  eta_s?: EtaS;
  notes?: Notes;
  [k: string]: unknown;
}
/**
 * Worker → Leader. Large results go to result_ref, never inline.
 */
export interface BridgeToolCall {
  method?: Method106;
  task_id: TaskId7;
  tool: Tool;
  args?: Args;
  status?: Status7;
  result_ref?: ResultRef;
  [k: string]: unknown;
}
export interface Args {
  [k: string]: unknown;
}
/**
 * Worker → Leader execution plan before work starts.
 */
export interface BridgePlan {
  method?: Method107;
  task_id: TaskId8;
  steps?: Steps1;
  files?: Files;
  est_tokens?: EstTokens;
  ack?: Ack;
  [k: string]: unknown;
}
/**
 * Worker → Leader. summary is 1–2k tokens; artifacts are paths.
 */
export interface BridgeResult {
  method?: Method108;
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
  method?: Method109;
  task_id: TaskId10;
  reason: Reason6;
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
  browser?: Browser;
  mcp?: Mcp;
  skills?: Skills;
  multi_agent?: MultiAgent;
  multi_model?: MultiModel;
  vision?: Vision;
  "approval.auto_review"?: ApprovalAutoReview;
  [k: string]: unknown;
}
export interface ModelProviderSummary {
  provider_id: ProviderId1;
  model_id?: ModelId1;
  model_context_window?: ModelContextWindow;
  model_max_output_tokens?: ModelMaxOutputTokens;
  limit_source?: LimitSource;
  is_fallback?: IsFallback;
  warning?: Warning;
  [k: string]: unknown;
}
export interface PermissionProfileSummary {
  profile_id: ProfileId1;
  selectable: Selectable;
  description: Description1;
  [k: string]: unknown;
}
/**
 * Additive initialize response. Old clients ignore unknown keys.
 */
export interface InitializeResult {
  protocol_version?: ProtocolVersion2;
  protocol_min?: ProtocolMin;
  protocol_max?: ProtocolMax;
  server_name?: ServerName;
  server_version?: ServerVersion1;
  capabilities: Capabilities1;
  capability_snapshot: CapabilitySnapshot;
  model_providers: ModelProviders;
  permission_profiles: PermissionProfiles;
  [k: string]: unknown;
}
export interface Capabilities1 {
  [k: string]: unknown;
}
/**
 * Machine-assertable error payload in JSON-RPC ``error.data``.
 */
export interface ProtocolErrorData {
  error_code: ErrorCode1;
  retryable: Retryable;
  protocol_version?: ProtocolVersion3;
  protocol_min?: ProtocolMin1;
  protocol_max?: ProtocolMax1;
  server_version?: ServerVersion2;
  details?: Details1;
  [k: string]: unknown;
}
