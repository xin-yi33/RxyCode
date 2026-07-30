# core/ - Agent Core

## What Is This Module?
The core module is the brain of RxyCode. It contains the main agent logic, the LangGraph execution pipeline, system prompts, state definitions, and configuration. Every user request flows through this module.

## Architecture

### Key Files
| File | Purpose |
|------|---------|
| agent_v2.py | Main agent class (AgentV2) - entry point for all user requests |
| graph.py | LangGraph state machine - orchestrates the multi-step pipeline |
| prompts/ | Prompt registry package - all system & role prompts (single source) |
| state.py | AgentState TypedDict - shared state across graph nodes |
| governance.py | Provider/model rate limits, role-aware model routing, and sensitive-action policy contracts |
| tracing.py | Node-level tracing - span collection, JSONL persistence, replay, p50/p99 stats |
| config.py | Legacy config (superseded by config/settings.py) |

### Session Runtime Persistence

`core/session_runtime.py` persists the active workspace in two separate dated records:
- `~/.RxyCode/projects/YYYY-MM-DD/<session_id>.json`: project/workspace metadata
- `~/.RxyCode/sessions/YYYY-MM-DD/runtime/<session_id>.json`: runtime session state referencing the project record

Session restoration searches the current date, earlier dated records, and the legacy `runtime_sessions/` directory.

### Core Code: agent_v2.py

**Classes:**
- UsageTrackingLLM (line ~284): Wrapper around any LangChain LLM that records
  token usage and settles provider/model rate-limit grants for every
  `ainvoke()` and `astream()` call. It re-wraps `bind_tools()` and
  `with_structured_output()` so fast path, graph, and sub-agent calls retain
  both behaviors.
- AgentV2 (line ~240): The main agent. Handles user input routing, fast-path optimization, sub-agent delegation, compose mode, and the full LangGraph pipeline.
- SubAgentV2 (line ~1090): Lightweight sub-agent for parallel task execution.

**How a Request Flows:**
1. AgentV2.run(user_input, mode) is called
2. Plan mode uses a dedicated read-only tool loop and never enters the execution graph
3. Download intent check (_detect_download_intent) for build/compose requests
4. Fast path: simple queries go directly to _fast_reply() (with 2-level cache: exact + semantic)
5. Sub-agent path: complex multi-task queries use _run_with_subagents()
6. Compose path: plan+build mode uses _run_compose()
7. Full pipeline: complex build tasks go through the LangGraph pipeline in graph.py

**Key Methods in AgentV2:**
- _fast_reply(user_input): Direct LLM call with caching. Uses astream() in stream mode, ainvoke() otherwise. Includes tiktoken fallback for token estimation when streaming chunks lack usage metadata.
- _register_tools(): Registers all available tools (bash, read, write, edit, grep, glob, git, webfetch, websearch, file_download, etc.) into the tool orchestrator.
- _is_simple_query(text): Heuristic to decide if a query can skip the full pipeline.
- _detect_download_intent(text): Regex-based detection of file download, skill download, and MCP download intents.
- _run_plan_only(user_input): Produces planning text with an explicit read/view/ls/grep/glob/websearch/webfetch/datetime allowlist; mutating calls are hidden and rejected, and the execution graph is never entered.
- cancel(): Cancels the active asyncio request task and propagates cancellation to an active graph task.
- _extract_and_save_code(response, user_input): Compatibility no-op; implicit code saving/opening was removed. Models must use safety-gated write/open tools explicitly.
- _should_use_subagents(text): Checks if a task has multiple independent subtasks that can run in parallel.
- `_handle_rag_tool_after(context)`: Internal production lifecycle hook. Successful code-affecting tool calls immediately invalidate prompt RAG context and enqueue a debounced incremental refresh; indexing never blocks the tool response.
- `runtime_status()`: Reports live RAG worker state/generations/failures,
  provider/model rate-limit balance, and aggregate MCP connection/tool/error
  state including `backoff_servers` and `next_retry_seconds`; MCP trust labels
  remain explicitly `host_process` and `safe_allowlist_plus_explicit`.
- `_refresh_mcp_tools()`: Uses per-server fingerprints to refresh only added,
  removed, edited, disconnected, or tool-list-changed MCP servers. Unchanged
  healthy clients remain live when another server fails; failed servers retry
  with bounded exponential backoff instead of adding connection latency to
  every request.

**Token Tracking:**
- _extract_cache_read(resp): Extracts cache hit tokens from provider response metadata
- _record_usage(resp): Records input/output/cache tokens into the global token_stats singleton

**Rate-limit settlement:** Before a provider call, `UsageTrackingLLM` reserves
one request unit plus estimated input tokens and the configured output
reservation. `ainvoke()`, wrapped streaming, and the raw provider stream each
own one `finally` settlement for every acquired grant. Provider/stream errors,
cancellation, and an open circuit breaker therefore
reconcile exactly once. Reconciliation never refunds the request unit; it
refunds unused output-token reservation up to bucket capacity, or records
excess reported/observed tokens as debt for later calls. Settlement failures
are logged without replacing the provider error or cooperative cancellation.

The limiter is an in-process, per-`AgentV2` provider/model token bucket. Its
short `RLock` protects a shared agent across event loops, but it does not
coordinate quotas across separate Agent instances, processes, or hosts. See
[governance](governance.md).

### Core Code: graph.py

Implements the LangGraph state machine with these nodes:
1. goal_planner_node: High-level goal decomposition
2. decomposer_node: Breaks tasks into subtasks (HierarchicalDecomposer)
3. executor_node: Executes individual subtasks with tool orchestration and watchdog timeout
4. validator_node: Validates execution results against requirements
5. re_planner_node: Re-plans on validation failure
6. compressor_node: Compresses context when it grows too large
7. error_recovery_node: Handles errors with retry logic
8. synthesizer_node: Combines all results into a final response

**Routing Functions:**
- route_next(state): Decides next node after decomposer (execute or synthesize)
- route_after_validator(state): Decides next node after validator (synthesize, replan, or re-execute)
- build_graph(): Constructs the full StateGraph with all nodes and edges

**Watchdog Pattern:**
The executor includes a `_watchdog()` coroutine and per-task
`_ProgressTracker`. It polls at `heartbeat_interval_seconds` (default 15), but
the silent-stall cutoff is disabled by default with
`task_stall_timeout_seconds=0`; a legitimate quiet task is therefore not
cancelled at a fixed 600-second boundary. Operators can opt into a positive
stall cutoff, while `task_max_time_seconds=7200` independently enforces the
default total task ceiling.

### Core Code: prompts/ (Prompt Registry)

A package providing the single source of truth for all pipeline stage prompts.
Design stitched from OpenHands: XML tag structured sections, dynamic tool
description injection, few-shot examples, and i18n support.

**Package Structure:**
| File | Purpose |
|------|---------|
| `prompts/__init__.py` | Public API exports |
| `prompts/registry.py` | PromptRegistry class + convenience functions |
| `prompts/templates.py` | All prompt templates with XML tags (<ROLE>, <INSTRUCTIONS>, etc.) |
| `prompts/few_shot.py` | Few-shot example data per pipeline stage |
| `prompts/i18n.py` | Multi-language text packs (zh, en) |
| `prompts/tool_list.py` | Dynamic tool descriptions from ToolRegistry |

**Public API:**
- `get_system_prompt(tools=False, locale=None)`: Unified system prompt (with optional tool descriptions)
- `get_role_prompt(key, locale=None, include_few_shot=True, **kwargs)`: Stage-specific role prompt
- `build_user_message(role, content, memory_context, locale=None)`: Formatted user message
- `list_stages()`: All registered pipeline stage keys
- `get_prompt_version(key) -> str`: Return the version of a registered prompt (for cache-key stability)
- `UNIFIED_SYSTEM_PROMPT`: Backward-compatible constant (rendered without tools)

**PromptSpec Versioning:**
- `PromptSpec` is a frozen dataclass: `name`, `version` (semantic, e.g. "1.0.0"), `template`, `few_shots`
- The `version` field enters cache keys and traces, ensuring prompt changes are detectable and cache-safe
- All stage templates are registered as `PromptSpec` objects at import time from `templates.STAGE_TEMPLATES`
- Bumping the version invalidates caches that depend on prompt content

### Core Code: state.py

Defines AgentState (TypedDict) - the shared state object passed between all graph nodes:
- user_input, session_id, task_tree, memory_context
- conversation_history, current_task_id, execution_results
- final_response, phase, error
- _llm, _memory, _tool_orchestrator, _tui (internal references)

`TaskNode.effect` persists the planner's `TaskEffect` (`read`, `write`,
`danger`, or backward-compatible `auto`). The executor uses `read` to enforce a
READ-only tool ceiling. Validation treats `write`/`danger` as an unconditional
evidence requirement and conservatively infers the requirement for `auto`.

## Dependencies
- langchain_core for message types
- langgraph for the state machine
- tiktoken for token estimation fallback
- Internal: config/, cache/, memory/, tools/, utils/
- [tracing](tracing.md): `core/tracing.py` - node-level span collection for pipeline observability
- [evals](evals.md): `evals/` - reuses `core/prompts` registry for judge prompt version management
- [rag](rag.md): `rag/` - code_search tool auto-registers into the tool registry
- [governance](governance.md): `core/governance.py` - rate limits, model routing, and sensitive-action decisions
