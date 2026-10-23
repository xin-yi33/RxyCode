"""Per-server MCP tool manifest baseline + drift detection (2026-10-12).

A malicious or compromised MCP server can silently change its tool surface — a
new tool, a rewritten description (prompt injection), a widened schema. Because
agent_v2 re-registers on ``tools/list_changed`` without review, that silent
upgrade was invisible to the user.  This module records what each server
*promised* at the last accepted state: a per-tool hash persisted at
``<data_dir>/mcp/tool_manifests.json``.  On reconnect, the registration path
compares the fresh signature with the stored baseline and surfaces drift
(log warning + ``_mcp_runtime`` aggregate) so an operator can re-review.  The
matching model is fail-open **by design**: registration proceeds, and the
*new* signature immediately becomes the baseline — the alert fires once per
actual change, not on every reconnect.

2026-10-12 K3 复审接缝修正：

* 签名覆盖**原始 MCP schema**（StructuredTool 的 ``args_schema`` 是 pydantic
  类，直接序列化只得到 repr，参数类型漂移漏报）；MCP 适配器把原始
  ``inputSchema``/``outputSchema`` 放进 ``metadata['mcp_input_schema']`` /
  ``['mcp_output_schema']``，签名优先使用，语义化回退
  ``model_json_schema()``。
* 基线文件的读-改-写合并进跨进程锁（appserver 与 worker/多个窗口并发时
  相互丢记录的缺陷），并提供 :func:`update_baseline` / :func:`remove_baseline`
  原子操作；加载时逐条类型校验——结构错误的条目被丢弃并记 warning，不再让
  ``raw.get`` 在 list 上抛 AttributeError 而静默跳过复核。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    from ..config.settings import get_data_dir
except ImportError:
    from config.settings import get_data_dir

_logger = logging.getLogger(__name__)

_MANIFEST_FILE = "tool_manifests.json"


def manifest_path() -> Path:
    return get_data_dir() / "mcp" / _MANIFEST_FILE


@contextmanager
def _manifest_lock(path: Path) -> Iterator[None]:
    """Exclusive cross-process lock around read-modify-write of the store.

    Mirrors appserver/task_store._cross_process_lock (kept separate so mcp/
    does not import appserver/).
    """
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() < 1:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 5.0
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    time.sleep(0.02)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _canonical_schema(value: Any) -> Any:
    """Return a JSON-canonical schema for hashing.

    ``StructuredTool.args_schema`` may be a pydantic model class; normalize it
    through ``model_json_schema()`` so a parameter-type change alters the
    digest (K3-1 漏报修复）。Unknown shapes fall back to ``default=str`` in the
    caller's ``json.dumps``.
    """
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    model_json_schema = getattr(value, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            return model_json_schema()
        except Exception:  # noqa: BLE001 — degraded hash beats a crash
            return value
    return value


def signature_for_tools(tools: dict[str, Any]) -> dict[str, str]:
    """Return ``{qualified_tool_name: sha256_hex}`` for a server's tool map.

    Hashes **raw** input/output JSON schemas (``metadata['mcp_input_schema']``
    / ``['mcp_output_schema']`` when present) plus the description, with
    sorted-key JSON so trivial key reordering does not count as drift.
    """
    signature: dict[str, str] = {}
    for name, tool in (tools or {}).items():
        description = str(getattr(tool, "description", "") or "")
        metadata = getattr(tool, "metadata", None)
        input_schema = None
        output_schema = None
        if isinstance(metadata, dict):
            input_schema = metadata.get("mcp_input_schema")
            output_schema = metadata.get("mcp_output_schema")
        if input_schema is None:
            input_schema = getattr(tool, "parameters", None) or getattr(
                tool, "args_schema", None
            )
        if output_schema is None:
            output_schema = getattr(tool, "output_schema", None)
        doc = json.dumps(
            {
                "description": description,
                "inputSchema": _canonical_schema(input_schema),
                "outputSchema": _canonical_schema(output_schema),
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


def _normalize_store(raw: Any, path: Path) -> dict[str, dict[str, str]]:
    """Validate the parsed JSON strictly; malformed entries are dropped.

    2026-10-12 K3-4：顶层不是 dict（旧版本/probe 写了 list）或条目类型错误
    时记录 warning 并只丢坏条目，不再靠 AttributeError 静默跳过复核。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _logger.warning(
            "MCP tool manifest %s has non-dict top level (%s); treating as empty",
            path,
            type(raw).__name__,
        )
        return {}
    servers = raw.get("servers")
    if servers is None:
        return {}
    if not isinstance(servers, dict):
        _logger.warning(
            "MCP tool manifest %s has non-dict 'servers' field; treating as empty",
            path,
        )
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for server, signature in servers.items():
        if not isinstance(signature, dict):
            _logger.warning(
                "MCP tool manifest %s drops malformed entry for server %r",
                path,
                server,
            )
            continue
        valid = {
            str(tool): digest
            for tool, digest in signature.items()
            if isinstance(digest, str)
        }
        if len(valid) != len(signature):
            _logger.warning(
                "MCP tool manifest %s drops %d non-string digests for server %r",
                path,
                len(signature) - len(valid),
                server,
            )
        cleaned[str(server)] = valid
    return cleaned


def load_manifest_store(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Read the persisted baselines; corrupt files degrade to empty."""
    path = path or manifest_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return _normalize_store(raw, path)


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


def update_baseline(
    server: str, signature: dict[str, str], path: Path | None = None
) -> None:
    """Lock, merge the server's new signature over disk, and persist.

    Read-modify-write under the cross-process lock so two appservers/windows
    recording different servers concurrently cannot clobber each other
    (K3-4). Deleting nothing here; only this server's slice is replaced.
    """
    path = path or manifest_path()
    try:
        with _manifest_lock(path):
            store = load_manifest_store(path)
            store[str(server)] = {str(k): str(v) for k, v in signature.items()}
            save_manifest_store(store, path)
    except OSError:
        _logger.warning("could not update MCP tool manifest baseline for %s", server)


def remove_baseline(server: str, path: Path | None = None) -> None:
    """Lock and delete one server's baseline (removed from config)."""
    path = path or manifest_path()
    try:
        with _manifest_lock(path):
            store = load_manifest_store(path)
            if store.pop(server, None) is not None:
                save_manifest_store(store, path)
    except OSError:
        _logger.warning("could not remove MCP tool manifest baseline for %s", server)
