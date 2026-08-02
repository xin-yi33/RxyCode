/* Auto-generated. Edit protocol/schema.json then run: bun run generate */

export type RxyCodeProtocol = ClientRequest | ProtocolNotification | ServerRequestMessage;
export type ClientRequest = InitializeRequest | NewSessionRequest | PromptRequest | InterruptRequest | ShutdownRequest;
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
export type Method3 = "session/interrupt";
export type SessionId1 = string;
export type Method4 = "shutdown";
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
  | JobStatusUpdate;
export type Method5 = "event/message_delta";
export type SessionId2 = string;
export type Text1 = string;
export type Method6 = "event/progress";
export type SessionId3 = string;
export type Text2 = string;
export type Method7 = "event/reasoning_snapshot";
export type SessionId4 = string;
export type Text3 = string;
export type Snapshot = boolean;
export type Method8 = "event/plan";
export type SessionId5 = string;
export type Steps = string[];
export type Method9 = "event/step";
export type SessionId6 = string;
export type Index = number;
export type Total = number;
export type Text4 = string;
export type Method10 = "event/task_started";
export type SessionId7 = string;
export type TaskId = string;
export type Title = string;
export type Method11 = "event/tool_begin";
export type SessionId8 = string;
export type CallId = string;
export type ToolName = string;
export type Method12 = "event/tool_end";
export type SessionId9 = string;
export type CallId1 = string;
export type Ok = boolean;
export type Summary = string;
export type Status = string | null;
export type Method13 = "event/task_complete";
export type SessionId10 = string;
export type TaskId1 = string;
export type Ok1 = boolean;
export type Method14 = "event/token_usage";
export type SessionId11 = string;
export type InputTokens = number;
export type OutputTokens = number;
export type Method15 = "event/final";
export type SessionId12 = string;
export type RunId = string;
export type Text5 = string;
export type Thinking = string | null;
export type InputTokens1 = number | null;
export type OutputTokens1 = number | null;
export type SessionSchemaVersion = number | null;
export type Method16 = "event/error";
export type SessionId13 = string;
export type Message = string;
export type RunId1 = string | null;
export type Status1 = ("succeeded" | "failed" | "cancelled" | "timed_out") | null;
export type Method17 = "event/done";
export type SessionId14 = string;
export type RunId2 = string;
export type Status2 = "succeeded" | "failed" | "cancelled" | "timed_out";
export type Method18 = "event/job_status";
export type SessionId15 = string;
export type JobId = string;
export type State = "submitted" | "running" | "failed";
export type ServerRequestMessage = ApprovalRequest | ApprovalResponse | QuestionRequest | QuestionResponse;
export type Method19 = "approval/request";
export type SessionId16 = string;
export type RequestId = string;
export type RiskLevel = "READ" | "WRITE" | "DANGER";
export type Action = string;
export type RequestId1 = string;
export type Decision = "approved" | "rejected" | "allow_once" | "always_allow_level";
export type Method20 = "question/request";
export type SessionId17 = string;
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
 */
export interface PromptRequest {
  method?: Method2;
  session_id: SessionId;
  text: Text;
  timeout_seconds?: TimeoutSeconds;
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
 * Graceful appserver shutdown (future ``appserver`` lifespan teardown).
 *
 * ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
 */
export interface ShutdownRequest {
  method?: Method4;
  reason?: Reason;
  [k: string]: unknown;
}
/**
 * SSE ``type: token`` via ``StreamTUI._buffer("token")`` / flush (api_server.py).
 */
export interface MessageDelta {
  method?: Method5;
  session_id: SessionId2;
  text: Text1;
  [k: string]: unknown;
}
/**
 * SSE ``type: progress`` from ``StreamTUI.write_progress`` (api_server.py).
 */
export interface ProgressUpdate {
  method?: Method6;
  session_id: SessionId3;
  text: Text2;
  [k: string]: unknown;
}
/**
 * SSE ``type: reasoning`` with ``snapshot: true`` from ``StreamTUI._emit_thinking_snapshot`` (api_server.py).
 */
export interface ReasoningSnapshot {
  method?: Method7;
  session_id: SessionId4;
  text: Text3;
  snapshot?: Snapshot;
  [k: string]: unknown;
}
/**
 * SSE ``type: plan`` from ``StreamTUI.write_plan`` (api_server.py).
 */
export interface PlanUpdate {
  method?: Method8;
  session_id: SessionId5;
  steps: Steps;
  [k: string]: unknown;
}
/**
 * SSE ``type: step`` from ``StreamTUI.write_step`` (api_server.py).
 */
export interface StepProgress {
  method?: Method9;
  session_id: SessionId6;
  index: Index;
  total: Total;
  text: Text4;
  [k: string]: unknown;
}
/**
 * Structured task boundary for LangGraph runs (future emit from chat worker).
 */
export interface TaskStarted {
  method?: Method10;
  session_id: SessionId7;
  task_id: TaskId;
  title: Title;
  [k: string]: unknown;
}
/**
 * SSE ``type: tool_call`` from ``StreamTUI.write_tool_call`` (api_server.py).
 */
export interface ToolBegin {
  method?: Method11;
  session_id: SessionId8;
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
  method?: Method12;
  session_id: SessionId9;
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
  method?: Method13;
  session_id: SessionId10;
  task_id: TaskId1;
  ok: Ok1;
  [k: string]: unknown;
}
/**
 * Token deltas from chat ``final`` SSE payload fields (api_server.py queue).
 */
export interface TokenUsage {
  method?: Method14;
  session_id: SessionId11;
  input_tokens: InputTokens;
  output_tokens: OutputTokens;
  [k: string]: unknown;
}
/**
 * SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py).
 */
export interface FinalAnswer {
  method?: Method15;
  session_id: SessionId12;
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
  method?: Method16;
  session_id: SessionId13;
  message: Message;
  run_id?: RunId1;
  status?: Status1;
  [k: string]: unknown;
}
/**
 * SSE ``type: done`` from chat stream teardown (api_server.py).
 */
export interface RunComplete {
  method?: Method17;
  session_id: SessionId14;
  run_id: RunId2;
  status: Status2;
  [k: string]: unknown;
}
/**
 * Background job state for watchdog / appserver (submitted|running|failed).
 */
export interface JobStatusUpdate {
  method?: Method18;
  session_id: SessionId15;
  job_id: JobId;
  state: State;
  [k: string]: unknown;
}
/**
 * Maps ``ApprovalRequest.to_event()`` SSE in core/safety/approval.py.
 */
export interface ApprovalRequest {
  method?: Method19;
  session_id: SessionId16;
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
  method?: Method20;
  session_id: SessionId17;
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
