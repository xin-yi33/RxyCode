"""Safety audit log: append-only JSONL record of every gated tool call.

Adapted from OpenHands (MIT) openhands/security/ audit-trail concept.
Writes to ~/.rxycode/logs/audit.jsonl (reusing config/settings.py
get_data_dir). Failures are swallowed — auditing must never break a run.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, load_config
from RxyCode.RxyCode1_1_0.log.log_helpers import redact_sensitive
from RxyCode.RxyCode1_1_0.log.logger import get_current_run_id

from ..log_retention import rotate_file
from .policy import RiskLevel

_logger = logging.getLogger(__name__)
_FAILURE_ALERT_STREAK = 3

#: Keys matching any of these (case-insensitive substring) are redacted.
SENSITIVE_KEY_PATTERNS = ("api_key", "apikey", "password", "passwd", "secret", "token", "authorization")

_MAX_VALUE_CHARS = 200


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(pat in k for pat in SENSITIVE_KEY_PATTERNS)


def sanitize_args(args: Any, max_chars: int = _MAX_VALUE_CHARS) -> Any:
    """Recursively redact sensitive keys and inline credentials."""
    if isinstance(args, dict):
        out = {}
        for k, v in args.items():
            if _is_sensitive_key(str(k)):
                out[k] = "***"
            else:
                out[k] = sanitize_args(v, max_chars)
        return out
    if isinstance(args, (list, tuple)):
        return [sanitize_args(v, max_chars) for v in args]
    if isinstance(args, str):
        try:
            args = redact_sensitive(args)
        except Exception:
            pass
        return args[:max_chars] + "..." if len(args) > max_chars else args
    return args


def _default_path() -> Path:
    try:
        base = get_data_dir()
    except Exception:
        base = Path.home() / ".rxycode"
    return base / "logs" / "audit.jsonl"


class ToolMetrics:
    """调用次数、成功率、平均耗时。不保留参数和结果正文。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, int] = defaultdict(int)
        self._failures: dict[str, int] = defaultdict(int)
        self._duration_ms: dict[str, float] = defaultdict(float)
        self._streak: dict[str, int] = defaultdict(int)

    def record(
        self,
        tool: str,
        *,
        succeeded: bool,
        duration_ms: float | None,
    ) -> int:
        with self._lock:
            self._calls[tool] += 1
            if succeeded:
                self._streak[tool] = 0
            else:
                self._failures[tool] += 1
                self._streak[tool] += 1
            if duration_ms is not None:
                self._duration_ms[tool] += max(0.0, float(duration_ms))
            return self._streak[tool]

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            out: dict[str, dict[str, float | int]] = {}
            for tool, calls in self._calls.items():
                failures = self._failures[tool]
                avg = self._duration_ms[tool] / calls if calls else 0.0
                out[tool] = {
                    "calls": calls,
                    "failures": failures,
                    "success_rate": round((calls - failures) / calls, 6) if calls else 0.0,
                    "avg_duration_ms": round(avg, 3),
                }
            return out


class AuditLogger:
    """Append-only JSONL audit writer. Thread-safe via a single lock."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        max_bytes: int | None = None,
        backup_count: int | None = None,
    ):
        self._path = Path(path) if path else _default_path()
        self._lock = threading.Lock()
        self.metrics = ToolMetrics()
        try:
            config = load_config().get("observability") or {}
        except Exception:
            config = {}
        try:
            self._max_bytes = max(
                0,
                int(
                    max_bytes
                    if max_bytes is not None
                    else config.get("audit_max_bytes", 10 * 1024 * 1024)
                ),
            )
        except (TypeError, ValueError):
            self._max_bytes = 10 * 1024 * 1024
        try:
            self._backup_count = max(
                0,
                int(
                    backup_count
                    if backup_count is not None
                    else config.get("audit_backup_count", 5)
                ),
            )
        except (TypeError, ValueError):
            self._backup_count = 5

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        tool: str,
        risk: RiskLevel,
        args: Any,
        approval: str,
        result: Any,
        *,
        duration_ms: float | None = None,
        session_id: str | None = None,
        context_id: str | None = None,
        outcome: str | None = None,
        executed: bool | None = None,
    ) -> None:
        """Append one record. ``approval`` is why the call was allowed to run."""
        try:
            run_id = get_current_run_id()
        except Exception:
            run_id = "unknown"

        result_s = result if isinstance(result, str) else repr(result)
        try:
            result_s = redact_sensitive(result_s)
        except Exception:
            result_s = sanitize_args(result_s)
        if len(result_s) > _MAX_VALUE_CHARS:
            result_s = result_s[:_MAX_VALUE_CHARS] + "..."

        streak = 0
        if outcome is not None:
            streak = self.metrics.record(
                tool,
                succeeded=outcome == "succeeded",
                duration_ms=duration_ms,
            )
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "run_id": run_id,
            "session_id": session_id or "",
            "context_id": context_id or "",
            "tool": tool,
            "risk": risk.name if isinstance(risk, RiskLevel) else str(risk),
            "args": sanitize_args(args),
            "approval": approval,
            "reason": approval,
            "outcome": outcome or "",
            "executed": executed,
            "duration_ms": None if duration_ms is None else round(max(0.0, float(duration_ms)), 3),
            "result": result_s,
        }
        line = json.dumps(record, ensure_ascii=False)
        self._write_line(line)
        self._maybe_alert(
            tool=tool,
            session_id=session_id or "",
            result_s=result_s,
            streak=streak,
            outcome=outcome,
        )
        _logger.info(
            "tool_call tool=%s outcome=%s duration_ms=%s session=%s approval=%s",
            tool,
            outcome or "",
            record["duration_ms"],
            session_id or "",
            approval,
        )

    def _maybe_alert(
        self,
        *,
        tool: str,
        session_id: str,
        result_s: str,
        streak: int,
        outcome: str | None,
    ) -> None:
        kinds: list[str] = []
        lowered = result_s.lower()
        if "timed out" in lowered:
            kinds.append("timeout")
        if "spill write failed" in lowered:
            kinds.append("resource")
        if outcome is not None and outcome != "succeeded" and streak == _FAILURE_ALERT_STREAK:
            kinds.append("frequent_failure")
        for kind in kinds:
            detail = f"{tool} {kind}"
            _logger.warning("tool_alert kind=%s tool=%s session=%s", kind, tool, session_id)
            alert = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "event": "alert",
                "kind": kind,
                "tool": tool,
                "session_id": session_id,
                "detail": detail,
            }
            self._write_line(json.dumps(alert, ensure_ascii=False))

    def _write_line(self, line: str) -> None:
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                rotate_file(
                    self._path,
                    incoming_bytes=len(line.encode("utf-8")) + 1,
                    max_bytes=self._max_bytes,
                    backup_count=self._backup_count,
                )
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            # Auditing is best-effort; never break the tool call.
            pass


_default_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = AuditLogger()
    return _default_logger
