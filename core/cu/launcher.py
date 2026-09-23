"""Locate the open-computer-use stdio MCP binary. Never shell-concat."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .settings import configured_command

_MCP_BIN_NAMES = (
    "open-computer-use-mcp",
    "open-codex-computer-use-mcp",
)
_CLI_BIN_NAMES = ("open-computer-use", "ocu")


def _is_usable_command(path: str) -> bool:
    if not path:
        return False
    # PowerShell and cmd shims break stdio JSON-RPC (they steal stdin and
    # print a banner). The real entry is node + the package script.
    # 废弃代码（2026-09-22）：只拒绝 .ps1，放行 .cmd/.bat。Windows 的 which
    # 会命中 open-computer-use-mcp.CMD，initialize 收到的不是 JSON-RPC。
    # if lowered.endswith(".ps1"):
    #     return False
    lowered = path.lower()
    if lowered.endswith((".ps1", ".cmd", ".bat")):
        return False
    return True


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found and _is_usable_command(found):
        return found
    if sys.platform == "win32":
        # 废弃代码（2026-09-22）：which 再补 .cmd/.bat。外壳脚本破坏 JSON-RPC。
        # for suffix in (".cmd", ".exe", ".bat"):
        for suffix in (".exe",):
            found = shutil.which(name + suffix) if not name.endswith(suffix) else None
            if found and _is_usable_command(found):
                return found
    return None


def _node_package_bin() -> tuple[str, list[str]] | None:
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        return None
    candidates: list[Path] = []
    npm_root = os.environ.get("NODE_PATH")
    if npm_root:
        candidates.append(Path(npm_root))
    node_dir = Path(node).resolve().parent
    candidates.append(node_dir / "node_modules" / "open-computer-use" / "bin")
    # Global npm prefix on Windows is often the node directory itself.
    for prefix in (node_dir, Path(sys.prefix)):
        candidates.append(prefix / "node_modules" / "open-computer-use" / "bin")
    for folder in candidates:
        for script in ("open-computer-use-mcp", "ocu"):
            path = folder / script
            if path.is_file():
                # 废弃代码（2026-09-22）：mcp 脚本不加子命令。空参数会把帮助
                # 写进 stdout，主机报 MCP server emitted invalid JSON-RPC。
                # args = ["mcp"] if script == "ocu" else []
                return node, [str(path), "mcp"]
    return None


def resolve_ocu_mcp(config: dict[str, Any] | None = None) -> tuple[str, list[str]] | None:
    """Return ``(command, args)`` for ``open-computer-use mcp``, or None."""
    override = configured_command(config)
    if override is not None:
        return override
    for name in _MCP_BIN_NAMES:
        found = _which(name)
        if found:
            return found, []
    for name in _CLI_BIN_NAMES:
        found = _which(name)
        if found:
            return found, ["mcp"]
    packaged = _node_package_bin()
    if packaged is not None:
        return packaged
    return None


def mcp_server_config(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    resolved = resolve_ocu_mcp(config)
    if resolved is None:
        return None
    command, args = resolved
    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "timeout": 30,
    }
