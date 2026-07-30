"""Safety audit log: append-only JSONL record of every gated tool call.

Adapted from OpenHands (MIT) openhands/security/ audit-trail concept.
Writes to ~/.rxycode/logs/audit.jsonl (reusing config/settings.py
get_data_dir). Failures are swallowed — auditing must never break a run.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .policy import RiskLevel

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
            from ...log.log_helpers import redact_sensitive

            args = redact_sensitive(args)
        except Exception:
            pass
        return args[:max_chars] + "..." if len(args) > max_chars else args
    return args


def _default_path() -> Path:
    try:
        from ...config.settings import get_data_dir
        base = get_data_dir()
    except Exception:
        base = Path.home() / ".rxycode"
    return base / "logs" / "audit.jsonl"


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
        try:
            from ...config.settings import load_config

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
    ) -> None:
        """Append one record. ``approval`` is one of
        auto/approved/rejected/always/dry_run."""
        try:
            from ...log.logger import get_current_run_id
            run_id = get_current_run_id()
        except Exception:
            run_id = "unknown"

        result_s = result if isinstance(result, str) else repr(result)
        try:
            from ...log.log_helpers import redact_sensitive

            result_s = redact_sensitive(result_s)
        except Exception:
            result_s = sanitize_args(result_s)
        if len(result_s) > _MAX_VALUE_CHARS:
            result_s = result_s[:_MAX_VALUE_CHARS] + "..."

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "run_id": run_id,
            "tool": tool,
            "risk": risk.name if isinstance(risk, RiskLevel) else str(risk),
            "args": sanitize_args(args),
            "approval": approval,
            "result": result_s,
        }
        line = json.dumps(record, ensure_ascii=False)
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                from ..log_retention import rotate_file

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
