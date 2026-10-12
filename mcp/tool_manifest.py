"""Per-server MCP tool manifest baseline + drift detection (2026-10-12).

A malicious or compromised MCP server can silently change its tool surface — a
new tool, a rewritten description (prompt injection), a widened schema. Because
agent_v2 re-registers on ``tools/list_changed`` without review, that silent
upgrade was invisible to the user.  This module records what each server
*promised* at the last accepted state: a per-tool hash of
``(description, canonical inputSchema, outputSchema)`` persisted at
``<data_dir>/mcp/tool_manifests.json``.  On reconnect, the registration path
compares the fresh signature with the stored baseline and surfaces drift
(log warning + ``_mcp_runtime`` aggregate) so an operator can re-review.  The
matching model is fail-open: registration proceeds, and the *new* signature
immediately becomes the baseline — the alert fires once per actual change,
not on every reconnect.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

try:
    from ..config.settings import get_data_dir
except ImportError:
    from config.settings import get_data_dir

_logger = logging.getLogger(__name__)

_MANIFEST_FILE = "tool_manifests.json"


def manifest_path() -> Path:
    return get_data_dir() / "mcp" / _MANIFEST_FILE


def signature_for_tools(tools: dict[str, Any]) -> dict[str, str]:
    """Return ``{qualified_tool_name: sha256_hex}`` for a server's tool map.

    Tool objects may be LangChain StructuredTool instances or MCPClient MCPTool
    dataclasses; description and both schemas are canonicalized with sorted-key
    JSON so trivial key reordering does not count as drift.
    """
    signature: dict[str, str] = {}
    for name, tool in (tools or {}).items():
        description = str(getattr(tool, "description", "") or "")
        schema = getattr(tool, "args_schema", None) or getattr(tool, "parameters", None)
        output = getattr(tool, "output_schema", None)
        doc = json.dumps(
            {
                "description": description,
                "inputSchema": schema,
                "outputSchema": output,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        signature[str(name)] = hashlib.sha256(doc.encode("utf-8")).hexdigest()
    return signature


def diff_signatures(
    old: dict[str, str], new: dict[str, str]
) -> dict[str, list[str]]:
    """Classify drift between a persisted baseline and a fresh signature."""
    old = old or {}
    new = new or {}
    return {
        "added": sorted(name for name in new if name not in old),
        "removed": sorted(name for name in old if name not in new),
        "changed": sorted(
            name for name in new if name in old and old[name] != new[name]
        ),
    }


def load_manifest_store(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Read the persisted baselines; corrupt files degrade to empty."""
    path = path or manifest_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    servers = raw.get("servers")
    if not isinstance(servers, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for server, signature in servers.items():
        if isinstance(signature, dict):
            cleaned[str(server)] = {
                str(tool): str(digest) for tool, digest in signature.items()
            }
    return cleaned


def save_manifest_store(
    store: dict[str, dict[str, str]], path: Path | None = None
) -> None:
    """Persist baselines atomically; failures are audit-log-only (fail-open)."""
    path = path or manifest_path()
    payload = json.dumps(
        {"version": 1, "servers": store}, ensure_ascii=False, indent=2, sort_keys=True
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(path)
    except OSError:
        _logger.warning("could not persist MCP tool manifest store %s", path)
