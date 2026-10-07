"""沙箱 spawn 交付物类型（v1.4.1）。

``JobPlan`` / ``WrappedCommand`` 独立成模块，是为了让 manager 与平台后端
之间不出现循环导入：manager 顶部导入 linux/macos 构建器，后端从本模块
取类型。windows 后端仍由 manager 懒导入（其模块 import 期绑定 windll，
非 Windows 宿主不可加载）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobPlan:
    """spawn 后要落到进程上的 Windows Job 约束（无约束则全 0）。"""

    max_memory_bytes: int = 0
    max_processes: int = 0
    kill_on_close: bool = True


@dataclass(frozen=True)
class WrappedCommand:
    """spawn 交付物：最终 argv + 可选 Job 计划 + 实况报告。"""

    argv: list[str]
    job_plan: JobPlan | None
    backend: str                 # "bwrap" | "seatbelt" | "job+token" | "none"
    applied: bool                # 是否真加了沙箱层
    downgraded: bool = False     # 能力缺失发生了显式降级
    detail: str = ""
    cleanup: tuple[Path, ...] = ()   # 用后需清理的临时文件（如 seatbelt profile）
