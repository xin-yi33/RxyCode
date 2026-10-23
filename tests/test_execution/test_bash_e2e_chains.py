"""End-to-end: the REAL bash tool through the REAL orchestrator gate.

Covers acceptance A/B/D at the dispatch layer the agent actually uses:
state persistence, cwd, cancel, and that the gate still runs per call.
"""

from __future__ import annotations

import asyncio
import os
import sys
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


def _config(permission: str = "full_auto") -> dict:
    return {
        "safety": {
            "enabled": True,
            "permission_mode": permission,
            "auto_approve": ["write", "danger"],
        },
        "execution": {"sandbox_mode": "workspace"},
    }


def _orch():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    orch = ToolOrchestrator()
    orch.register("bash", bash_tool)
    return orch


@pytest.fixture(autouse=True)
async def _clean():
    await ps.release_all()
    yield
    await ps.release_all()


async def test_state_across_three_tool_calls():
    """Three separate tool invocations (three agent turns) share state."""
    token = bind_session("e2e-state")
    try:
        orch = _orch()
        cfg = _config()
        if WINDOWS:
            await orch.execute_tool("bash", {"command": "$e2e = 'kept'",
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            await orch.execute_tool("bash", {"command": "$e2e = $e2e + '-more'",
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            out = await orch.execute_tool("bash", {"command": "Write-Output $e2e",
                                                   "description": "t", "workdir": "",
                                                   "timeout": 60}, config=cfg)
        else:
            await orch.execute_tool("bash", {"command": "e2e=kept",
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            await orch.execute_tool("bash", {"command": 'e2e="$e2e-more"',
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            out = await orch.execute_tool("bash", {"command": "echo $e2e",
                                                   "description": "t", "workdir": "",
                                                   "timeout": 60}, config=cfg)
        print(f"\n  three-call state: {str(out).strip()[:60]!r}")
        assert "kept-more" in str(out)
    finally:
        reset_session_binding(token)


async def test_cd_then_bash_then_prompt_cwd_agree():
    """The dedicated cd tool, an in-shell cd, and the runtime all agree."""
    import tempfile

    from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory

    token = bind_session("e2e-cwd")
    base = Path(os.getcwd())
    sub = Path(tempfile.mkdtemp(dir=base, prefix="_e2ecwd_"))
    try:
        orch = _orch()
        cfg = _config()

        res = change_directory(str(sub))
        if res.startswith("[error"):
            pytest.skip(f"cd refused: {res}")
        assert str(current_working_directory()) == str(sub)

        # bash must run in the cd'd directory.
        out = await orch.execute_tool(
            "bash",
            {"command": "Write-Output (Get-Location).Path" if WINDOWS else "pwd",
             "description": "t", "workdir": "", "timeout": 60},
            config=cfg,
        )
        print(f"\n  after cd tool: shell={str(out).strip()[:70]}")
        assert str(sub) in str(out)

        # An in-shell cd must be reflected back into the runtime.
        if WINDOWS:
            await orch.execute_tool(
                "bash",
                {"command": f"Set-Location -LiteralPath '{base}'",
                 "description": "t", "workdir": "", "timeout": 60},
                config=cfg,
            )
        else:
            await orch.execute_tool(
                "bash",
                {"command": f"cd '{base}'", "description": "t",
                 "workdir": "", "timeout": 60},
                config=cfg,
            )
        print(f"  runtime after in-shell cd: {current_working_directory()}")
        assert str(current_working_directory()) == str(base)
    finally:
        import shutil

        shutil.rmtree(sub, ignore_errors=True)
        reset_session_binding(token)


async def test_workdir_is_single_shot_through_tool():
    import tempfile

    token = bind_session("e2e-workdir")
    base = Path(os.getcwd())
    sub = Path(tempfile.mkdtemp(dir=base, prefix="_e2ewd_"))
    try:
        orch = _orch()
        cfg = _config()
        if WINDOWS:
            await orch.execute_tool("bash", {"command": "$w = 'stay'",
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            inside = await orch.execute_tool(
                "bash",
                {"command": "Write-Output (Get-Location).Path", "description": "t",
                 "workdir": str(sub), "timeout": 60},
                config=cfg,
            )
            after = await orch.execute_tool(
                "bash",
                {"command": "Write-Output (Get-Location).Path; Write-Output $w",
                 "description": "t", "workdir": "", "timeout": 60},
                config=cfg,
            )
        else:
            await orch.execute_tool("bash", {"command": "w=stay", "description": "t",
                                             "workdir": "", "timeout": 60}, config=cfg)
            inside = await orch.execute_tool(
                "bash",
                {"command": "pwd", "description": "t", "workdir": str(sub),
                 "timeout": 60},
                config=cfg,
            )
            after = await orch.execute_tool(
                "bash",
                {"command": "pwd; echo $w", "description": "t", "workdir": "",
                 "timeout": 60},
                config=cfg,
            )
        print(f"\n  inside={str(inside).strip()[:70]}")
        print(f"  after={str(after).strip()[:70]}")
        assert str(sub) in str(inside)
        assert "stay" in str(after)
    finally:
        import shutil

        shutil.rmtree(sub, ignore_errors=True)
        reset_session_binding(token)


async def test_cancel_through_tool_kills_tree():
    token = bind_session("e2e-cancel")
    try:
        orch = _orch()
        cfg = _config()
        cmd = "Start-Sleep -Seconds 30" if WINDOWS else "sleep 30"
        task = asyncio.create_task(
            orch.execute_tool("bash", {"command": cmd, "description": "t",
                                       "workdir": "", "timeout": 60}, config=cfg)
        )
        await asyncio.sleep(1.0)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.sleep(0.5)
        print(f"\n  shells after cancel: {ps.active_identities()}")
        assert ps.started_identities() == [], "cancel must stop the shell"
    finally:
        reset_session_binding(token)


async def test_permission_still_gates_each_call():
    """The shell reuses the environment, never a prior authorization."""
    token = bind_session("e2e-perm")
    try:
        from RxyCode.RxyCode1_1_0.core.safety import approval as approval_mod

        previous = approval_mod.get_approval_broker()
        approval_mod.set_approval_broker(None)
        try:
            orch = _orch()
            # confirm_all without a broker: bash must be refused every time,
            # even though a shell may already exist from an earlier call.
            cfg = _config("full_auto")
            await orch.execute_tool("bash", {"command": "Write-Output warm",
                                             "description": "t", "workdir": "",
                                             "timeout": 60}, config=cfg)
            strict = {
                "safety": {"enabled": True, "permission_mode": "confirm_all",
                           "auto_approve": []},
                "execution": {"sandbox_mode": "workspace"},
            }
            out = await orch.execute_tool(
                "bash",
                {"command": "Write-Output should-not-run", "description": "t",
                 "workdir": "", "timeout": 60},
                config=strict,
            )
            print(f"\n  strict result: {str(out).strip()[:100]!r}")
            assert "should-not-run" not in str(out), (
                "a warm shell must not waive this call's approval"
            )
        finally:
            approval_mod.set_approval_broker(previous)
    finally:
        reset_session_binding(token)
