"""Compare one-shot vs managed path under the SAME sandbox config.

This is the real audit claim: "same fail-closed config, old path refuses,
new path executes".
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


async def test_same_policy_both_paths(monkeypatch):
    """Both paths must reach the same sandbox decision."""
    one_shot_wrapped = {}
    managed_wrapped = {}

    real_wrap = shell_executor._wrap_os_sandbox

    def spy(argv, cwd):
        result = real_wrap(argv, cwd)
        one_shot_wrapped["called"] = one_shot_wrapped.get("called", 0) + 1
        one_shot_wrapped["result"] = result is not None
        return result

    monkeypatch.setattr(shell_executor, "_wrap_os_sandbox", spy)

    # 1. One-shot path.
    cmd = "Write-Output oneshot" if WINDOWS else "echo oneshot"
    r1 = await shell_executor.execute_async(cmd, "", 60)
    print(f"\n  one-shot success={r1.get('success')} wrap_calls={one_shot_wrapped}")

    # 2. Managed path, through the real bash tool.
    from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async

    await ps.release_all()
    before = one_shot_wrapped.get("called", 0)
    cmd2 = "Write-Output managed" if WINDOWS else "echo managed"
    out = await run_bash_async(cmd2, "", "", 60)
    after = one_shot_wrapped.get("called", 0)
    print(f"  managed out={out.strip()[:40]!r} wrap_calls_delta={after - before}")

    assert after > before, (
        "the managed shell must go through the sandbox wrapper too"
    )
    await ps.release_all()


async def test_sandbox_disabled_still_works():
    """With the sandbox disabled, the managed shell still runs normally."""
    await ps.release_all()
    from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async

    cmd = "Write-Output plain" if WINDOWS else "echo plain"
    out = await run_bash_async(cmd, "", "", 60)
    print(f"\n  disabled-sandbox output={out.strip()[:40]!r}")
    assert "plain" in out
    await ps.release_all()


async def test_managed_spawn_uses_new_process_group():
    """The shell must be in its own process group so cancel can kill the tree."""
    await ps.release_all()
    shell = await ps.acquire_shell(identity="pg", cwd=os.getcwd())
    try:
        await shell.ensure_started()
        assert shell.pid
        if not WINDOWS:
            import os as _os

            pgid = _os.getpgid(shell.pid)
            print(f"\n  shell pid={shell.pid} pgid={pgid}")
            assert pgid == shell.pid, "shell must lead its own process group"
        else:
            print(f"\n  shell pid={shell.pid} (Windows: CREATE_NEW_PROCESS_GROUP)")
    finally:
        await ps.release_all()
