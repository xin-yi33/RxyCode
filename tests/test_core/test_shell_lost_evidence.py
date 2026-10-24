"""Lost-shell evidence: real process status is not a completion receipt."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core.session_runtime import (
    bind_session,
    reset_session_binding,
    set_working_directory,
)
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

pytestmark = pytest.mark.asyncio
WINDOWS = os.name == "nt"


@pytest.fixture(autouse=True)
async def _clean_shells():
    await ps.release_all()
    try:
        yield
    finally:
        await ps.release_all()


def _protocol(tmp_path):
    return ps._marker_protocol(str(tmp_path))


@pytest.mark.parametrize("workdir", ["", "/one call's dir; $(printf injected)"])
async def test_posix_protocol_paths_are_literal_shell_words(tmp_path, workdir):
    protocol = _protocol(tmp_path / "workspace's cwd; $(printf injected)")
    script = ps._build_wrapped_command("echo payload", protocol, powershell=False, workdir=workdir)
    tokens = shlex.split(script, posix=True)
    targets = [tokens[i + 1].removesuffix(";") for i, token in enumerate(tokens) if token == ">"]
    expected = [protocol.rc_file_path, protocol.cwd_file_path]
    if workdir:
        expected = [
            protocol.rc_file_path,
            protocol.err_file_path,
            protocol.cwd_file_path,
            *expected,
        ]
        assert tokens[tokens.index("cd") + 1] == workdir
    assert targets == expected


async def test_protocol_uses_initial_workspace_not_host_or_one_call_workdir(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace's cwd"
    workspace.mkdir()
    shell = ps.ManagedShell(identity="paths", cwd=str(workspace), argv=["fixture-shell"])
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda raw: None, drain=AsyncMock()),
        stdout=object(),
        returncode=None,
    )
    shell._process = process
    protocols = []

    async def collect(process, protocol, **kwargs):
        protocols.append(protocol)
        return ps.CommandOutcome(stdout="payload", exit_code=0)

    monkeypatch.setattr(shell, "_collect", collect)
    await shell._run_locked("echo payload", timeout=30, workdir=str(tmp_path / "one-call"))
    assert len(protocols) == 1
    assert all(Path(path).parent == workspace for path in ps._protocol_files(protocols[0]))


@pytest.mark.parametrize("returncode", [7, 0, -9])
@pytest.mark.parametrize("capture_output", [False, True])
async def test_eof_preserves_process_status_and_unflushed_output(
    tmp_path, returncode, capture_output
):
    protocol = _protocol(tmp_path)
    stream = asyncio.StreamReader()
    stream.feed_data((protocol.begin + "\npayload").encode())
    stream.feed_eof()
    process = SimpleNamespace(stdout=stream, returncode=None)

    async def reaped():
        # EOF can arrive before asyncio's child-exit notification.
        process.returncode = returncode
        return returncode

    process.wait = AsyncMock(side_effect=reaped)
    shell = ps.ManagedShell(identity="eof", cwd=str(tmp_path), argv=["fixture-shell"])
    capture = SimpleNamespace(feed=lambda name, raw: output.append((name, raw)))
    output = []
    with pytest.raises(ps.ShellLostError) as caught:
        await shell._collect(process, protocol, capture if capture_output else None)
    assert caught.value.exit_code == returncode
    assert caught.value.stdout == ("" if capture_output else "payload")
    assert output == ([("stdout", b"payload")] if capture_output else [])
    process.wait.assert_awaited_once()


async def test_exit_before_begin_is_not_attributed_to_the_command(tmp_path):
    protocol = _protocol(tmp_path)
    stream = asyncio.StreamReader()
    stream.feed_data(b"[exit code: 0] not a command receipt")
    stream.feed_eof()
    process = SimpleNamespace(stdout=stream, returncode=7, wait=AsyncMock())
    shell = ps.ManagedShell(identity="before-begin", cwd=str(tmp_path), argv=["fixture-shell"])
    with pytest.raises(ps.ShellLostError) as caught:
        await shell._collect(process, protocol)
    assert caught.value.exit_code is None
    assert caught.value.stdout == ""
    process.wait.assert_not_awaited()


@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
async def test_live_process_eof_does_not_invent_a_status(tmp_path, monkeypatch, interrupt):
    protocol = _protocol(tmp_path)
    stream = asyncio.StreamReader()
    stream.feed_data((protocol.begin + "\nnot a receipt").encode())
    stream.feed_eof()
    waiting = asyncio.Event()

    async def still_alive():
        waiting.set()
        await asyncio.Event().wait()

    process = SimpleNamespace(stdout=stream, returncode=None, wait=still_alive)
    shell = ps.ManagedShell(identity="live-eof", cwd=str(tmp_path), argv=["fixture-shell"])
    monkeypatch.setattr(shell, "ensure_started", AsyncMock())
    monkeypatch.setattr(shell, "close", AsyncMock())

    async def collect(*args, **kwargs):
        return await shell._collect(process, protocol)

    monkeypatch.setattr(shell, "_run_locked", collect)
    if interrupt == "timeout":

        async def expire(coro, **kwargs):
            task = asyncio.create_task(coro)
            try:
                await waiting.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            raise asyncio.TimeoutError

        monkeypatch.setattr(ps.asyncio, "wait_for", expire)
        with pytest.raises(ps.ShellLostError) as caught:
            await shell.run("unused", timeout=1)
        assert caught.value.exit_code is None
    else:
        task = asyncio.create_task(shell.run("unused", timeout=0))
        try:
            await waiting.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    shell.close.assert_awaited_once()
    assert process.returncode is None


@pytest.mark.parametrize("workspace_name", ["workspace", "workspace's cwd"])
@pytest.mark.parametrize("exit_code", [7, 0])
async def test_real_exit_through_tool_retains_failure_and_never_replays(
    tmp_path, monkeypatch, exit_code, workspace_name
):
    workspace = tmp_path / workspace_name
    workspace.mkdir()
    host = tmp_path / "host's cwd"
    host.mkdir()
    token = bind_session(f"real-exit-{exit_code}")
    set_working_directory(workspace, persist=False)
    marker = workspace / "once.txt"
    setup = "$lost_state = 'old'" if WINDOWS else "lost_state=old"
    command = (
        f"Add-Content -LiteralPath 'once.txt' -Value once; exit {exit_code}"
        if WINDOWS
        else f"printf 'once\\n' >> 'once.txt'; printf 'partial'; exit {exit_code}"
    )
    fresh = (
        'Write-Output "fresh[$lost_state]"' if WINDOWS else 'printf "fresh[%s]" "${lost_state-}"'
    )
    config = {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": ["write", "danger"],
        },
        "execution": {"sandbox_mode": "workspace", "os_sandbox": {"enabled": False}},
    }
    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)

    evidence = []

    async def call(text):
        capture_token = orchestrator.begin_evidence_capture()
        try:
            return str(
                await orchestrator.execute_tool(
                    "bash",
                    {"command": text, "description": "exit evidence", "workdir": "", "timeout": 30},
                    config=config,
                )
            )
        finally:
            evidence[:] = orchestrator.end_evidence_capture(capture_token)

    try:
        with monkeypatch.context() as host_context:
            host_context.chdir(host)
            setup_result = await call(setup)
            assert not setup_result.startswith("[error")
            assert evidence[0].status == "succeeded"
            shell = next(iter(ps._SHELLS.values()))
            result = await call(command)
        assert result.startswith("[error executing bash:")
        assert f"[exit code: {exit_code}]" in result
        assert "environment was lost" in result
        assert "next command starts a fresh shell" in result
        if not WINDOWS:
            assert "partial" in result
        assert len(evidence) == 1
        assert evidence[0].status == "failed"
        assert evidence[0].exit_code == exit_code
        assert not shell.alive
        assert not ps.active_identities()
        assert not list(tmp_path.rglob(".rxy_*.tmp"))
        assert list(host.iterdir()) == []
        assert marker.read_text().splitlines() == ["once"]
        assert "fresh[]" in await call(fresh)
        assert evidence[0].exit_code is None
        assert evidence[0].status == "succeeded"
        assert next(iter(ps._SHELLS.values())) is not shell
        assert marker.read_text().splitlines() == ["once"]
    finally:
        await ps.release_all()
        reset_session_binding(token)
