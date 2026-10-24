"""Regression coverage for Web-only kernel-bound process observation."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from RxyCode.RxyCode1_1_0.utils import shell
from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core import session_runtime
from RxyCode.RxyCode1_1_0.core.persistent_shell import ManagedShell
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools import bash as bash_mod
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from rxycode_worker.process_observer import (
    ProcessObserverRegistry,
    RemoteProcessObserver,
)


class _UnavailableSampler:
    available = False
    reason = "process_denied"

    def __init__(self, _pid: int | None) -> None:
        pass

    def sample(self) -> tuple[float, int, int, int]:
        return 0.0, 0, 0, 0


@pytest.mark.asyncio
async def test_unavailable_sample_is_unknown_without_judge_or_details(monkeypatch) -> None:
    monkeypatch.setattr(shell, "ProcessTreeSampler", _UnavailableSampler)
    judged: list[dict] = []
    reported: list[tuple[str, dict | None]] = []

    async def judge(payload: dict) -> dict[str, str]:
        judged.append(payload)
        return {"action": "continue", "note": "must not run"}

    async def reporter(text: str, details: dict | None) -> None:
        reported.append((text, details))

    token = shell.bind_process_probe(
        judge,
        call_id="call-unavailable",
        generation=1,
        reporter=reporter,
    )
    try:
        result = await shell.run_process_probe(
            123,
            elapsed_seconds=180.0,
            observe_seconds=0.05,
        )
    finally:
        shell.reset_process_probe(token)

    assert result is not None
    assert result.action == "unknown"
    assert result.details == {}
    assert judged == []
    assert len(reported) == 1
    assert reported[0][1] is None
    assert "观察不可用" in reported[0][0]


class _FakeObserver:
    def wrap_argv(self, argv: list[str], process_key: str) -> list[str]:
        return ["trusted-wrapper", process_key, *argv]


def test_web_wrapper_requires_bound_observer_context() -> None:
    argv = ["/bin/sh", "-c", "printf web"]
    assert shell.wrap_process_argv(argv) == argv

    observer_token = shell.bind_process_observer(_FakeObserver())
    probe_token = shell.bind_process_probe(
        None,
        call_id="call-wrap",
        generation=2,
    )
    try:
        wrapped = shell.wrap_process_argv(argv)
    finally:
        shell.reset_process_probe(probe_token)
        shell.reset_process_observer(observer_token)

    assert wrapped[0] == "trusted-wrapper"
    assert len(wrapped) == len(argv) + 2
    assert shell.wrap_process_argv(argv) == argv


class _SequenceObserver:
    def __init__(self) -> None:
        self.primes: list[tuple[str, str]] = []
        self.samples: list[str] = []
        self.cancels: list[str] = []
        self.released: list[str] = []

    async def prime(self, process_key: str, window_id: str) -> bool:
        self.primes.append((process_key, window_id))
        return True

    async def sample(self, window_id: str) -> tuple[float, int, int, int]:
        self.samples.append(window_id)
        return 20.0, 1024, 1, 4096

    async def cancel(self, window_id: str) -> None:
        self.cancels.append(window_id)

    async def release_process(self, process_key: str) -> None:
        self.released.append(process_key)


class _ManagedObserver(_SequenceObserver):
    def __init__(self) -> None:
        super().__init__()
        self.wraps: list[str] = []

    def wrap_argv(self, argv: list[str], process_key: str) -> list[str]:
        self.wraps.append(process_key)
        return list(argv)


@pytest.mark.asyncio
async def test_checkpoints_reuse_process_but_isolate_windows() -> None:
    observer = _SequenceObserver()
    reported: list[dict | None] = []

    async def judge(_payload: dict) -> dict[str, str]:
        return {"action": "continue", "note": "continue"}

    async def reporter(_text: str, details: dict | None) -> None:
        reported.append(details)

    observer_token = shell.bind_process_observer(observer)
    probe_token = shell.bind_process_probe(
        judge,
        call_id="multi-checkpoint",
        generation=1,
        reporter=reporter,
    )
    context = shell.current_process_probe()
    assert context is not None
    process_key = context.process_key
    try:
        first = await shell.run_process_probe(
            123,
            elapsed_seconds=180.0,
            observe_seconds=0.02,
        )
        second = await shell.run_process_probe(
            123,
            elapsed_seconds=300.0,
            observe_seconds=0.02,
        )
    finally:
        await shell.release_process_observation(process_key)
        shell.reset_process_probe(probe_token)
        shell.reset_process_observer(observer_token)

    assert first is not None and first.action == "continue"
    assert second is not None and second.action == "continue"
    assert {key for key, _ in observer.primes} == {process_key}
    assert len({window for _, window in observer.primes}) == 2
    assert len(set(observer.cancels)) == 2
    assert observer.released == [process_key]
    assert reported and all(value is not None for value in reported)


@pytest.mark.asyncio
async def test_managed_shell_registers_once_across_two_commands(tmp_path) -> None:
    observer = _ManagedObserver()
    observer_token = shell.bind_process_observer(observer)
    managed = ManagedShell(identity="bridge-managed", cwd=str(tmp_path))
    try:
        first = await managed.run("echo first", timeout=10)
        second = await managed.run("echo second", timeout=10)
        assert first.exit_code == 0
        assert second.exit_code == 0
        assert len(observer.wraps) == 1
        assert observer.wraps[0] == managed._process_registration_key
    finally:
        key = managed._process_registration_key
        await managed.close()
        await asyncio.sleep(0)
        shell.reset_process_observer(observer_token)
    assert observer.released == [key]


@pytest.mark.asyncio
async def test_tool_orchestrator_managed_path_keeps_registration_wrapper(
    isolated_runtime,
) -> None:
    marker = isolated_runtime.workspace / "managed-wrapper.marker"

    class MarkerObserver(_ManagedObserver):
        def wrap_argv(self, argv: list[str], process_key: str) -> list[str]:
            self.wraps.append(process_key)
            code = (
                "import os,pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_text('wrapped'); "
                "os.execv(sys.argv[2], sys.argv[2:])"
            )
            return [sys.executable, "-c", code, str(marker), *argv]

    observer = MarkerObserver()
    observer_token = shell.bind_process_observer(observer)
    session_token = session_runtime.bind_session("bridge-managed-orchestrator")
    orchestrator = ToolOrchestrator(tool_registry=default_registry)
    orchestrator.register("bash", bash_mod.bash_tool)
    config = {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": ["write", "danger"],
        },
        "execution": {
            "sandbox_mode": "host",
            "workspace_root": str(isolated_runtime.workspace),
            "os_sandbox": {"enabled": False},
        },
    }
    try:
        result = await orchestrator.execute_tool(
            "bash",
            {
                "command": "echo managed-wrapper-ok",
                "description": "managed production wrapper path",
                "workdir": "",
                "timeout": 20,
            },
            call_id="managed-wrapper-path",
            config=config,
        )
        assert "managed-wrapper-ok" in str(result)
        assert marker.read_text() == "wrapped"
        assert len(observer.wraps) == 1
    finally:
        orchestrator.shutdown_sync_executor(wait=True)
        await ps.release_all()
        session_runtime.reset_session_binding(session_token)
        shell.reset_process_observer(observer_token)


class _GateObserver(_SequenceObserver):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.sample_calls = 0

    async def prime(self, process_key: str, window_id: str) -> bool:
        self.entered.set()
        await self.release.wait()
        return False

    async def sample(self, window_id: str) -> tuple[float, int, int, int]:
        self.sample_calls += 1
        if self.sample_calls == 2:
            self.entered.set()
            await self.release.wait()
        return 20.0, 1024, 1, 4096

    async def cancel(self, window_id: str) -> None:
        await self.release.wait()
        await super().cancel(window_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prime", "sample2"])
async def test_completion_during_slow_prime_or_sample_never_reports_or_judges(
    stage,
) -> None:
    observer = _GateObserver()
    judged: list[dict] = []
    reported: list[str] = []

    async def judge(payload: dict) -> dict[str, str]:
        judged.append(payload)
        return {"action": "continue", "note": "late"}

    async def reporter(text: str, _details: dict | None) -> None:
        reported.append(text)

    completion = asyncio.Event()
    observer_token = shell.bind_process_observer(observer)
    probe_token = shell.bind_process_probe(
        judge,
        call_id=f"slow-{stage}",
        generation=1,
        reporter=reporter,
    )
    task = asyncio.create_task(
        shell.run_process_probe(
            123,
            elapsed_seconds=180.0,
            completion=completion,
            observe_seconds=0.02,
        )
    )
    try:
        await asyncio.wait_for(observer.entered.wait(), timeout=1)
        completion.set()
        observer.release.set()
        result = await asyncio.wait_for(task, timeout=1)
    finally:
        observer.release.set()
        task.cancel()
        shell.reset_process_probe(probe_token)
        shell.reset_process_observer(observer_token)

    assert result is None
    assert judged == []
    assert reported == []


@pytest.mark.asyncio
async def test_cancel_during_slow_prime_does_not_wait_for_remote_cleanup() -> None:
    observer = _GateObserver()
    observer_token = shell.bind_process_observer(observer)
    probe_token = shell.bind_process_probe(
        None,
        call_id="cancel-slow",
        generation=1,
    )
    task = asyncio.create_task(
        shell.run_process_probe(
            123,
            elapsed_seconds=180.0,
            observe_seconds=0.02,
        )
    )
    try:
        await asyncio.wait_for(observer.entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        observer.release.set()
        shell.reset_process_probe(probe_token)
        shell.reset_process_observer(observer_token)


def test_registry_binds_kernel_peer_to_descendant_and_rejects_reuse() -> None:
    descendant = None
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wrapper = None
    registry = ProcessObserverRegistry(max_processes=2)
    process_key = "a" * 64
    window1 = "b" * 64
    window2 = "c" * 64
    try:
        # Make one short-lived bwrap-like root with one actual descendant.
        wrapper = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
                "time.sleep(20)",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            values = psutil.Process(wrapper.pid).children(recursive=True)
            if values:
                descendant = values[0]
                break
            time.sleep(0.02)
        assert descendant is not None
        registry.bind_root(wrapper.pid, psutil.Process(wrapper.pid).create_time())
        assert registry.register(
            {"_peer_pid": descendant.pid, "process_key": process_key}
        )[
            "registered"
        ]
        assert registry.register(
            {"_peer_pid": descendant.pid, "process_key": process_key}
        )[
            "reason"
        ] == "duplicate"
        assert registry.register({"_peer_pid": sibling.pid, "process_key": "d" * 64})[
            "reason"
        ] == "peer_not_bound"
        assert registry.observe_start(
            {"process_key": process_key, "window_id": window1}
        )["available"] is True
        assert registry.observe_sample({"window_id": window1})["available"] is True
        assert registry.observe_cancel({"window_id": window1})["cancelled"] is True
        assert registry.observe_sample({"window_id": window1})["reason"] == "not_observing"
        assert registry.observe_start(
            {"process_key": process_key, "window_id": window2}
        )["available"] is True
        assert registry.release_process({"process_key": process_key})["released"] is True
        assert registry.observe_sample({"window_id": window2})["reason"] == "not_observing"
    finally:
        registry.close()
        for process in (sibling, wrapper):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        if descendant is not None:
            try:
                if descendant.is_running():
                    descendant.kill()
                    descendant.wait(timeout=5)
            except psutil.Error:
                pass


def test_remote_observer_wrapper_uses_stdlib_helper_and_original_argv() -> None:
    class Channel:
        sock_path = "/control/ctl.sock"

    observer = RemoteProcessObserver(Channel())
    original = ["/bin/sh", "-c", "printf ok"]
    wrapped = observer.wrap_argv(original, "c" * 64)

    assert wrapped[1:3] == ["-I", "-S"]
    assert wrapped[3].endswith("registration_helper.py")
    assert wrapped[-4:] == ["--", *original]
    assert "--process-key" in wrapped
    assert "--timeout" in wrapped


@pytest.mark.skipif(os.name != "posix", reason="execv PID identity is POSIX-only")
def test_registration_helper_preserves_pid_and_exit_code(tmp_path) -> None:
    helper = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "rxycode-worker"
        / "src"
        / "rxycode_worker"
        / "registration_helper.py"
    )
    output = tmp_path / "pid.txt"
    command = [
        sys.executable,
        "-I",
        "-S",
        helper,
        "--socket",
        str(tmp_path / "missing.sock"),
        "--process-key",
        "d" * 64,
        "--timeout",
        "5",
        "--",
        "rxy-path-exec",
        str(output),
    ]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "rxy-path-exec"
    executable.write_text(
        "#!/bin/sh\n"
        f"{sys.executable} -c 'import os,pathlib,sys; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))' \"$1\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    process = subprocess.Popen(command, env=env)
    assert process.wait(timeout=10) == 0
    assert int(output.read_text()) == process.pid


@pytest.mark.skipif(os.name != "posix", reason="helper exec path is POSIX-only")
def test_registration_helper_timeout_still_execs_original_once(tmp_path) -> None:
    helper = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "rxycode-worker"
        / "src"
        / "rxycode_worker"
        / "registration_helper.py"
    )
    sock_path = tmp_path / "ctl.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def hold_connection() -> None:
        connection, _ = server.accept()
        try:
            connection.recv(4096)
            time.sleep(0.5)
        finally:
            connection.close()

    worker = threading.Thread(target=hold_connection, daemon=True)
    output = tmp_path / "executed.txt"
    command = [
        sys.executable,
        "-I",
        "-S",
        str(helper),
        "--socket",
        str(sock_path),
        "--process-key",
        "e" * 64,
        "--timeout",
        "0.1",
        "--",
        "rxy-timeout-command",
        str(output),
    ]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    executable = bindir / "rxy-timeout-command"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib,sys\n"
        "pathlib.Path(sys.argv[1]).write_text('once')\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    worker.start()
    try:
        process = subprocess.Popen(command, env=env)
        assert process.wait(timeout=3) == 0
    finally:
        server.close()
        worker.join(timeout=2)

    assert output.read_text() == "once"
