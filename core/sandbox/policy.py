"""OS 级沙箱策略（v1.4.1，仿 Codex：受限执行面 + 显式降级）。

执行面（v1.4.1）：utils/shell.py 的 bash 子进程 spawn 点
（``asyncio.create_subprocess_exec`` 前后——argv 包装 / Windows Job 指派）。
非执行面（v1.4.1 不覆盖，诚实登记）：
- write/edit/patch 文件工具由 core/safety/policy.py 写白名单管（软件闸，不变）；
- MCP stdio server / Playwright 浏览器 / Desktop GUI 子进程未纳入（附录登记项）。

语言/进程约束：纯 stdlib（bwrap/seatbelt 以命令行调用为准，Windows 用 ctypes），
无第三方依赖；后端只做纯函数/纯系统调用，不读 config（config 只经本模块进入）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DENY_READ_GLOBS: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
    "**/.ssh/**",
    "**/*.pem",
    "**/.aws/**",
    "**/credentials*",
)


@dataclass(frozen=True)
class SandboxPolicy:
    """一次命令执行的沙箱策略。"""

    enabled: bool = False
    mode: str = "workspace"                       # "workspace" | "read-only"
    workspace_root: Path = Path(".")
    network: str = "none"                         # "none" | "inherit"
    deny_read_globs: tuple[str, ...] = DEFAULT_DENY_READ_GLOBS
    max_memory_mb: int = 0                        # 0=不限（Windows Job 内核限额；独立于 psutil 软限）
    max_processes: int = 0                        # 0=不限
    extra_write_roots: tuple[Path, ...] = ()
    on_missing_capability: str = "downgrade"      # "downgrade"（显式响亮降级）| "fail_closed"

    def validate(self) -> None:
        if self.mode not in ("workspace", "read-only"):
            raise ValueError(
                f"os_sandbox.mode 非法: {self.mode!r}（允许 workspace | read-only）"
            )
        if self.network not in ("none", "inherit"):
            raise ValueError(
                f"os_sandbox.network 非法: {self.network!r}（允许 none | inherit）"
            )
        if self.on_missing_capability not in ("downgrade", "fail_closed"):
            raise ValueError(
                "os_sandbox.on_missing_capability 非法: "
                f"{self.on_missing_capability!r}（允许 downgrade | fail_closed）"
            )
        if self.max_memory_mb < 0 or self.max_processes < 0:
            raise ValueError("os_sandbox 的 max_memory_mb/max_processes 不得为负")


def from_config(cfg: dict[str, Any] | None, *, workspace_root: Path) -> SandboxPolicy:
    """从 ``execution.os_sandbox`` 节构建策略（唯一 config 入口）。

    约定（v1.4.1 默认）：enabled=False——先以显式开关交付，烧熟后（E2E 稳定）再评估默认开。
    """
    execution = (cfg or {}).get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError("execution 节必须是映射")
    section = execution.get("os_sandbox") or {}
    if not isinstance(section, dict):
        raise ValueError("execution.os_sandbox 必须是映射")
    policy = SandboxPolicy(
        enabled=bool(section.get("enabled", False)),
        mode=str(section.get("mode", "workspace")).strip().lower() or "workspace",
        workspace_root=workspace_root,
        network=str(section.get("network", "none")).strip().lower() or "none",
        deny_read_globs=tuple(
            section.get("deny_read_globs") or DEFAULT_DENY_READ_GLOBS
        ),
        max_memory_mb=int(section.get("max_memory_mb", 0) or 0),
        max_processes=int(section.get("max_processes", 0) or 0),
        extra_write_roots=tuple(Path(p) for p in (section.get("extra_write_roots") or ())),
        on_missing_capability=str(section.get("on_missing_capability", "downgrade")),
    )
    policy.validate()
    return policy
