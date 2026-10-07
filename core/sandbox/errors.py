"""OS 级沙箱错误类型（v1.4.1）。"""

from __future__ import annotations


class SandboxUnavailableError(RuntimeError):
    """要求的沙箱后端在当前平台/环境不可用（on_missing_capability=fail_closed 时抛出）。"""


class SandboxDeniedError(PermissionError):
    """沙箱策略拒绝该操作（如 bwrap/seatbelt/受限令牌覆盖不到的显式拒绝）。"""
