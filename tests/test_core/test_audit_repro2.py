"""Deeper repro for the two findings my first attempt missed."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def show(claim: str, reproduced: bool, detail: str = "") -> None:
    tag = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  [{tag}] {claim}" + (f" :: {detail}" if detail else ""))


async def test_invalid_workdir_posix_style(tmp_path: Path):
    """Check BOTH the target of the cd AND whether the command still runs.

    The wrapper emits a 126 trailer but falls through to the command text;
    only a shell that treats the failed block as fatal would stop it.
    """
    await ps.release_all()
    sh = await ps.acquire_shell(identity="badwd2", cwd=os.getcwd())
    marker = tmp_path / "ran2.txt"
    bad = tmp_path / "nope"
    try:
        if WINDOWS:
            # A multi-statement command: if cd fails but execution continues,
            # the marker is created in the ORIGINAL directory.
            cmd = (
                "if (-not (Test-Path -LiteralPath '"
                + str(bad)
                + "')) { Write-Output 'nogdir' }; "
                f"Set-Content -LiteralPath '{marker}' -Value ran"
            )
            r = await sh.run(cmd, timeout=30, workdir=str(bad))
        else:
            cmd = f"touch '{marker}'"
            r = await sh.run(cmd, timeout=30, workdir=str(bad))
        show(
            "command executes despite failed workdir",
            marker.exists(),
            f"rc={r.exit_code} marker={marker.exists()} out={r.stdout.strip()[:60]!r}",
        )
    finally:
        await ps.release_all()


async def test_cancel_child_tree_real(tmp_path: Path):
    """Start a real long-lived child, cancel the command, then check the child."""
    await ps.release_all()
    sh = await ps.acquire_shell(identity="cancel-tree2", cwd=os.getcwd())
    marker = tmp_path / "child_alive.txt"
    try:
        if WINDOWS:
            # PowerShell starts a real python child that survives the pipeline.
            script = tmp_path / "child.py"
            script.write_text(
                "import time, pathlib\n"
                "time.sleep(6)\n"
                f"pathlib.Path(r'{marker}').write_text('alive')\n",
                encoding="utf-8",
            )
            cmd = f"python '{script}'"
        else:
            script = tmp_path / "child.py"
            script.write_text(
                "import time, pathlib\n"
                "time.sleep(6)\n"
                f"pathlib.Path(r'{marker}').write_text('alive')\n",
                encoding="utf-8",
            )
            cmd = f"python '{script}'"
        task = asyncio.create_task(sh.run(cmd, timeout=60))
        await asyncio.sleep(1.2)  # let python actually start
        t0 = time.perf_counter()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, ps.ShellLostError):
            pass
        cancel_ms = (time.perf_counter() - t0) * 1000
        await sh.close()  # close the shell too
        await asyncio.sleep(7.0)  # beyond the child's 6s sleep
        show(
            "cancelled command leaves a real child process running",
            marker.exists(),
            f"cancel={cancel_ms:.0f}ms child_survived={marker.exists()}",
        )
    finally:
        await ps.release_all()


async def test_session_reset_keeps_shell_state():
    """clear_session_runtime must not leave a shell holding stale state."""
    import asyncio as _asyncio

    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        clear_session_runtime,
        reset_session_binding,
    )

    await ps.release_all()
    token = bind_session("reset-sess")
    try:
        # Acquire through the SESSION identity, exactly like the bash tool.
        identity = ps.state_identity()
        assert identity.startswith("reset-sess"), identity
        shell = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
        await shell.ensure_started()
        if WINDOWS:
            await shell.run("$reset_var = 'stale'", timeout=30)
        else:
            await shell.run("reset_var=stale", timeout=30)

        before = len(ps.active_identities())
        clear_session_runtime("reset-sess")
        # Teardown is scheduled on the loop; let it run.
        await _asyncio.sleep(0.5)
        after = len(ps.active_identities())

        show(
            "clear_session_runtime leaves the old shell (and its variables) alive",
            after != 0,
            f"shells_before={before} shells_after={after}",
        )
        assert after == 0, "session reset must drop the session's shells"
        assert not shell.alive
    finally:
        reset_session_binding(token)
        await ps.release_all()
