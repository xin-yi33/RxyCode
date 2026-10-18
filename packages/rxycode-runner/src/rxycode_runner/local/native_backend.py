"""Local full runs on this machine. It does not call the sandbox wrapper."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)


def _reaping_manager():
    """core/sandbox manager with the checkout-local import fallback."""
    try:
        from core.sandbox import manager
    except ImportError:
        from RxyCode.RxyCode1_1_0.core.sandbox import manager
    return manager


def _reaping_windows():
    """windows sandbox primitives (reaping bind-failure path only)."""
    try:
        from core.sandbox import windows
    except ImportError:
        from RxyCode.RxyCode1_1_0.core.sandbox import windows
    return windows


@dataclass
class NativeResult:
    started: bool
    wrapped: bool
    argv: list[str]
    approval: str
    pid: int | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass
class LocalNativeBackend:
    target: str
    permission: str
    audit: list[dict[str, object]] = field(default_factory=list)
    _children: dict[int, subprocess.Popen[bytes]] = field(default_factory=dict)
    _live: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.target != "local":
            raise ValueError("target must be local")
        if self.permission not in {"full", "ask"}:
            raise ValueError("permission must be full or ask")

    def attach_sandbox(self, backend: object) -> None:
        del backend
        raise PermissionError("SANDBOX_FORBIDDEN")

    def start(self, argv: list[str], cwd: Path) -> NativeResult:
        if self.permission != "full":
            raise PermissionError("ASK_REQUIRED")
        return self._spawn(argv, cwd, approval="skipped", wait=False, timeout=None)

    async def shell(self, argv: list[str], cwd: Path, *, timeout: float = 1800) -> NativeResult:
        if self.permission == "ask":
            decision = await self._ask(argv)
            if decision != "approved":
                self.audit.append(
                    {
                        "argv": list(argv),
                        "approval": "rejected",
                        "started": False,
                        "wrapped": False,
                    }
                )
                return NativeResult(
                    started=False,
                    wrapped=False,
                    argv=list(argv),
                    approval="rejected",
                )
            return await asyncio.to_thread(
                self._spawn,
                argv,
                cwd,
                approval="approved",
                wait=True,
                timeout=timeout,
            )
        return await asyncio.to_thread(
            self._spawn,
            argv,
            cwd,
            approval="skipped",
            wait=True,
            timeout=timeout,
        )

    async def run_command(
        self, argv: list[str] | str, cwd: Path, *, timeout: float = 1800
    ) -> NativeResult:
        """Run the exact command the policy already checked.

        ``argv`` list spawns via ``create_subprocess_exec``（orchestrator 传
        ShellExecutor 构建的 argv——full 与其它模式同一个 shell）；``str``
        保留 ``create_subprocess_shell`` 兼容路径。Windows 下子进程出生即
        绑定 reaping-only Job（kill-on-close，无限额）：worker 死亡整树
        回收。回收不是安全边界——创建/绑定失败仅告警并照常执行。
        """
        recorded = list(argv) if isinstance(argv, list) else [argv]
        spawn_kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        job_handle = 0
        if os.name == "nt":
            spawn_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            # 进程级 reaping-only Job（WEB-W7-C02）：kill-on-close，无限额。
            # 句柄进程级缓存、worker 死亡时由 OS 关闭触发整树回收——按命令
            # 关闭会把 agent 有意 Start-Process 的后台进程一并杀死。回收
            # 不是安全边界——建/绑失败只警告，命令照常执行。
            job_handle = _reaping_manager().reaping_job_handle()
            if job_handle:
                # CREATE_SUSPENDED（winbase.h 0x4）：subprocess 无此常量。
                spawn_kwargs["creationflags"] = int(
                    spawn_kwargs["creationflags"]
                ) | 0x00000004
        if isinstance(argv, list):
            proc = await asyncio.create_subprocess_exec(*argv, **spawn_kwargs)
        else:
            proc = await asyncio.create_subprocess_shell(argv, **spawn_kwargs)
        if job_handle:
            try:
                _reaping_manager().bind_spawned_process(job_handle, proc.pid)
            except Exception as exc:  # noqa: BLE001 - reaping 失败不阻塞命令
                _logger.warning(
                    "reaping job 绑定失败（%s），命令将无回收保证执行", exc
                )
                try:
                    _reaping_windows().resume_process_main_thread(proc.pid)
                except Exception:  # noqa: BLE001 - 已告警，命令继续
                    pass
                # 句柄不随命令关闭：进程级存活，root 若已入 Job，worker
                # 死亡时 kill-on-close 仍生效。
        self._live.add(proc.pid)
        timed_out = False
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_tree(proc.pid)
            timed_out = True
            try:
                out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                out_b, err_b = await proc.communicate()
        except asyncio.CancelledError:
            _kill_tree(proc.pid)
            raise
        finally:
            self._live.discard(proc.pid)
        stdout = (out_b or b"").decode("utf-8", errors="replace")
        stderr = (err_b or b"").decode("utf-8", errors="replace")
        result = NativeResult(
            started=True,
            wrapped=False,
            argv=recorded,
            approval="skipped",
            pid=proc.pid,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
        self.audit.append(
            {
                "pid": proc.pid,
                "argv": recorded,
                "approval": "skipped",
                "started": True,
                "wrapped": False,
            }
        )
        return result

    def kill(self, pid: int) -> None:
        known = pid in self._live or pid in self._children
        if not known:
            return
        _kill_tree(pid)
        proc = self._children.get(pid)
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._live.discard(pid)
        self.audit.append({"pid": pid, "approval": "killed", "wrapped": False})

    async def _ask(self, argv: list[str]) -> str:
        try:
            from core.safety.approval import (
                ApprovalDecision,
                ApprovalRequest,
                get_approval_broker,
            )
            from core.safety.policy import RiskLevel
        except ImportError:
            from RxyCode.RxyCode1_1_0.core.safety.approval import (
                ApprovalDecision,
                ApprovalRequest,
                get_approval_broker,
            )
            from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
        broker = get_approval_broker()
        if broker is None:
            return "rejected"
        decision = await broker.request_approval(
            ApprovalRequest(
                tool_name="shell",
                args_summary={"argv": list(argv)},
                risk=RiskLevel.DANGER,
            )
        )
        allowed = {
            ApprovalDecision.APPROVED,
            ApprovalDecision.ALLOW_ONCE,
            ApprovalDecision.ALWAYS_ALLOW_LEVEL,
        }
        return "approved" if decision in allowed else "rejected"

    def _spawn(
        self,
        argv: list[str] | str,
        cwd: Path,
        *,
        approval: str,
        wait: bool,
        timeout: float | None,
        shell: bool = False,
    ) -> NativeResult:
        recorded = [argv] if isinstance(argv, str) else list(argv)
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
        )
        self._children[proc.pid] = proc
        stdout = ""
        stderr = ""
        exit_code = None
        timed_out = False
        if wait:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc.pid)
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, err = proc.communicate()
                timed_out = True
            stdout = out.decode("utf-8", errors="replace")
            stderr = err.decode("utf-8", errors="replace")
            exit_code = proc.returncode
        result = NativeResult(
            started=True,
            wrapped=False,
            argv=recorded,
            approval=approval,
            pid=proc.pid,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
        self.audit.append(
            {
                "pid": proc.pid,
                "argv": recorded,
                "approval": approval,
                "started": True,
                "wrapped": False,
            }
        )
        return result


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        return
