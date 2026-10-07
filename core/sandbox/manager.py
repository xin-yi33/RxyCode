"""沙箱执行管理面（v1.4.1）：后端选择、argv 包装、降级/失败语义。

调用方只认识三个函数：
- ``wrap_command(policy, argv, cwd)`` → ``WrappedCommand``：spawn 前调用。
- ``open_sandbox_job(wrapped)`` → Job 句柄：spawn **前**调用（Windows；
  配合 CREATE_SUSPENDED 出生即绑定，2026-10-07 起替代 apply_post_spawn）。
- ``bind_spawned_process(job_handle, pid)``：spawn 后第一时间调用——
  指派 root 入 Job 并恢复其主线程。

语义纪律（local-agent-process-isolation 技能）：
- 能力缺失 → ``on_missing_capability="fail_closed"`` 抛 ``SandboxUnavailableError``；
  ``"downgrade"`` 则**显式响亮降级**（logger.warning + 返回值标记
  ``downgraded=True``），绝不静默 unsandbox。
- docker 模式与 os_sandbox 不叠加（docker 自带 OS 边界）——由调用方排除。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .detect import SandboxCapabilities, detect_capabilities
from .errors import SandboxUnavailableError
from .linux import build_bwrap_command      # 纯 stdlib argv 组装，无平台 API，可顶部导入
from .macos import build_seatbelt_command   # 纯 stdlib profile 生成，无平台 API，可顶部导入
from .policy import SandboxPolicy
from .types import JobPlan, WrappedCommand  # noqa: F401 —— 2026-10-06 起定义移入 types.py，此处仅 re-export 兼容旧导入点

_logger = logging.getLogger(__name__)


def _windows():
    """windows 后端的唯一懒导入点（P7 懒导入预算纪律）：该模块 import 期绑
    ``ctypes.windll``，非 Windows 宿主不可加载，故保持函数内懒导入。"""
    from . import windows

    return windows


def resolve(policy: SandboxPolicy, os_name: str | None = None) -> SandboxCapabilities:
    """能力解析 + 降级/失败语义的唯一判定点。"""
    caps = detect_capabilities(os_name)
    if caps.available:
        return caps
    if policy.on_missing_capability == "fail_closed":
        raise SandboxUnavailableError(
            f"os_sandbox 要求沙箱但后端不可用：{caps.detail}（platform={caps.platform}）"
        )
    _logger.warning(
        "os_sandbox 显式降级：后端不可用（%s），本次命令不在 OS 沙箱内执行。"
        "要拒绝降级请设 execution.os_sandbox.on_missing_capability=fail_closed。",
        caps.detail,
    )
    return caps


def wrap_command(
    policy: SandboxPolicy,
    argv: list[str],
    cwd: Path,
    *,
    os_name: str | None = None,
) -> WrappedCommand:
    """spawn 前调用：按平台包装 argv / 生成 Job 计划。

    enabled=False → 原样返回（applied=False）。能力缺失按 policy 语义
    fail-closed 或响亮降级（返回 applied=False、downgraded=True）。
    """
    if not argv:
        raise ValueError("argv 为空")
    if not policy.enabled:
        return WrappedCommand(
            argv=list(argv), job_plan=None, backend="none",
            applied=False, detail="os_sandbox disabled",
        )
    policy.validate()
    caps = resolve(policy, os_name)
    if not caps.available:
        return WrappedCommand(
            argv=list(argv), job_plan=None, backend="none",
            applied=False, downgraded=True,
            detail=f"显式降级：{caps.detail}",
        )

    if caps.backend == "bwrap":
        return build_bwrap_command(policy, argv, cwd)
    if caps.backend == "seatbelt":
        return build_seatbelt_command(policy, argv, cwd)
    if caps.backend == "job+token":
        return _windows().plan_windows_command(policy, argv, cwd)
    raise SandboxUnavailableError(f"未知沙箱后端: {caps.backend}")


def open_sandbox_job(wrapped: WrappedCommand) -> int:
    """spawn **前**调用（Windows）：按 wrapped.job_plan 建空 Job，返回句柄。

    出生即绑定流（2026-10-07 验收修）：调用方随后用 CREATE_SUSPENDED 创建
    子进程、立即 :func:`bind_spawned_process` 指派并恢复主线程——suspended
    窗口内 root 一行代码未跑、不可能有子孙，根除后补枚举的竞态与 venv
    launcher 等自建 Job 的跨层级重归属（GetLastError=5）。

    返回 Job 句柄（非 Windows/未应用时 0）——**调用方持有并在命令收尾时关闭**；
    丢弃句柄会随 worker 生命周期累积泄漏（且 kill-on-close 永不触发）。
    """
    if not wrapped.applied or wrapped.job_plan is None:
        return 0
    if sys.platform != "win32":          # 防御：Job 计划只在 Windows 生成
        raise SandboxUnavailableError("Job 计划只能在 Windows 创建")
    return _windows().open_job(wrapped.job_plan)


def bind_spawned_process(job_handle: int, pid: int) -> None:
    """把 CREATE_SUSPENDED 出生的 root 指派进 Job 并恢复其主线程。

    指派失败抛 ``SandboxUnavailableError`` 且**不恢复线程**——root 从未运行，
    调用方直接终止即「整树回收」（无子孙可漏）。此后子孙随 Job 继承自动
    入列；子孙框架自建 Job（如 CPython 3.13 venv launcher）会合法嵌套在本
    Job 之下，kill-on-close 与限额沿层级生效，不再需要后补指派。
    """
    if not job_handle:
        return
    if sys.platform != "win32":
        raise SandboxUnavailableError("Job 绑定只能在 Windows 应用")
    windows = _windows()
    windows.assign_pid_to_job_handle(job_handle, pid)
    windows.resume_process_main_thread(pid)


# 废弃代码（2026-10-07 起）：生产执行面改 open_sandbox_job + bind_spawned_process
# （出生即绑定）。本函数的后补整树指派无法处理自建 Job 的子进程（venv
# launcher → AssignProcessToJobObject GetLastError=5），仅兼容保留，禁止新调用方。
def apply_post_spawn(policy: SandboxPolicy, wrapped: WrappedCommand, pid: int) -> int:
    """spawn 成功后调用：Windows Job 约束落到 pid（kill-on-close + 限额）。

    .. deprecated:: 2026-10-07
       生产改 :func:`open_sandbox_job` + :func:`bind_spawned_process`。
       本函数仅兼容保留：后补枚举只适用于子孙不自建 Job 的场景。

    必须整树指派：Job 语义只在指派后诞生的子孙自动入 Job，已存在的子孙
    要逐个指派，否则 kill-on-close 漏杀（2026-10-06 实测）。因此在
    create_subprocess_exec 返回的最早时刻调用本函数，可把「先发子孙已存在」
    的竞态压到最小。

    返回 Job 句柄（非 Windows/未应用时 0）——**调用方持有并在命令收尾时关闭**；
    丢弃句柄会随 worker 生命周期累积泄漏（且 kill-on-close 永不触发）。
    """
    del policy
    if not wrapped.applied or wrapped.job_plan is None:
        return 0
    if sys.platform != "win32":          # 防御：Job 计划只在 Windows 生成
        raise SandboxUnavailableError("Job 计划只能在 Windows 应用")
    return _windows().assign_job_to_tree(pid, wrapped.job_plan)
