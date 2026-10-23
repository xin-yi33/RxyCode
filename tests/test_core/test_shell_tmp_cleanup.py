"""Cancelled/killed commands must not leave protocol temp files behind."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def _rxy_tmp_files(root: Path) -> list[Path]:
    return sorted(root.glob(".rxy_*.tmp"))


async def test_cancel_sweeps_temp_files(tmp_path: Path):
    """A cancelled command's rc/err/cwd/out files must be removed."""
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )

    await ps.release_all()
    token = bind_session("tmp-sweep")
    try:
        # Files are created next to cwd, so run inside tmp_path.
        shell = await ps.acquire_shell(identity="sweep", cwd=str(tmp_path))
        await shell.ensure_started()
        # Warm up so the shell definitely lives in tmp_path.
        await shell.run(
            "Set-Location -LiteralPath '" + str(tmp_path) + "'"
            if WINDOWS
            else "cd '" + str(tmp_path) + "'",
            timeout=20,
        )
        before = _rxy_tmp_files(tmp_path)

        cmd = "Start-Sleep -Seconds 30" if WINDOWS else "sleep 30"
        task = asyncio.create_task(shell.run(cmd, timeout=60))
        await asyncio.sleep(0.8)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, ps.ShellLostError):
            pass

        after = _rxy_tmp_files(tmp_path)
        print(f"\n  before={len(before)} after={len(after)}")
        assert after == [], f"cancelled command leaked {after}"
    finally:
        reset_session_binding(token)
        await ps.release_all()


async def test_normal_command_leaves_nothing(tmp_path: Path):
    await ps.release_all()
    shell = await ps.acquire_shell(identity="clean", cwd=str(tmp_path))
    try:
        await shell.ensure_started()
        await shell.run(
            "Set-Location -LiteralPath '" + str(tmp_path) + "'"
            if WINDOWS
            else "cd '" + str(tmp_path) + "'",
            timeout=20,
        )
        cmd = "Write-Output ok" if WINDOWS else "echo ok"
        r = await shell.run(cmd, timeout=30)
        assert "ok" in r.stdout
        leftovers = _rxy_tmp_files(tmp_path)
        print(f"\n  leftovers after normal command: {leftovers}")
        assert leftovers == []
    finally:
        await ps.release_all()
