"""WEB-W4-C01. Local full runs a native process and refuses a sandbox."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _rel in (
    Path("packages") / "rxycode-runner" / "src",
    Path("packages") / "rxycode-core" / "src",
):
    _src = REPO / _rel
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


def _session(pid: int) -> int:
    value = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.c_uint(pid), ctypes.byref(value))
    if not ok:
        raise OSError(ctypes.GetLastError())
    return int(value.value)


def test_w4_c01_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A local full shell is a native pid in this session and is not wrapped."""
    import asyncio

    from execution.tool_orchestrator import ToolOrchestrator
    from rxycode_core.runtime.execution_port import (
        ExecutionPort,
        bind_execution_port,
        reset_execution_port,
    )
    from tools.bash import bash_tool

    wrapped: list[object] = []

    def spy(*args: object, **kwargs: object) -> object:
        wrapped.append(args)
        raise AssertionError("full mode called wrap_command")

    monkeypatch.setattr("core.sandbox.manager.wrap_command", spy)
    code = (
        "import ctypes,os; v=ctypes.c_ulong(); "
        "ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(v)); "
        "print(int(v.value))"
    )
    argv = [sys.executable, "-c", code]
    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    port = ExecutionPort()
    token = bind_execution_port(port)
    try:
        text = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                {"argv": argv, "command": code, "target": "local", "cwd": str(tmp_path)},
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
        )
    finally:
        reset_execution_port(token)
    assert wrapped == []
    assert str(_session(os.getpid())) in text
    assert port.local_full is not None
    assert any(item["approval"] == "skipped" for item in port.local_full.audit)


def test_w4_c01_negative() -> None:
    """Full mode rejects an injected sandbox instead of wrapping the command."""
    from rxycode_runner.local.native_backend import LocalNativeBackend

    backend = LocalNativeBackend(target="local", permission="full")

    class SandboxBackend:
        def wrap_command(self, argv: list[str]) -> list[str]:
            return ["bwrap", *argv]

    with pytest.raises(PermissionError, match="SANDBOX_FORBIDDEN"):
        backend.attach_sandbox(SandboxBackend())
