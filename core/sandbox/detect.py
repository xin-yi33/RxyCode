"""沙箱后端能力探测（v1.4.1）。

只做只读探测（PATH 查找 / sys.platform），不 spawn 任何进程。
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SandboxCapabilities:
    """当前平台可用的最强沙箱后端。"""

    platform: str                        # "windows" | "linux" | "macos" | "other"
    backend: str                         # "job+token" | "bwrap" | "seatbelt" | "none"
    available: bool
    detail: str = ""
    checks: dict = field(default_factory=dict)


def detect_capabilities(os_name: str | None = None) -> SandboxCapabilities:
    """探测本机最强可用后端（不 spawn、不触网）。"""
    name = os_name or sys.platform
    if name == "win32":
        # Job Object + 受限令牌均为 NT 内置；真实可用性由 windows.py 的运行期路径再证。
        return SandboxCapabilities(
            platform="windows",
            backend="job+token",
            available=True,
            detail="Windows Job Object（内核限额 + kill-on-close）+ 受限令牌原语",
        )
    if name.startswith("linux"):
        bwrap = shutil.which("bwrap")
        return SandboxCapabilities(
            platform="linux",
            backend="bwrap" if bwrap else "none",
            available=bool(bwrap),
            detail="bubblewrap" if bwrap else "bubblewrap 不在 PATH",
            checks={"bwrap_path": bwrap or ""},
        )
    if name == "darwin":
        seatbelt = shutil.which("sandbox-exec")
        return SandboxCapabilities(
            platform="macos",
            backend="seatbelt" if seatbelt else "none",
            available=bool(seatbelt),
            detail="sandbox-exec（Seatbelt）" if seatbelt else "sandbox-exec 不在 PATH",
            checks={"sandbox_exec_path": seatbelt or ""},
        )
    return SandboxCapabilities(
        platform="other", backend="none", available=False, detail=f"不支持的平台: {name}"
    )
