/* Auto-generated. Edit protocol/schema.json then run: bun run generate */

export type RxyCodeProtocol = ClientRequest | ProtocolNotification | ServerRequestMessage;
export type ClientRequest =
  | InitializeRequest
  | NewSessionRequest
  | PromptRequest
  | InterruptRequest
  | SetThinkingExpandedRequest
  | WarmSessionRequest
  | ShutdownRequest;
export type Method = "initialize";
export type ClientName = string;
export type ClientVersion = string;
export type ProtocolVersion = string;
export type Capabilities = {
  [k: string]: unknown;
} | null;
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
export type Method6 = "shutdown";
export type Reason = string | null;
export type ProtocolNotification =
  | MessageDelta
  | ProgressUpdate
  | ReasoningSnapshot
  | PlanUpdate
  | StepProgress
  | TaskStarted
  | ToolBegin
  | ToolEnd
  | TaskComplete
  | TokenUsage
  | FinalAnswer
  | ErrorNotification
  | RunComplete
  | JobStatusUpdate
  | ServerHeartbeat;
export type Method7 = "event/message_delta";
export type SessionId4 = string;
export type Text1 = string;
export type Method8 = "event/progress";
export type SessionId5 = string;
export type Text2 = string;
export type Method9 = "event/reasoning_snapshot";
export type SessionId6 = string;
export type Text3 = string;
export type Snapshot = boolean;
export type Method10 = "event/plan";
export type SessionId7 = string;
export type Steps = string[];
export type Method11 = "event/step";
export type SessionId8 = string;
export type Index = number;
export type Total = number;
export type Text4 = string;
export type Method12 = "event/task_started";
export type SessionId9 = string;
export type TaskId = string;
export type Title = string;
export type Method13 = "event/tool_begin";
export type SessionId10 = string;
export type CallId = string;
export type ToolName = string;
export type Method14 = "event/tool_end";
export type SessionId11 = string;
export type CallId1 = string;
export type Ok = boolean;
export type Summary = string;
export type Status = string | null;
export type Method15 = "event/task_complete";
export type SessionId12 = string;
export type TaskId1 = string;
export type Ok1 = boolean;
export type Method16 = "event/token_usage";
export type SessionId13 = string;
export type InputTokens = number;
export type OutputTokens = number;
export type Method17 = "event/final";
export type SessionId14 = string;
export type RunId = string;
export type Text5 = string;
export type Thinking = string | null;
export type InputTokens1 = number | null;
export type OutputTokens1 = number | null;
export type SessionSchemaVersion = number | null;
export type Method18 = "event/error";
export type SessionId15 = string;
export type Message = string;
export type RunId1 = string | null;
export type Status1 = ("succeeded" | "failed" | "cancelled" | "timed_out") | null;
export type Method19 = "event/done";
export type SessionId16 = string;
export type RunId2 = string;
export type Status2 = "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method20 = "event/job_status";
export type SessionId17 = string;
export type JobId = string;
export type State = "submitted" | "running" | "failed";
export type Method21 = "event/server_heartbeat";
export type UptimeSeconds = number;
export type ActiveJobs = number;
export type Degraded = boolean;
export type ServerRequestMessage = ApprovalRequest | ApprovalResponse | QuestionRequest | QuestionResponse;
export type Method22 = "approval/request";
export type SessionId18 = string;
export type RequestId = string;
export type RiskLevel = "READ" | "WRITE" | "DANGER";
export type Action = string;
export type RequestId1 = string;
export type Decision = "approved" | "rejected" | "allow_once" | "always_allow_level";
export type Method23 = "question/request";
export type SessionId19 = string;
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
 * JSON-RPC handshake on connect (future ``python -m appserver``).
 *
 * ``client_name`` / ``client_version`` identify the OpenTUI or Desktop client;
 * ``protocol_version`` must equal ``protocol.version.PROTOCOL_VERSION``;
 * ``capabilities`` is an optional client feature manifest (unused in HTTP mode).
 */
export interface InitializeRequest {
  method?: Method;
  client_name: ClientName;
  client_version: ClientVersion;
  protocol_version: ProtocolVersion;
  capabilities?: Capabilities;
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
 * Graceful appserver shutdown (future ``appserver`` lifespan teardown).
 *
 * ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
 */
export interface ShutdownRequest {
  method?: Method6;
  reason?: Reason;
  [k: string]: unknown;
}
/**
 * SSE ``type: token`` via ``StreamTUI._buffer("token")`` / flush (api_server.py).
 */
export interface MessageDelta {
  method?: Method7;
  session_id: SessionId4;
  text: Text1;
  [k: string]: unknown;
}
/**
 * SSE ``type: progress`` from ``StreamTUI.write_progress`` (api_server.py).
 */
export interface ProgressUpdate {
  method?: Method8;
  session_id: SessionId5;
  text: Text2;
  [k: string]: unknown;
}
/**
 * SSE ``type: reasoning`` with ``snapshot: true`` from ``StreamTUI._emit_thinking_snapshot`` (api_server.py).
 */
export interface ReasoningSnapshot {
  method?: Method9;
  session_id: SessionId6;
  text: Text3;
  snapshot?: Snapshot;
  [k: string]: unknown;
}
/**
 * SSE ``type: plan`` from ``StreamTUI.write_plan`` (api_server.py).
 */
export interface PlanUpdate {
  method?: Method10;
  session_id: SessionId7;
  steps: Steps;
  [k: string]: unknown;
}
/**
 * SSE ``type: step`` from ``StreamTUI.write_step`` (api_server.py).
 */
export interface StepProgress {
  method?: Method11;
  session_id: SessionId8;
  index: Index;
  total: Total;
  text: Text4;
  [k: string]: unknown;
}
/**
 * Structured task boundary for LangGraph runs (future emit from chat worker).
 */
export interface TaskStarted {
  method?: Method12;
  session_id: SessionId9;
  task_id: TaskId;
  title: Title;
  [k: string]: unknown;
}
/**
 * SSE ``type: tool_call`` from ``StreamTUI.write_tool_call`` (api_server.py).
 */
export interface ToolBegin {
  method?: Method13;
  session_id: SessionId10;
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
  method?: Method14;
  session_id: SessionId11;
  call_id: CallId1;
  ok: Ok;
  summary: Summary;
  status?: Status;
  [k: string]: unknown;
}
/**
 * Structured task completion paired with ``TaskStarted``.
 */
export interface TaskComplete {
  method?: Method15;
  session_id: SessionId12;
  task_id: TaskId1;
  ok: Ok1;
  [k: string]: unknown;
}
/**
 * Token deltas from chat ``final`` SSE payload fields (api_server.py queue).
 */
export interface TokenUsage {
  method?: Method16;
  session_id: SessionId13;
  input_tokens: InputTokens;
  output_tokens: OutputTokens;
  [k: string]: unknown;
}
/**
 * SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py).
 */
export interface FinalAnswer {
  method?: Method17;
  session_id: SessionId14;
  run_id: RunId;
  text: Text5;
  thinking?: Thinking;
  input_tokens?: InputTokens1;
  output_tokens?: OutputTokens1;
  session_schema_version?: SessionSchemaVersion;
  [k: string]: unknown;
}
/**
 * SSE ``type: error`` from ``StreamTUI.write_error`` and chat worker (api_server.py).
 */
export interface ErrorNotification {
  method?: Method18;
  session_id: SessionId15;
  message: Message;
  run_id?: RunId1;
  status?: Status1;
  [k: string]: unknown;
}
/**
 * SSE ``type: done`` from chat stream teardown (api_server.py).
 */
export interface RunComplete {
  method?: Method19;
  session_id: SessionId16;
  run_id: RunId2;
  status: Status2;
  [k: string]: unknown;
}
/**
 * Background job state for watchdog / appserver (submitted|running|failed).
 */
export interface JobStatusUpdate {
  method?: Method20;
  session_id: SessionId17;
  job_id: JobId;
  state: State;
  [k: string]: unknown;
}
/**
 * Periodic appserver liveness signal (T4 watchdog).
 */
export interface ServerHeartbeat {
  method?: Method21;
  uptime_seconds: UptimeSeconds;
  active_jobs: ActiveJobs;
  degraded: Degraded;
  [k: string]: unknown;
}
/**
 * Maps ``ApprovalRequest.to_event()`` SSE in core/safety/approval.py.
 */
export interface ApprovalRequest {
  method?: Method22;
  session_id: SessionId18;
  request_id: RequestId;
  risk_level: RiskLevel;
  action: Action;
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
  request_id: RequestId1;
  decision: Decision;
  [k: string]: unknown;
}
/**
 * Maps ``QuestionRequest.to_event()`` in core/question.py.
 */
export interface QuestionRequest {
  method?: Method23;
  session_id: SessionId19;
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
