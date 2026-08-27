# core/ - Agent Core

## What Is This Module?
The core module is the brain of RxyCode. It contains the main agent logic, the LangGraph execution pipeline, system prompts, state definitions, and configuration. Every user request flows through this module.

## Architecture

### Session layer (Phase 2)

| File | Purpose |
|------|---------|
| session.py | Headless `Session` facade over AgentV2; terminal events via `emit()` protocol models |

`Session` is the strangler entry point for `api_server.py` and future `appserver/`.
It performs no I/O — HTTP/SSE adapters map `notification_to_sse_event()` to legacy event dicts.

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
| catalog.py | Cache-contract catalog — three families via `injects_cache_control` / `injects_prompt_cache_key`; unknown models get a five-point fallback (`unknown_fallback_contract`), never model-name heuristics |
| prefix_profile.py | Frozen prefix fingerprints — `PrefixProfile`, `digest_tools`, `identity()`, `profiles_compatible` (chat vs agent archives) |
| turn_router.py | THE single turn router — `route()` owns all fast-path decisions; do NOT add routing ifs to agent_v2._run_impl |
| prewarm.py | Isomorphic prewarm archives (chat + agent slots) and keep-alive that rides the frozen AgentPrefix |
| turn_context.py | Public `append_turn_context` seam (LinkAgent/EKO suffix) — never spliced into S1 |
| handoff.py | `HandoffEnvelope` reserved type — rejects messages/history/thinking keys (NoHistoryCopy) |
| agents/spec.py | Phase F static validation for TeamSpec (`validate_team`). `MAX_DELEGATE_DEPTH=3` is the Coordinator hop cap (DC6); it is not Phase D `subagent_depth` (0/1/2 on ChildSession). |
| agents/runtime.py | Phase F `AgentRuntime` role adapter over Phase D `ChildRuntime`. Does not copy D5 lifecycle. Session may hold many runtimes; single-agent path still uses AgentV2 (`role="default"` keeps cache namespace `None`). |
| agents/sop.py | Phase F `SopMachine`: deterministic SOP transitions from TeamSpec. No LLM, Session, or IO. |
| agents/coordinator.py | Phase F Coordinator: empty toolset, form_team only, precheck, one LLM route event, dual ledgers + stall replan. |
| agents/mailbox.py | Phase F append-only mailbox; every message records `relayed_by`. |
| agents/blackboard.py | Phase F append-only blackboard with authorized `context_keys` and a 1 MB cap. |
| agents/verifier.py | Phase F mechanical gate (no LLM). Eight low-level checks plus high-level `goal_satisfied`. Verdicts bind `subject_hash`. |
| agents/budget.py | Phase F `BudgetGuard`: token / wall-clock / delegation fuses. Over-budget returns a truncated partial answer. |
| agents/router.py | Phase F `ModeRouter`: /solo /team /team-multi /why-mode, then heuristics, then optional LLM. Default `agents.enabled=false`. |
| agents/teams/software_dev/ | Builtin software_dev Team Pack (pm → architect → frontend/backend → tester → verify → 3-way audit → doc). Tool names: `read`/`ls`. |
| tracing.py | Node spans plus team tree (`replay --show-team`). J3 `LlmCallRecord` is opt-in via `settings.distillation.collect`. |
| agents/client_settings.py | F13 settings projection: nested expert-team fields hidden until `agents.enabled`. |
| agents/bridge/ | F16 external-agent Workers: JSON-RPC task_delegate/progress/tool_call/plan/result/abort over stdio or WS. No resident pool. |

See `docs/modules/agents.md` for the expert-team module index.

### Session Runtime Persistence

`core/session_runtime.py` persists the active workspace in two separate dated records:
- `~/.RxyCode/projects/YYYY-MM-DD/<session_id>.json`: project/workspace metadata
- `~/.RxyCode/sessions/YYYY-MM-DD/runtime/<session_id>.json`: runtime session state referencing the project record

Session restoration searches the current date, earlier dated records, and the legacy `runtime_sessions/` directory.

### Core Code: agent_v2.py

**Classes:**
- UsageTrackingLLM (line ~401): Wrapper around any LangChain LLM that records
  token usage and settles provider/model rate-limit grants for every
  LLM call. `_to_openai_messages` drops orphan `role=tool` history entries
  that are not a response to the preceding assistant `tool_calls`, and
  inserts a stub tool result for any unanswered `tool_call_id` before the
  next user/assistant message (or the end of the payload). Both mismatches
  otherwise 400 on DeepSeek/OpenAI. Incomplete DSML/XML tool markup in the
  model text is treated as a continuation (native tools), not a successful
  Final Answer. A build turn that never successfully calls write/edit, or
  that stops after a partial write to say "now the controllers" / "请继续",
  is nudged to keep writing instead of emitting a filename table as the
  Final Answer. `ainvoke()` and `astream()` call. It re-wraps `bind_tools()` and
  `with_structured_output()` so fast path, graph, and sub-agent calls retain
  both behaviors.
- AgentV2 (line ~747): The main agent. Handles user input routing, fast-path optimization, compose mode, and the full LangGraph pipeline. Also owns session lifecycle (`set_session`/`reset_session`/`switch_model`/`list_checkpoints`), hooks, trajectory and checkpoint/journal integration. A succeeded run does not mark the durable checkpoint complete while the side-effect journal still has pending WRITE/DANGER rows; otherwise an identical retry rotates `attempt_id` and later writes are blocked as `journal_unavailable`.
**How a Request Flows:**
1. AgentV2.run(user_input, mode) is called
2. Plan mode uses a dedicated read-only tool loop and never enters the execution graph
3. Download intent check (_detect_download_intent) for build/compose requests that are not create/build product prompts. A long “create a website” request that mentions an isolated Skill directory must not collapse into `download_skill`. Create/build product requests that also ask for websearch continue after research prefetch failure; pure freshness Q&A still aborts instead of guessing.
4. Fast path: simple queries go directly to _fast_reply() (with 2-level cache: exact + semantic)
5. Parallel path: `request_routing.should_use_subagents()` sets `parallel_requested` on graph state. LangGraph then runs **the same AgentV2** TaskTree leaves concurrently (`asyncio.gather`). Isolated child agents live in `core/subagents/` (Phase D `task` / `@agent`). Expert-team vs solo is `ModeRouter` (`core/agents/router.py`); `settings.agents.enabled` defaults to false (always SOLO, no L2/L3).
6. Compose path: plan+build mode uses _run_compose()
7. Full pipeline: complex build tasks go through the LangGraph pipeline in graph.py

**Key Methods in AgentV2:**
- _fast_reply(user_input): Direct LLM call with caching. Uses astream() in stream mode, ainvoke() otherwise. Includes tiktoken fallback for token estimation when streaming chunks lack usage metadata.
- _register_tools(): Registers all available tools via `core/builtin_tool_registration.register_builtin_tools()` (bash, read, write, edit, grep, glob, git, webfetch, websearch, file_download, `task`/`task_manage`, subagent dispatch, etc.). Isolated subagents default on (`subagent_config_from_env()`; `RXYCODE_SUBAGENTS=0` disables). When `subagents_enabled` is on, the `task` name is the isolated subagent dispatch tool and the task-list tool registers as `task_manage`.
- _is_simple_query(text): Heuristic to decide if a query can skip the full pipeline.
- _detect_download_intent(text): Regex-based detection of file download, skill download, and MCP download intents.
- _run_plan_only(user_input): Produces a Markdown plan (`#` / `## Summary` / `## Steps`) with an explicit read/view/ls/grep/glob/websearch/webfetch/datetime allowlist; mutating calls are hidden and rejected, and the execution graph is never entered. Desktop 在计划文档下用「是，实施此计划」切到 Build。
- cancel(): Cancels the active asyncio request task and propagates cancellation to an active graph task.
- _extract_and_save_code(response, user_input): Compatibility no-op; implicit code saving/opening was removed. Models must use safety-gated write/open tools explicitly.
- set_session(session_id)/reset_session()/switch_model(name)/list_checkpoints(): Durable session lifecycle, model switch and checkpoint inspection.
- register_hook/unregister_hook: lifecycle hooks (`before`/`after`/`error`) via `core/hooks.py`.
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

**LLM construction via provider layer (A6/A8/A9):**

- `_build_llm_from_config()` resolves the strategy, derives capabilities, and
  builds the raw LLM: `provider = providers.resolve(model_config)` →
  `caps = provider.capabilities(model_config)` →
  `ChatOpenAI(**provider.llm_kwargs(model_config, caps))` — then wraps it in
  `UsageTrackingLLM(provider=provider, capabilities=caps)` (see
  [providers](providers.md) for the strategy layer itself).
- `UsageTrackingLLM` records usage for every `ainvoke()`/`astream()`; cache-read
  and reasoning extraction are **delegated to the provider's capability map**
  (A8): `BaseProvider.extract_cache_read(usage, caps)` walks
  `caps.usage_fields.cache_read_flat` / `cache_read_nested`, and
  `_extract_reasoning()` calls `provider.extract_reasoning(delta, caps)` using
  `caps.usage_fields.reasoning` — replacing the old "try both fields" guessing.
- Prompt variants (A9): `get_role_prompt(...)` / `get_system_prompt(...)` are
  called with `variant=self._prompt_variant()`, where `_prompt_variant()`
  returns `caps.prompt_variant` (e.g. `deepseek-v4-pro` vs `deepseek-v4-flash`).
- Capability gates: `_apply_cache_control()` skips `cache_control` injection
  when `not self._provider.supports_prompt_cache(self._capabilities)`; the
  function-calling fast path raises
  `"capabilities.supports_function_calling is False"` when the capability is
  off (both in `agent_v2.py`).

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
9. reflection_node (graph.py:1299): Reflects on validation failures and decides retry/replan/terminate
10. final_verifier_node (graph.py:1304): Verifies grounded synthesis claims; the actual terminal node (`synthesizer -> final_verifier -> END`)

**Routing Functions:**
- route_next(state): Decides next node after decomposer (execute or synthesize)
- route_after_validator(state): Decides next node after validator (synthesize, replan, or re-execute)
- route_after_reflection(state) (graph.py:1249): Decides next node after reflection
- route_entry(state) (graph.py:1261): Entry routing into the graph
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
- `parallel_tasks`, `parallel_requested` (parallel executor fan-out)
- `reflections`, `failure_attribution`, `replan_count`, `reflection_action`
- `final_verification` (grounded-synthesis verification result)
- `compression_count`
- _llm, _memory, _tool_orchestrator, _tui, _tracer, _checkpoint_store,
  _checkpoint_mode, _checkpoint_key_input, _hooks, _hook_audit, _model_router,
  _trajectory, _capabilities (internal references)

`TaskNode.effect` persists the planner's `TaskEffect` (`read`, `write`,
`danger`, or backward-compatible `auto`). The executor uses `read` to enforce a
READ-only tool ceiling. Validation treats `write`/`danger` as an unconditional
evidence requirement and conservatively infers the requirement for `auto`.

### P6 request routing (`core/request_routing.py`)

AgentV2 no longer embeds ~25 keyword lists inline. Routing lives in
`core/request_routing.py` with this priority:

1. **Explicit directives** (user prefix): `/full`, `/pipeline` → LangGraph;
   `/fast` → tool-aware fast reply
2. **Structured signals**: absolute paths, URLs, `mode` (`plan`/`compose`/`build`)
3. **Narrow keyword heuristics** (legacy, test-locked)

Canonical inventory (`ROUTING_INVENTORY`, 25 sites):

| ID | Location | Triggers | Decides | Risk |
|----|----------|----------|---------|------|
| R01 | `GIT_FORCE_RE` | git-only phrases | Fast-reply allowlist | Low |
| R02 | `PURE_SOCIAL_GREETING_RE` | hello/你好 | Social role hint | Low |
| R03 | `has_creation_product_intent` | 写+游戏 / build+app | Social vs code | **High** |
| R04 | `is_social_chat` | emotion / 玩游戏 | Skip LangGraph | Medium |
| R05 | `is_simple_query.en_patterns` | build entire, multi-step | Full pipeline | **High** |
| R06 | `is_simple_query.zh_always_complex` | 分步/逐步 | Full pipeline | Medium |
| R07 | `is_simple_query.zh_action+scope` | 重构+整个 | Full pipeline | **High** |
| R08 | `is_simple_query.length` | >500 chars | Full pipeline | Low |
| R09 | `is_simple_query.zh_code_intent` | 游戏/代码/脚本 | Tool pipeline | **High** |
| R10 | `is_simple_query.en_code_intent` | `\b(game\|app\|website\|code\|script\|bot\|crawler\|algorithm)\b` | Tool pipeline | **High** |
| R11 | `is_simple_query.zh_file_ops` | 读文件/写文件 | Tool pipeline | Medium |
| R12 | `is_simple_query.en_file_ops` | `read file` | Tool pipeline | Medium |
| R13 | `detect_download_intent.url` | file URL | Download path | Low |
| R14 | `detect_download_intent.download_url` | 下载+URL | Download path | Low |
| R15 | `detect_download_intent.package` | npx/pip | MCP/skill | Medium |
| R16 | `detect_download_intent.skill_patterns` | install skill | `download_skill` | Medium |
| R17 | `detect_download_intent.mcp_patterns` | install mcp | `download_mcp` | Medium |
| R18 | `detect_file_operation.code_gen_skip` | game/code | Skip direct file op | Medium |
| R19 | `detect_file_operation.list_kw` | list+path | Direct `ls` | Low |
| R20 | `detect_file_operation.read_kw` | read+cat+path | Direct `read` | Low |
| R21 | `detect_file_operation.write_patterns` | create file path | Direct `write` | Medium |
| R22 | `should_use_subagents` | 并行/batch | `parallel_requested` | Low |
| R23 | `agent_v2._run_impl` | `mode` plan/compose/build | Top-level path | **High** |
| R24 | `agent_v2._run_compose` | build-phase classifier | Compose build | **High** |
| R25 | `parse_routing_directive` | `/full` `/fast` `/pipeline` | Explicit override | Mitigation |

High-risk sites (R03, R05, R07, R09–R10, R23–R24) are covered by
`tests/test_core/test_routing_simple_queries.py`,
`tests/test_core/test_social_chat_routing.py`, `tests/test_routing_consistency.py`,
and `tests/test_core/test_request_routing.py`.

### P7 intentional lazy imports

P7 tracks function-scoped imports under `core/`, `execution/`, `planning/`,
`validation/`, and `synthesis/` via `scripts/count_lazy_imports.py` (budget **70**).

Current total: **72 / 70** (`python scripts/count_lazy_imports.py --by-file`).
The budget is currently **over budget** and must be reduced; the table below is
**non-exhaustive** (representative) since Phase B/C subagent modules and new
providers added several entries.

| Module | Count | Reason |
|--------|------:|--------|
| `execution/tool_journal.py` | 4 | Platform-specific `msvcrt` / `fcntl` file locking; imported only when journal I/O runs |
| `core/agent_v2.py` | 3 | Optional `pybreaker` (guarded by config); `rag.index.start_background_indexer` only when RAG enabled |
| `core/checkpoints.py` | 3 | Defers `execution.tool_journal` (`validate_attempt_id`, `new_attempt_id`) to break import cycles at module load |
| `core/prompts/registry.py` | 3 | `few_shot.format_few_shot` only when rendering few-shot blocks; `datetime` in `build_user_message` to avoid cold-start cost |
| `core/safety/policy.py` | 3 | Defers `session_runtime` path helpers (`resolve_session_path`, `current_working_directory`); `importlib` for optional tool modules |
| `core/prompts/tool_list.py` | 2 | `tools.registry` behind try/except so prompt unit tests run without full tool registration |
| `core/providers/anthropic.py` | 2 | Dual import path (`...config` vs `config`) for installed-package vs repo-root pytest layouts |
| `core/providers/base.py` | 2 | Same dual-path `model_capabilities` import as other provider modules |
| `core/providers/deepseek.py` | 2 | Same dual-path `model_capabilities` import as other provider modules |
| `core/providers/qwen.py` | 2 | Same dual-path `model_capabilities` import as other provider modules |
| `core/safety/approval.py` | 2 | `utils.tui.get_tui` only in TUI approval path; `threading` only in `wait_for_request` test hook |
| `core/session.py` | 2 | `protocol.notifications` try/except for repo-root vs package import layouts |
| `core/builtin_tool_registration.py` | 1 | Optional `rag.search` import guarded by `rag_enabled` |
| `core/graph.py` | 1 | `TYPE_CHECKING`-style deferred `MemoryManager` import for annotations / cycle avoidance |
| `core/prompts/i18n.py` | 1 | `config.settings.load_config` in `get_locale()` so prompt tests can run without config I/O at import |
| `core/providers/tokenizers.py` | 1 | Optional `tiktoken` import; falls back when package not installed |

`tracing.py`, `trajectory.py`, `tool_orchestrator.py`, and `graph.py` node factories
now use module-scope absolute imports (config reads go through `config.settings`).

Regression guard: `tests/test_core/test_lazy_import_budget.py` (milestone & final budget)
and `python scripts/count_lazy_imports.py` (must stay `< 70`).

### Isolated Subagents (`core/subagents/`, Phase B/C/D)

The subagent system is a separate package under `core/`:
- `manager.py` — `ChildSessionManager`: the single dispatch path for `task` tool,
  `@agent` mention, and command subtasks (validates definition/mode, permission.task,
  depth, context, budget, then executes through `ChildRuntime`).
- `runtime.py` — `AgentRuntime` + `ChildRuntime` facade. Each child creates an
  **independent `AgentV2`** bound to a child session id, installs a child permission
  guard before `AgentV2`'s tool gate, and normalizes result/usage/telemetry/errors
  into `TaskResult`. Parent cancel propagates to the active child AgentV2.
- `sessions.py` — `ChildSession` lifecycle state machine + `SessionTree` (recursive
  parent cancellation).
- `definitions.py` / `config_loader.py` — `AgentDefinitionRegistry` and
  JSON/Markdown/YAML agent-definition loaders (`config/agents/`).
- `permissions.py` — `PermissionPolicy` allow/ask/deny evaluation with system hard-reject.
- `budget.py` — `BudgetGuard` (steps/tokens/time/concurrency).
- `workspace.py` — `WorkspaceValidator` + `LeaseManager` (read_only / leased_write /
  isolated_worktree).
- `events.py` — `ChildSessionEvent` + `EventStore` (monotonic seq, idempotency, replay).
- `registry_provider.py` — process-wide manager singleton (`init_manager`/`get_manager`).

Dispatch entry points: `tools/subagent_task_tool.py` (`task` tool),
`tools/task_manage.py` (`task_manage` list tool), `tools/agent_invoke.py`
(`@agent` mention). Protocol types live in `protocol/subagents.py`.

### Supporting modules

- `core/research_policy.py` — research fast-path policy (`get_research_policy`),
  including `extract_research_query` (UI `search/filter` and page-control copy
  such as date filters are not search topics; T06 prefers gold/silver/Nasdaq)
  and create/build product tasks continuing after prefetch failure while pure
  Q&A still aborts instead of guessing.
- `core/run_lifecycle.py` — `RunLifecycle` wrapper used by `api_server` around `Session.prompt`.
- `core/hooks.py` — lifecycle `HookRegistry` (`before`/`after`/`error`).
- `core/checkpoints.py` — durable `CheckpointStore` for graph snapshots and side-effect journaling.
- `core/trajectory.py` — per-run trajectory persistence.

## Dependencies
- langchain_core for message types
- langgraph for the state machine
- tiktoken for token estimation fallback
- Internal: config/, cache/, memory/, tools/, utils/
- [tracing](tracing.md): `core/tracing.py` - node-level span collection for pipeline observability
- [evals](evals.md): `evals/` - reuses `core/prompts` registry for judge prompt version management
- [rag](rag.md): `rag/` - code_search tool auto-registers into the tool registry
- [governance](governance.md): `core/governance.py` - rate limits, model routing, and sensitive-action decisions

## Phase Fix invariants (PHASE-FIX.md)

- **Cache contracts live in the catalog, in three families**: implicit /
  explicit / unknown. `injects_cache_control(contract)` and
  `injects_prompt_cache_key(contract)` are the only allowed gate keepers.
  Model-name heuristics (e.g. "id contains claude") are forbidden.
- **S1 is frozen**: the system prompt head never contains per-turn dates or
  dynamic research contracts (`get_system_s1` vs `get_system_s2`).
- **No new routing ifs inside `agent_v2._run_impl`**: `core/turn_router.py`
  `route()` is the single decision table (path, profile_kind, skip_await).
  `_run_impl` must not contain `is_social_chat(` / `PURE_SOCIAL_GREETING_RE`
  / `declines_tools(` probes.
- **ChatPrefix vs AgentPrefix**: greetings/social ride the frozen empty-tool
  chat archive (thinking off, session load skipped); encoding turns keep the
  frozen full core tool list and live reasoning. Tool schema must never be
  cropped per turn (FX6 ToolsFreeze).
- **Prewarm/keep-alive are isomorphic** to the archive they serve
  (`core/prewarm.py`); keep-alive always carries system + core tools.
- **Turn context** (`append_turn_context`) only appends to the user suffix
  after the memory context; `system`/`tools` kinds are rejected.
- **Handoff** may never carry transcripts (`HandoffEnvelope`).
