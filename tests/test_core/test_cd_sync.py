"""Reproduce: the dedicated `cd` tool and the managed shell disagree on cwd."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core.session_runtime import (
    bind_session,
    current_working_directory,
    reset_session_binding,
)

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def show(claim: str, reproduced: bool, detail: str = "") -> None:
    tag = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  [{tag}] {claim}" + (f" :: {detail}" if detail else ""))


async def test_cd_tool_then_bash():
    """cd tool -> subdir, then bash must run there, not in the old shell dir."""
    import tempfile

    from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async
    from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory

    await ps.release_all()
    token = bind_session("cd-sync")
    # Stay inside the execution workspace so the cd gate allows it.
    base = Path(os.getcwd())
    target = Path(tempfile.mkdtemp(dir=base, prefix="_cdsync_"))
    try:
        if WINDOWS:
            await run_bash_async("Write-Output warm", "", "", 30)
        else:
            await run_bash_async("echo warm", "", "", 30)

        res = change_directory(str(target))
        print(f"\n  cd result: {res}")
        if res.startswith("[error"):
            pytest.skip(f"cd tool refused this path: {res}")
        runtime_cwd = current_working_directory()

        if WINDOWS:
            out = await run_bash_async("Write-Output (Get-Location).Path", "", "", 30)
        else:
            out = await run_bash_async("pwd", "", "", 30)

        shell_says = out.strip()
        print(f"  runtime cwd={runtime_cwd}")
        print(f"  shell says ={shell_says}")
        show(
            "dedicated cd and the shell disagree (shell stayed in old dir)",
            str(target) not in shell_says,
            f"target={target} shell={shell_says}",
        )
        assert str(target) in shell_says, (
            "the shell must follow the dedicated cd tool"
        )
        assert str(current_working_directory()) == str(target), (
            "the shell must not have clobbered the runtime cwd"
        )
    finally:
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        change_directory(str(base))
        reset_session_binding(token)
        await ps.release_all()
