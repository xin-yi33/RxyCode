# recovery/ - Error Recovery

## What Is This Module?
Handles errors during task execution with retry logic and error summarization.

## Key Files
| File | Purpose |
|------|---------|
| error_recovery.py | ErrorRecovery + ErrorKind classification + tenacity backoff |
| circuit_breaker.py | LLMCircuitBreaker - pybreaker-based LLM circuit breaker |

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
- TRANSIENT: network blips, timeouts, connection errors, HTTP 429 / 5xx
  (httpx + openai SDK exceptions mapped; status semantics adapted from
  config/model_manager.py:8-21)
- PERMANENT: logic / parse / validation errors, HTTP 4xx (except 429)
- Unknown errors default to PERMANENT (conservative: no blind retries)

**Backoff (retry_with_backoff):**
- Adapted from tenacity: TRANSIENT errors retried with
  wait_exponential_jitter(initial=2, max=30) + stop_after_attempt(3)
- PERMANENT errors propagate immediately without consuming attempts

**Retry Logic:**
- Tool execution errors: retry with same parameters
- LLM errors: retry with simplified prompt
- Timeout errors: retry with increased timeout
- Max 3 retries per task before giving up

## Core Code: circuit_breaker.py (LLMCircuitBreaker)

**Purpose:** Stop cascading failures when the LLM provider is down.

- Adapted from pybreaker: CircuitBreaker(fail_max=5, reset_timeout=60)
- After 5 consecutive failures the breaker opens for 60s; while open, calls
  fail fast with CircuitBreakerError instead of hitting the provider
- Attached at the UsageTrackingLLM call layer (core/agent_v2.py), so fast
  path, graph nodes and sub-agents share one process-wide breaker
- While open, UsageTrackingLLM returns a "服务暂时不可用" message instead of
  raising (honest hint, no cascade)
- astream only guards stream *establishment* through the breaker so token
  streaming is not buffered
- Config switch: recovery.circuit_breaker_enabled (default true)
