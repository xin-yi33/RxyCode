"""Verify the REAL agent tool dispatch routes bash to the managed shell.

This is a wiring test at the ToolOrchestrator level (the path the agent
actually uses), not a direct call to the tool function.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core.safety import approval as approval_mod
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools.registry import default_registry


def _config() -> dict:
    # full_auto = no approval prompts, which is what an unattended run uses.
    return {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": ["write", "danger"],
        },
        "execution": {"sandbox_mode": "workspace"},
    }


@pytest.fixture(autouse=True)
def _broker():
    previous = approval_mod.get_approval_broker()
    approval_mod.set_approval_broker(None)
    yield
    approval_mod.set_approval_broker(previous)


@pytest.fixture(autouse=True)
async def _clean():
    """Isolate managed-shell state between tests.

    The shell registry is process-global and lives in memory, so a leftover
    shell from another test would make "did dispatch create a shell?" lie.
    """
    try:
        await ps.release_all()
    except RuntimeError:
        # A different event loop owns a prior shell; drop the registry only.
        ps._SHELLS.clear()
    yield
    try:
        await ps.release_all()
    except RuntimeError:
        ps._SHELLS.clear()


pytestmark = pytest.mark.asyncio


def _orch() -> ToolOrchestrator:
    orch = ToolOrchestrator(tool_registry=default_registry)
    # Register the real bash tool so the real dispatch path runs.
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    orch.register("bash", bash_tool)
    return orch


class TestOrchestratorRoutesToManagedShell:
    async def test_orchestrator_bash_creates_managed_shell(self):
        orch = _orch()
        out = await orch.execute_tool(
            "bash",
            {"command": "Write-Output wired", "description": "t",
             "workdir": "", "timeout": 60},
            config=_config(),
        )
        assert "wired" in str(out)
        # Behavioural proof that the managed path ran: the one-shot path can
        # never keep a variable, so this is stronger than inspecting a
        # process-global registry that other tests may have touched.
        await orch.execute_tool(
            "bash",
            {"command": "$wired_marker = 'kept'", "description": "t",
             "workdir": "", "timeout": 60},
            config=_config(),
        )
        echo = await orch.execute_tool(
            "bash",
            {"command": "Write-Output $wired_marker", "description": "t",
             "workdir": "", "timeout": 60},
            config=_config(),
        )
        assert "kept" in str(echo)

    async def test_state_survives_across_orchestrator_calls(self):
        orch = _orch()
        cfg = _config()
        await orch.execute_tool(
            "bash",
            {"command": "$wired_state = 'persisted'", "description": "t",
             "workdir": "", "timeout": 60},
            config=cfg,
        )
        out = await orch.execute_tool(
            "bash",
            {"command": "Write-Output $wired_state", "description": "t",
             "workdir": "", "timeout": 60},
            config=cfg,
        )
        assert "persisted" in str(out)

    async def test_docker_mode_uses_one_shot_path(self, monkeypatch):
        """Docker sandbox must NOT get a long-lived host shell."""
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        # Force the eligibility check to see docker.
        monkeypatch.setattr(
            bash_mod,
            "load_config",
            lambda: {"execution": {"sandbox_mode": "docker"}},
        )
        assert bash_mod._managed_shell_eligible("echo hi") is False

    async def test_env_opt_out_disables_managed(self, monkeypatch):
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        monkeypatch.setenv("RXYCODE_MANAGED_SHELL", "0")
        assert bash_mod._managed_shell_eligible("echo hi") is False

    async def test_internal_argv_path_is_still_one_shot(self):
        """Git/formatter style callers keep execute_argv_async."""
        from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor

        ex = ShellExecutor()
        argv = ["cmd", "/c", "echo", "internal"] if os.name == "nt" else ["echo", "internal"]
        result = await ex.execute_argv_async(argv, "", 30)
        assert result.get("success") is True
        assert "internal" in str(result.get("stdout", ""))
        assert ps.active_identities() == [], (
            "internal argv execution must not create a managed shell"
        )
