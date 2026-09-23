"""Plugin adapter contract.

New connectors register as catalog data + a package under plugins/<name>/.
This module must not import the agent graph or orchestrator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_NAME = "catalog.json"


def bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / CATALOG_NAME


def load_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else bundled_catalog_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    rows = raw.get("plugins") if isinstance(raw, dict) else raw
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            out.append(dict(row))
    return out


def catalog_entry(name: str, path: Path | None = None) -> dict[str, Any] | None:
    wanted = (name or "").strip().lower()
    for row in load_catalog(path):
        if str(row.get("name") or "").strip().lower() == wanted:
            return row
    return None


def adapter_kind(manifest: dict[str, Any] | None, catalog_row: dict[str, Any] | None = None) -> str:
    for source in (manifest, catalog_row):
        if not isinstance(source, dict):
            continue
        kind = str(source.get("adapter") or source.get("connect") or "").strip().lower()
        if kind:
            return kind
    if isinstance(manifest, dict) and manifest.get("mcp"):
        return "mcp"
    return "zip"
