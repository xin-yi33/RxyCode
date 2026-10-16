"""Local full runs on this machine. It does not call the sandbox wrapper."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NativeResult:
    started: bool
    wrapped: bool
    argv: list[str]
    approval: str
    pid: int | None = None
    exit_code: int | None = None
    stdout: str = ""


@dataclass
class LocalNativeBackend:
    target: str
    permission: str
    audit: list[dict[str, object]] = field(default_factory=list)
    _children: dict[int, subprocess.Popen[bytes]] = field(default_factory=dict)

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
        return self._spawn(argv, cwd, approval="skipped", wait=False)

    async def shell(self, argv: list[str], cwd: Path) -> NativeResult:
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
            return self._spawn(argv, cwd, approval="approved", wait=True)
        return self._spawn(argv, cwd, approval="skipped", wait=True)

    def kill(self, pid: int) -> None:
        proc = self._children.get(pid)
        if proc is None or proc.poll() is not None:
            return
        proc.kill()
        proc.wait(timeout=5)
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

    def _spawn(self, argv: list[str], cwd: Path, *, approval: str, wait: bool) -> NativeResult:
        proc = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._children[proc.pid] = proc
        stdout = ""
        exit_code = None
        if wait:
            out, _err = proc.communicate(timeout=30)
            stdout = out.decode("utf-8", errors="replace")
            exit_code = proc.returncode
        result = NativeResult(
            started=True,
            wrapped=False,
            argv=list(argv),
            approval=approval,
            pid=proc.pid,
            exit_code=exit_code,
            stdout=stdout,
        )
        self.audit.append(
            {
                "pid": proc.pid,
                "argv": list(argv),
                "approval": approval,
                "started": True,
                "wrapped": False,
            }
        )
        return result
