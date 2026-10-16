"""Append-only local audit. Secrets and clipboard text are not stored."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SECRET = re.compile(r"sk-[A-Za-z0-9_-]+")


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, row: dict[str, Any]) -> None:
        cleaned: dict[str, str] = {}
        for key, value in row.items():
            if key == "clipboard":
                cleaned[key] = "[redacted]"
                continue
            cleaned[key] = _SECRET.sub("[redacted]", str(value))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
