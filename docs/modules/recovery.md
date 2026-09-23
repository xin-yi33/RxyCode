# recovery/ - Error Recovery

## What Is This Module?
Handles errors during task execution with retry logic and error summarization.

## Key Files
| File | Purpose |
|------|---------|
| error_recovery.py | ErrorRecovery + ErrorKind classification + tenacity backoff |
| circuit_breaker.py | LLMCircuitBreaker - keyed per agent (F2). One role tripping no longer takes down the process. |

## Core Code: error_recovery.py (ErrorRecovery)

**Error Handling Strategy:**
1. Track error count per task (max_retries=3)
2. On error, determine if retry is viable
3. If retryable: mark task for re-execution
4. If max retries exceeded: mark task as failed with error summary
5. Provide error summary for the synthesizer

**Key Methods:**
- handle_error(tree, task_id, error) -> str: Handle an execution error
  - Returns: 'retry' if retryable, 'cancel' if max retries exceeded, 'skip' if task not found
- get_error_summary(tree) -> str: Collect all errors for reporting

**Error Classification (ErrorKind / classify_error):**
- TRANSIENT: network blips, **short connect** timeouts, HTTP 429 / 5xx
  (httpx + openai SDK exceptions mapped; status semantics adapted from
  config/model_manager.py:50-60). Generic read/idle ``TimeoutError``,
  ``httpx.ReadTimeout``, and ``openai.APITimeoutError`` are **not**
  retried — those clocks already spent the budget. Surface: `event/retry`
  until retries exhaust.
- BUSINESS: tool/result failures (`classify_tool_status`). Surface: `tool_result`.
  The turn continues; do not emit `event/error`.
- PERMANENT: logic / parse / validation errors, HTTP 4xx (except 429), fired
  stream clocks (`FirstTokenTimeoutError` / `StreamIdleTimeoutError`), and
  long read/idle timeouts. Surface: `event/error`.
- Short connect handshake (`StreamConnectTimeoutError`) is TRANSIENT and may
  use `STREAM_TRANSPORT_RETRY_MAX` extra attempts (default 2). Daily
  `_raw_stream` does **not** retry first-token/idle 180s. Appserver stall
  recycles a dead worker; it is not an LLM retry.
- Unknown errors default to PERMANENT (conservative: no blind retries)
- `should_emit_event_error` is the session/TUI gate for `event/error`.

**Backoff (retry_with_backoff):**
- Adapted from tenacity: TRANSIENT errors retried with
  wait_exponential_jitter(initial=2, max=30) + stop_after_attempt(3)
  (`retry_with_backoff(..., wait_multiplier=2, max_attempts=3)`)
- PERMANENT errors propagate immediately without consuming attempts
- Applies to READ-level tool invocations in ToolOrchestrator; task-level
  recovery (`handle_error`) marks tasks PENDING/CANCELLED rather than rewriting
  prompts

## Core Code: circuit_breaker.py (LLMCircuitBreaker)

**Purpose:** Stop cascading failures when the LLM provider is down.

- Adapted from pybreaker: CircuitBreaker(fail_max=5, reset_timeout=60)
- After 5 consecutive failures the breaker opens for 60s; while open, calls
  fail fast with CircuitBreakerError instead of hitting the provider
- Attached at the UsageTrackingLLM call layer (core/agent_v2.py), so fast
  path, graph nodes and sub-agents share the default keyed breaker
  (`get_breaker("default")`); additional keys isolate AgentRuntimes
- While open, UsageTrackingLLM returns a "服务暂时不可用" message instead of
  raising (honest hint, no cascade)
- astream and `_raw_stream` only guard stream *establishment* through the
  breaker so token streaming is not buffered
- Config switch: recovery.circuit_breaker_enabled (default true)
- Helpers: `get_breaker(key)` / `get_default_breaker()` /
  `reset_all_breakers()` / `reset_breakers()` /
  `SERVICE_UNAVAILABLE_MESSAGE`
