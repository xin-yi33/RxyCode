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


def _alive(pid: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return int(code.value) == 259


def _session(pid: int) -> int:
    value = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.c_uint(pid), ctypes.byref(value))
    if not ok:
        raise OSError(ctypes.GetLastError())
    return int(value.value)


def test_w4_c01_contract(monkeypatch: pytest.MonkeyPatch) -> None:
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
    work = REPO / "tests" / "web" / "w4" / "_run"
    work.mkdir(parents=True, exist_ok=True)
    command = f'{sys.executable} -c "{code}"'
    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    port = ExecutionPort()
    token = bind_execution_port(port)
    try:
        text = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": command,
                    "target": "local",
                    "workdir": str(work),
                    "timeout": 30,
                },
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
        )
        failed = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": f'{sys.executable} -c "import sys; sys.exit(3)"',
                    "target": "local",
                    "workdir": str(work),
                    "timeout": 30,
                },
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
        )
        pidfile = work / "slow.pid"

        async def slow_call() -> tuple[str, float, float]:
            import time

            stamps: list[float] = []

            async def tick() -> None:
                await asyncio.sleep(0.2)
                stamps.append(time.perf_counter())

            task = asyncio.create_task(tick())
            text = await orchestrator.execute_tool(
                "bash",
                {
                    "command": (
                        f"{sys.executable} -c \"import os,time,pathlib; "
                        f"pathlib.Path(r'{pidfile}').write_text(str(os.getpid())); "
                        "time.sleep(30)\""
                    ),
                    "target": "local",
                    "workdir": str(work),
                    "timeout": 1,
                },
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
            finished = time.perf_counter()
            await task
            return text, (stamps[0] if stamps else finished), finished

        slow, stamped, finished = asyncio.run(slow_call())
        assert stamped < finished - 0.3
        kill_file = work / "kill.pid"

        async def kill_call() -> None:
            async def stop() -> None:
                for _ in range(50):
                    backend = port.local_full
                    if kill_file.is_file() and backend is not None and backend._live:
                        backend.kill(next(iter(backend._live)))
                        return
                    await asyncio.sleep(0.05)

            stopper = asyncio.create_task(stop())
            await orchestrator.execute_tool(
                "bash",
                {
                    "command": (
                        f"{sys.executable} -c \"import os,time,pathlib; "
                        f"pathlib.Path(r'{kill_file}').write_text(str(os.getpid())); "
                        "time.sleep(30)\""
                    ),
                    "target": "local",
                    "workdir": str(work),
                    "timeout": 10,
                },
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
            await stopper

        asyncio.run(kill_call())
        assert kill_file.is_file()
        assert _alive(int(kill_file.read_text(encoding="utf-8").strip())) is False
        assert any(item.get("approval") == "killed" for item in port.local_full.audit)
    finally:
        reset_execution_port(token)
    assert "exit code: 3" in failed
    assert "timeout" in slow
    assert pidfile.is_file()
    slow_pid = int(pidfile.read_text(encoding="utf-8").strip())
    assert _alive(slow_pid) is False
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
