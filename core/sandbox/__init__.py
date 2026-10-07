"""OS 级沙箱（v1.4.1）：仿 Codex 的受限执行面。

公开 API：
- ``SandboxPolicy`` / ``from_config`` —— 策略（config 唯一入口）
- ``detect_capabilities`` —— 只读能力探测
- ``wrap_command`` —— spawn 前 argv 包装
- ``open_sandbox_job`` / ``bind_spawned_process`` —— Windows 出生即绑定
  （2026-10-07 起；``apply_post_spawn`` 为后补枚举，仅兼容保留）
- ``SandboxUnavailableError`` / ``SandboxDeniedError``

平台后端：``windows.py``（Job Object + 受限令牌）、``linux.py``（bubblewrap）、
``macos.py``（Seatbelt）。``types.py`` 为 spawn 交付物数据类（2026-10-06 起
独立成模块，避免 manager 与后端之间的循环导入）。
"""

from .detect import SandboxCapabilities, detect_capabilities
from .errors import SandboxDeniedError, SandboxUnavailableError
from .manager import (
    apply_post_spawn,
    bind_spawned_process,
    open_sandbox_job,
    wrap_command,
)
from .policy import DEFAULT_DENY_READ_GLOBS, SandboxPolicy, from_config
from .types import JobPlan, WrappedCommand

__all__ = [
    "DEFAULT_DENY_READ_GLOBS",
    "JobPlan",
    "SandboxCapabilities",
    "SandboxDeniedError",
    "SandboxPolicy",
    "SandboxUnavailableError",
    "WrappedCommand",
    "apply_post_spawn",
    "bind_spawned_process",
    "detect_capabilities",
    "from_config",
    "open_sandbox_job",
    "wrap_command",
]
