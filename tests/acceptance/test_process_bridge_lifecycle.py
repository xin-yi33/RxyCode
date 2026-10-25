"""Independent lifecycle checks for the physical process-observation bridge."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core import session_runtime
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools import bash as bash_mod
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from rxycode_worker import registration_helper as registration_helper_module
from rxycode_worker.ctl import CtlServer, TurnChannel, ctl_call
from rxycode_worker.process_observer import (
    ProcessObserverRegistry,
    RemoteProcessObserver,
)

HELPER = Path(registration_helper_module.__file__).resolve()


def _config(workspace: Path) -> dict[str, Any]:
    return {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": ["write", "danger"],
        },
        "execution": {
            "sandbox_mode": "host",
            "workspace_root": str(workspace),
            "max_memory_mb": 0,
            "max_processes": 0,
            "tool_timeout_seconds": 30,
            "os_sandbox": {"enabled": False},
        },
    }


def _wire_runtime(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> dict[str, Any]:
    config = _config(workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    monkeypatch.delenv("RXYCODE_MANAGED_SHELL", raising=False)
    return config


class _Judge:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, Any]]] = []

    async def __call__(self, payload: dict[str, Any]) -> dict[str, str]:
        self.calls.append((time.monotonic(), dict(payload)))
        return {"action": "continue", "note": "bridge lifecycle probe"}


class _WindowObserver:
    """Lifecycle observer with synthetic samples and a real user command."""

    def __init__(self, proxy_script: Path | None = None, marker: Path | None = None) -> None:
        self.wraps: list[str] = []
        self.primes: list[tuple[str, str]] = []
        self.samples: list[str] = []
        self.cancels: list[str] = []
        self.released: list[str] = []
        self.proxy_script = proxy_script
        self.marker = marker
        self.prime_event = asyncio.Event()
        self.release_gate = asyncio.Event()
        self.delay_releases = False

    def wrap_argv(self, argv: list[str], process_key: str) -> list[str]:
        self.wraps.append(process_key)
        if self.proxy_script is not None and self.marker is not None:
            return [
                sys.executable,
                str(self.proxy_script),
                str(self.marker),
                "--",
                *argv,
            ]
        return list(argv)

    async def prime(self, process_key: str, window_id: str) -> bool:
        self.primes.append((process_key, window_id))
        self.prime_event.set()
        return True

    async def sample(self, window_id: str) -> tuple[float, int, int, int]:
        self.samples.append(window_id)
        return 20.0, 0, 1, 4096

    async def cancel(self, window_id: str) -> None:
        self.cancels.append(window_id)

    async def release_process(self, process_key: str) -> None:
        if self.delay_releases:
            await self.release_gate.wait()
        self.released.append(process_key)


def _state_commands(workspace: Path) -> tuple[str, str]:
    subdir = workspace / "nested"
    subdir.mkdir()
    if os.name == "nt":
        quoted = str(subdir).replace("'", "''")
        first = (
            "$env:RXY_BRIDGE_STATE='kept'; "
            f"Set-Location -LiteralPath '{quoted}'; "
            "Write-Output 'RXY_STATE_SET'"
        )
        second = (
            "Write-Output ('RXY_STATE=' + $env:RXY_BRIDGE_STATE + "
            "';CWD=' + (Get-Location).Path); Start-Sleep -Seconds 6"
        )
    else:
        first = (
            "export RXY_BRIDGE_STATE=kept; "
            f"cd -- {shlex.quote(str(subdir))}; "
            "printf 'RXY_STATE_SET\\n'"
        )
        second = (
            "printf 'RXY_STATE=%s;CWD=%s\\n' "
            '"$RXY_BRIDGE_STATE" "$PWD"; sleep 6'
        )
    return first, second


@pytest.mark.asyncio
async def test_ctl_peer_credentials_scope_only_process_registration(
    tmp_path: Path,
) -> None:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return dict(args)

    server = CtlServer(
        tmp_path / "ctl.sock",
        {"echo": handler, "process_register": handler},
    )
    ordinary_args = {
        "x": 5,
        "_peer_pid": "client-pid",
        "_peer_uid": "client-uid",
        "_peer_gid": "client-gid",
    }
    ordinary = await server._dispatch(
        json.dumps({"op": "echo", "args": ordinary_args}).encode(),
        peer_credentials=(101, 202, 303),
    )
    assert ordinary == {"ok": True, "result": ordinary_args}

    process_key = "a" * 64
    registered = await server._dispatch(
        json.dumps(
            {
                "op": "process_register",
                "args": {
                    "process_key": process_key,
                    "_peer_pid": "client-pid",
                    "_peer_uid": "client-uid",
                    "_peer_gid": "client-gid",
                },
            }
        ).encode(),
        peer_credentials=(101, 202, 303),
    )
    assert registered == {
        "ok": True,
        "result": {
            "process_key": process_key,
            "_peer_pid": 101,
            "_peer_uid": 202,
            "_peer_gid": 303,
        },
    }

    unavailable = await server._dispatch(
        json.dumps(
            {
                "op": "process_register",
                "args": {
                    "process_key": process_key,
                    "_peer_pid": 999,
                    "_peer_uid": 999,
                    "_peer_gid": 999,
                },
            }
        ).encode()
    )
    assert unavailable == {"ok": True, "result": {"process_key": process_key}}


@pytest.mark.asyncio
async def test_default_managed_shell_keeps_state_for_real_five_second_probe(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = isolated_runtime.workspace
    config = _wire_runtime(monkeypatch, workspace)
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_observe_seconds",
        5.0,
        raising=False,
    )

    session_id = "accept-bridge-default"
    session_token = session_runtime.bind_session(session_id)
    emitted: list[Any] = []
    tui_token = ToolOrchestrator.bind_event_tui(
        ProtocolTui(session_id, emitted.append)
    )
    judge = _Judge()
    orchestrator = ToolOrchestrator(
        tool_registry=default_registry,
        liveness_judge=judge,
    )
    orchestrator.register("bash", bash_mod.bash_tool)
    first, second = _state_commands(workspace)
    try:
        session_runtime.set_working_directory(workspace, persist=False)
        first_result = await orchestrator.execute_tool(
            "bash",
            {
                "command": first,
                "description": "set managed-shell state",
                "workdir": "",
                "timeout": 20,
            },
            call_id="accept-default-first",
            config=config,
        )
        identity = ps.state_identity(session_id=session_id)
        assert identity in ps.started_identities()
        managed = await ps.acquire_shell(identity=identity, cwd=str(workspace))
        managed_pid = managed.pid
        assert managed_pid is not None

        monkeypatch.setattr(
            shell_module.shell_executor,
            "watchdog_checkpoints",
            (0.3, 25.0),
            raising=False,
        )
        started = time.monotonic()
        second_result = await orchestrator.execute_tool(
            "bash",
            {
                "command": second,
                "description": "verify state and observe default window",
                "workdir": "",
                "timeout": 20,
            },
            call_id="accept-default-second",
            config=config,
        )
        elapsed = time.monotonic() - started
    finally:
        orchestrator.shutdown_sync_executor(wait=True)
        await ps.release_all()
        ToolOrchestrator.reset_event_tui(tui_token)
        session_runtime.reset_session_binding(session_token)

    assert "RXY_STATE_SET" in str(first_result)
    assert "RXY_STATE=kept" in str(second_result)
    assert os.path.normcase(str(workspace / "nested")) in os.path.normcase(
        str(second_result)
    )
    assert ps.state_identity(session_id=session_id) not in ps.started_identities()
    assert elapsed >= 4.8
    assert len(judge.calls) == 1
    judged_at, payload = judge.calls[0]
    assert judged_at - started >= 4.8
    assert payload["pid"] == managed_pid
    assert payload["observation_seconds"] == 5.0
    assert payload["process_count"] > 0
    liveness = [
        item
        for item in emitted
        if getattr(item, "details", None) is not None
        and item.details.kind == "process_liveness"
    ]
    assert len(liveness) == 1
    assert liveness[0].details.observation_seconds == 5.0
    assert liveness[0].details.pid == managed_pid


@pytest.mark.asyncio
async def test_two_checkpoints_share_registration_but_isolate_windows(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = isolated_runtime.workspace
    config = _wire_runtime(monkeypatch, workspace)
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_observe_seconds",
        0.06,
        raising=False,
    )

    proxy_script = tmp_path / "managed_launcher.py"
    proxy_marker = tmp_path / "managed_launcher.started"
    proxy_script.write_text(
        "import pathlib, subprocess, sys\n"
        "pathlib.Path(sys.argv[1]).write_text('started', encoding='utf-8')\n"
        "raise SystemExit(subprocess.call(sys.argv[3:]))\n",
        encoding="utf-8",
    )
    observer = _WindowObserver(proxy_script, proxy_marker)
    observer_token = shell_module.bind_process_observer(observer)
    session_id = "accept-bridge-windows"
    session_token = session_runtime.bind_session(session_id)
    judge = _Judge()
    emitted: list[Any] = []
    tui_token = ToolOrchestrator.bind_event_tui(
        ProtocolTui(session_id, emitted.append)
    )
    orchestrator = ToolOrchestrator(
        tool_registry=default_registry,
        liveness_judge=judge,
    )
    orchestrator.register("bash", bash_mod.bash_tool)
    if os.name == "nt":
        command = "Write-Output 'RXY_WINDOWED'; Start-Sleep -Seconds 1"
    else:
        command = "printf 'RXY_WINDOWED\\n'; sleep 1"
    try:
        session_runtime.set_working_directory(workspace, persist=False)
        short = await orchestrator.execute_tool(
            "bash",
            {
                "command": "Write-Output 'RXY_SHORT'" if os.name == "nt" else "printf 'RXY_SHORT\\n'",
                "description": "start managed shell",
                "workdir": "",
                "timeout": 10,
            },
            call_id="accept-windows-short",
            config=config,
        )
        monkeypatch.setattr(
            shell_module.shell_executor,
            "watchdog_checkpoints",
            (0.08, 0.22, 25.0),
            raising=False,
        )
        long = await orchestrator.execute_tool(
            "bash",
            {
                "command": command,
                "description": "run two observation checkpoints",
                "workdir": "",
                "timeout": 10,
            },
            call_id="accept-windows-long",
            config=config,
        )
        assert len(observer.wraps) == 1
        registration_key = observer.wraps[0]
        assert registration_key not in observer.released
        checkpoint_windows = [window for _, window in observer.primes]
        assert len(checkpoint_windows) == 2
        assert len(set(checkpoint_windows)) == 2

        observer.prime_event.clear()
        observer.delay_releases = True
        cancelled = asyncio.create_task(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": (
                        "Start-Sleep -Seconds 30"
                        if os.name == "nt"
                        else "sleep 30"
                    ),
                    "description": "cancel during managed observation",
                    "workdir": "",
                    "timeout": 60,
                },
                call_id="accept-windows-cancel",
                config=config,
            )
        )
        await asyncio.wait_for(observer.prime_event.wait(), timeout=2)
        cancel_started = time.monotonic()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cancelled, timeout=2)
        cancel_elapsed = time.monotonic() - cancel_started
    finally:
        orchestrator.shutdown_sync_executor(wait=True)
        await ps.release_all()
        observer.release_gate.set()
        await asyncio.sleep(0.02)
        ToolOrchestrator.reset_event_tui(tui_token)
        session_runtime.reset_session_binding(session_token)
        shell_module.reset_process_observer(observer_token)

    assert "RXY_SHORT" in str(short)
    assert "RXY_WINDOWED" in str(long)
    assert cancel_elapsed < 2.0
    assert len(observer.wraps) == 1
    process_key = registration_key
    assert {key for key, _ in observer.primes} == {process_key}
    windows = [window for _, window in observer.primes]
    assert len(windows) == 3
    assert len(set(windows)) == 3
    assert len(judge.calls) == 2
    assert [payload["seq"] for _, payload in judge.calls] == [1, 2]
    liveness = [
        item
        for item in emitted
        if getattr(item, "details", None) is not None
        and item.details.kind == "process_liveness"
    ]
    assert len(liveness) == 2
    assert len({item.details.probe_id for item in liveness}) == 2
    assert set(checkpoint_windows).issubset(observer.cancels)
    assert windows[2] in observer.cancels
    assert observer.released.count(process_key) == 1
    assert proxy_marker.exists(), (
        "production sandbox callback replaced the observer-wrapped managed argv"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SO_PEERCRED"),
    reason="kernel SO_PEERCRED registration requires POSIX/Linux",
)
async def test_real_ctl_registers_kernel_peer_and_keeps_windows_independent(
    tmp_path: Path,
) -> None:
    sock_path = tmp_path / "ctl.sock"
    go_path = tmp_path / "go"
    helper_pid_path = tmp_path / "helper.pid"
    root_script = tmp_path / "root.py"
    root_script.write_text(
        "import json, pathlib, subprocess, sys, time\n"
        "go = pathlib.Path(sys.argv[1])\n"
        "argv = json.loads(sys.argv[2])\n"
        "while not go.exists():\n"
        "    time.sleep(0.01)\n"
        "child = subprocess.Popen(argv)\n"
        "while child.poll() is None:\n"
        "    time.sleep(0.02)\n"
        "raise SystemExit(child.returncode)\n",
        encoding="utf-8",
    )
    child_code = (
        "import os, pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    process_key = "a" * 64
    window_one = "b" * 64
    window_two = "c" * 64
    registry = ProcessObserverRegistry(max_processes=4, max_windows=4)
    registrations: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def register(args: dict[str, Any]) -> dict[str, Any]:
        result = registry.register(args)
        registrations.append((dict(args), dict(result)))
        return result

    server = CtlServer(
        sock_path,
        {
            "process_register": register,
            "process_observe_start": registry.observe_start,
            "process_observe_sample": registry.observe_sample,
            "process_observe_cancel": registry.observe_cancel,
            "process_release": registry.release_process,
        },
    )
    root: subprocess.Popen[bytes] | None = None
    observed_pid = 0
    try:
        await server.start()
        channel = TurnChannel(sock_path)
        observer = RemoteProcessObserver(channel)
        wrapped = observer.wrap_argv(
            [
                sys.executable,
                "-c",
                child_code,
                str(helper_pid_path),
            ],
            process_key,
        )
        root = subprocess.Popen(
            [
                sys.executable,
                str(root_script),
                str(go_path),
                json.dumps(wrapped),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        registry.bind_root(root.pid, psutil.Process(root.pid).create_time())
        go_path.write_text("go", encoding="utf-8")

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if helper_pid_path.exists() and registrations:
                observed_pid = int(helper_pid_path.read_text(encoding="utf-8"))
                break
            await asyncio.sleep(0.02)
        assert observed_pid > 0
        assert registrations
        peer_args, peer_result = registrations[0]
        assert peer_result["registered"] is True
        assert peer_args["_peer_pid"] == observed_pid

        assert await observer.prime(process_key, window_one) is True
        first_sample = await observer.sample(window_one)
        assert first_sample is not None
        assert first_sample[2] > 0
        assert await observer.prime(process_key, window_two) is True
        assert await observer.sample(window_two) is not None
        await observer.cancel(window_one)
        assert await observer.sample(window_one) is None
        assert await observer.sample(window_two) is not None

        forged = await asyncio.to_thread(
            ctl_call,
            sock_path,
            "process_register",
            process_key="d" * 64,
            _peer_pid=observed_pid,
        )
        assert forged["registered"] is False
        assert forged["reason"] == "peer_not_bound"

        await observer.release_process(process_key)
        assert await observer.prime(process_key, "e" * 64) is False
    finally:
        registry.close()
        if observed_pid > 0:
            try:
                proc = psutil.Process(observed_pid)
                if proc.is_running():
                    proc.kill()
                    proc.wait(timeout=5)
            except psutil.Error:
                pass
        if root is not None and root.poll() is None:
            root.kill()
            root.wait(timeout=5)
        await server.stop()


@pytest.mark.skipif(os.name != "posix", reason="registration helper uses POSIX exec")
@pytest.mark.asyncio
async def test_helper_timeout_preserves_original_once_path_and_env(
    tmp_path: Path,
) -> None:
    sock_path = tmp_path / "unresponsive.sock"
    accepted = asyncio.Event()
    release = asyncio.Event()
    writers: list[asyncio.StreamWriter] = []

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        accepted.set()
        try:
            await reader.read(65536)
            await release.wait()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_unix_server(hold, path=str(sock_path))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    count_path = tmp_path / "count.txt"
    observed_path = tmp_path / "observed.txt"
    executable = bin_dir / "rxy-helper-probe"
    executable.write_text(
        "#!/bin/sh\n"
        "printf 'run\\n' >> \"$1\"\n"
        "printf '%s\\n%s\\n' \"$RXY_BRIDGE_ENV\" \"$PATH\" > \"$2\"\n"
        "exit 7\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["RXY_BRIDGE_ENV"] = "kept"
    process: asyncio.subprocess.Process | None = None
    try:
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            str(HELPER),
            "--socket",
            str(sock_path),
            "--process-key",
            "f" * 64,
            "--timeout",
            "0.3",
            "--",
            "rxy-helper-probe",
            str(count_path),
            str(observed_path),
            env=env,
        )
        returncode = await asyncio.wait_for(process.wait(), timeout=3)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.close()
        await server.wait_closed()
        for writer in writers:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    assert accepted.is_set()
    assert returncode == 7
    assert elapsed < 2.0
    assert count_path.read_text(encoding="utf-8").splitlines() == ["run"]
    observed = observed_path.read_text(encoding="utf-8").splitlines()
    assert observed[0] == "kept"
    assert str(bin_dir) in observed[1].split(os.pathsep)
