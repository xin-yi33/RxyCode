"""
Pure logging helpers + quiet-path configuration for RxyCode's HTTP/agent layer.

This module is intentionally side-effect free (it does NOT touch sys.stdout /
stderr, configure logging, or import heavy deps) so it can be unit-tested
without corrupting the test runner's output capture.

Issue context (log audit 2026-07-16):
  #6  QUIET_PATHS lists heartbeat/health endpoints whose access logs are noisy
      and must be emitted at DEBUG instead of INFO.
  #5  Chat requests/completions log (truncated) prompt + answer so failures are
      diagnosable from the log alone; failures log the error at ERROR.
"""
from __future__ import annotations

import re

# Heartbeat/health endpoints whose access logs are noisy -> DEBUG only.
# (/status is polled ~every 30s by the TUI and would otherwise flood the log.)
QUIET_PATHS = {"/status", "/models"}

PROMPT_PREVIEW_LEN = 300
ANSWER_PREVIEW_LEN = 200
ERROR_PREVIEW_LEN = 300

_SECRET_PATTERNS = (
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)(\bbearer\s+)([^\s,;\"']+)"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)([^\s,;]+)"),
)

_CANCELLED_RESULT_PREFIXES = (
    "[cancelled",
    "[workflow cancelled",
)

_TIMEOUT_RESULT_PREFIXES = (
    "[build paused",
    "[task_stall_timeout]",
    "[task_max_time]",
    "[stall]",
    "[max_time]",
    "[workflow timeout",
    "[no input: question timed out]",
)

_FAILED_RESULT_PREFIXES = (
    "[agent error",
    "[pipeline error",
    "[model unavailable]",
    "[build failed",
    "[build incomplete",
    "[executor error]",
    "[evidence failed",
    "[error",
    "[blocked",
    "[rejected",
    "[dry-run]",
    "[max tool-call rounds reached]",
    "[search error",
    "[workflow error",
    "error:",
    "download failed:",
    "failed to ",
    "i could not verify the requested current information from external sources",
)

_TRACE_STATUS_BY_RESULT_STATUS = {
    "succeeded": "ok",
    "failed": "error",
    "timed_out": "timeout",
    "cancelled": "cancelled",
}


def redact_sensitive(value: object) -> str:
    """Return a log-safe string with common credential forms removed."""
    text = str(value)
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]", text)
    return _SECRET_PATTERNS[3].sub(r"\1\2[REDACTED]", text)


def classify_agent_result(answer: str) -> tuple[str, str]:
    """Classify AgentV2/build/tool string results without changing their API."""
    stripped = answer.strip()
    lowered = stripped.lower()
    if lowered.startswith(_CANCELLED_RESULT_PREFIXES):
        return "cancelled", stripped
    if lowered.startswith(_TIMEOUT_RESULT_PREFIXES):
        return "timed_out", stripped
    if lowered.startswith(_FAILED_RESULT_PREFIXES):
        if "timed out" in lowered:
            return "timed_out", stripped
        return "failed", stripped
    return "succeeded", answer


def trace_status_for_result(answer: str) -> tuple[str, str]:
    """Return the tracing status and normalized detail for a string result."""
    result_status, detail = classify_agent_result(answer)
    return _TRACE_STATUS_BY_RESULT_STATUS[result_status], detail


def tool_display_status(answer: str) -> str:
    """Map a tool result to the status vocabulary supported by both TUIs."""
    result_status, _ = classify_agent_result(answer)
    if result_status == "succeeded":
        return "success"
    if result_status == "timed_out":
        return "timeout"
    return "error"


def _with_run_id(extra: dict, run_id: str | None) -> dict:
    if run_id:
        extra["run_id"] = run_id
    return extra


def log_chat_request(logger, mode: str, message: str, run_id: str | None = None) -> None:
    """Log an incoming chat request with a truncated, redacted prompt."""
    logger.info("Chat request", extra=_with_run_id({
        "mode": mode,
        "prompt_len": len(message),
        "prompt": redact_sensitive(message)[:PROMPT_PREVIEW_LEN],
    }, run_id))


def log_chat_completed(
    logger,
    mode: str,
    answer: str,
    run_id: str | None = None,
    status: str = "succeeded",
) -> None:
    """Log a successful chat turn with a redacted answer preview."""
    logger.info("Chat completed", extra=_with_run_id({
        "mode": mode,
        "status": status,
        "answer_len": len(answer),
        "answer_preview": redact_sensitive(answer)[:ANSWER_PREVIEW_LEN],
    }, run_id))


def log_chat_error(
    logger,
    mode: str,
    error: Exception | str,
    run_id: str | None = None,
    status: str = "failed",
) -> None:
    """Log a failed chat turn at ERROR with redacted detail and status."""
    logger.error("Chat failed", extra=_with_run_id({
        "mode": mode,
        "status": status,
        "error": redact_sensitive(error)[:ERROR_PREVIEW_LEN],
    }, run_id))
