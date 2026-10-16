"""Append-only local audit. Secrets and clipboard text are not stored."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SECRET = re.compile(
    r"(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+",
)
_SECRET_KEYS = {
    "clipboard",
    "api_key",
    "token",
    "secret",
    "password",
    "authorization",
    "access_token",
    "device_token",
}
_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, row: dict[str, Any]) -> None:
        cleaned: dict[str, str] = {}
        for key, value in row.items():
            if key.casefold() in _SECRET_KEYS:
                cleaned[key] = "[redacted]"
                continue
            text = _SECRET.sub("[redacted]", str(value))
            cleaned[key] = _BEARER.sub("Bearer [redacted]", text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
