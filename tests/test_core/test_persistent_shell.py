"""Managed persistent shell: state, cwd, isolation, workdir semantics.

Covers acceptance group A (state & isolation) and the completion-protocol
cases from group B.  These run REAL shell processes; they are not mocks.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async

pytestmark = pytest.mark.asyncio

IS_WINDOWS = os.name == "nt"


async def _reset():
    await ps.release_all()


@pytest.fixture(autouse=True)
async def _clean_shells():
    await ps.release_all()
    yield
    await ps.release_all()


class TestStatePersistence:
    async def test_variable_survives_between_calls(self):
        if IS_WINDOWS:
            await run_bash_async("$rxy_probe = 'v1'", "", "", 30)
            out = await run_bash_async("Write-Output $rxy_probe", "", "", 30)
        else:
            await run_bash_async("rxy_probe=v1", "", "", 30)
            out = await run_bash_async("echo $rxy_probe", "", "", 30)
        assert "v1" in out

    async def test_function_survives_between_calls(self):
        if IS_WINDOWS:
            await run_bash_async(
                "function rxy_fn { 'fn-ok' }", "", "", 30
            )
            out = await run_bash_async("rxy_fn", "", "", 30)
        else:
            await run_bash_async("rxy_fn() { echo fn-ok; }", "", "", 30)
            out = await run_bash_async("rxy_fn", "", "", 30)
        assert "fn-ok" in out

    async def test_shell_is_reused_not_recreated(self):
        await run_bash_async("echo first", "", "", 30)
        ids = ps.active_identities()
        assert ids, "a managed shell should exist after the first command"
        first_pid = next(iter(ps._SHELLS.values())).pid
        await run_bash_async("echo second", "", "", 30)
        second_pid = next(iter(ps._SHELLS.values())).pid
        assert first_pid == second_pid

    async def test_nothing_starts_before_first_command(self):
        assert ps.active_identities() == []


class TestCwd:
    async def test_cdw_within_shell_is_reported(self, tmp_path: Path):
        if IS_WINDOWS:
            cmd = f"Set-Location -LiteralPath '{tmp_path}'; Write-Output (Get-Location).Path"
        else:
            cmd = f"cd '{tmp_path}' && pwd"
        out = await run_bash_async(cmd, "", "", 30)
        assert str(tmp_path) in out

    async def test_workdir_is_single_shot_and_state_survives(self, tmp_path: Path):
        """workdir scopes ONLY the directory; variables must not be isolated."""
        if IS_WINDOWS:
            await run_bash_async("$rxy_wd = 'keep'", "", "", 30)
            inside = await run_bash_async(
                "Write-Output (Get-Location).Path", "", str(tmp_path), 30
            )
            after = await run_bash_async(
                "Write-Output (Get-Location).Path; Write-Output $rxy_wd", "", "", 30
            )
        else:
            await run_bash_async("rxy_wd=keep", "", "", 30)
            inside = await run_bash_async("pwd", "", str(tmp_path), 30)
            after = await run_bash_async("pwd; echo $rxy_wd", "", "", 30)

        assert str(tmp_path) in inside
        assert "keep" in after, "workdir must not isolate variables"
        assert str(tmp_path) not in after.splitlines()[0]

    async def test_cd_inside_command_does_not_leak_with_workdir(self, tmp_path: Path):
        if IS_WINDOWS:
            cmd = "Set-Location -LiteralPath 'C:\\'; Write-Output done"
        else:
            cmd = "cd /; echo done"
        await run_bash_async(cmd, "", str(tmp_path), 30)
        after = await run_bash_async("Write-Output (Get-Location).Path" if IS_WINDOWS else "pwd", "", "", 30)
        assert str(tmp_path) not in after


class TestIsolation:
    async def test_different_sessions_do_not_share_state(self):
        a = await ps.acquire_shell(identity="iso-a", cwd=os.getcwd())
        b = await ps.acquire_shell(identity="iso-b", cwd=os.getcwd())
        if IS_WINDOWS:
            await a.run("$iso = 'from-a'", timeout=30)
            out = await b.run('Write-Output "[$iso]"', timeout=30)
        else:
            await a.run("iso=from-a", timeout=30)
            out = await b.run('echo "[$iso]"', timeout=30)
        assert out.stdout.strip() == "[]"

    async def test_same_shell_serializes(self):
        shell = await ps.acquire_shell(identity="ser", cwd=os.getcwd())
        if IS_WINDOWS:
            slow = "Start-Sleep -Milliseconds 400; Write-Output slow"
        else:
            slow = "sleep 0.4; echo slow"
        t1 = shell.run(slow, timeout=30)
        t2 = shell.run("echo fast", timeout=30)
        r1, r2 = await asyncio.gather(t1, t2)
        assert "slow" in r1.stdout
        assert "fast" in r2.stdout


class TestCompletionProtocol:
    async def test_fake_marker_in_output_does_not_settle_early(self):
        """Output that LOOKS like a completion marker must not end the command."""
        if IS_WINDOWS:
            cmd = "Write-Output '__RXY_END_fake rc=0'; Write-Output 'still'; cmd /c exit 5"
        else:
            cmd = "printf '__RXY_END_fake rc=0\\n'; echo still; exit 5"
        out = await run_bash_async(cmd, "", "", 30)
        assert "still" in out
        assert "[exit code: 5]" in out

    async def test_nonzero_exit_is_reported(self):
        cmd = "cmd /c exit 7" if IS_WINDOWS else "exit 7"
        out = await run_bash_async(cmd, "", "", 30)
        assert "[exit code: 7]" in out

    async def test_success_text_with_failing_exit_stays_failing(self):
        if IS_WINDOWS:
            cmd = "Write-Output 'SUCCESS'; cmd /c exit 3"
        else:
            cmd = "echo SUCCESS; exit 3"
        out = await run_bash_async(cmd, "", "", 30)
        assert "SUCCESS" in out
        assert "[exit code: 3]" in out


class TestLifecycle:
    async def test_release_closes_process(self):
        shell = await ps.acquire_shell(identity="life", cwd=os.getcwd())
        await shell.ensure_started()
        pid = shell.pid
        assert pid
        assert await ps.release_shell("life") is True
        assert "life" not in ps.active_identities()
        assert not shell.alive

    async def test_dead_shell_is_replaced_honestly(self):
        shell = await ps.acquire_shell(identity="dead", cwd=os.getcwd())
        await shell.ensure_started()
        await shell.close()
        fresh = await ps.acquire_shell(identity="dead", cwd=os.getcwd())
        assert fresh is not shell
