"""The three permission tiers, locked to their product definition.

    confirm_all : read tools (read/grep/ls) free; ANY edit and ANY bash asks.
    auto_edit   : read tools free, file edits free, bash ALWAYS asks.
    full_auto   : nothing asks; only the hard command blacklist blocks.

The sharp edge: ``bash`` used to be gated by the *command's* semantic risk, so
"echo hi" / "ls" / "git status" classified READ and executed with no approval
at all -- breaking auto_edit's rule and putting a shell outside every gate.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.tools import StructuredTool

from RxyCode.RxyCode1_1_0.core.safety import approval as approval_mod
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

TOOLS = ("bash", "read", "grep", "ls", "webfetch", "edit", "write")

READ_CALLS = [
    ("read", {"filePath": "x.txt"}),
    ("grep", {"pattern": "x"}),
    ("ls", {"path": "."}),
]

EDIT_CALLS = [
    ("edit", {"filePath": "x.txt", "old_string": "a", "new_string": "b"}),
]

# Commands that classify READ by semantics -- the historical bypass.
SHELL_CALLS = [
    {"command": "echo hi", "description": "p", "workdir": "", "timeout": 30},
    {"command": "ls", "description": "p", "workdir": "", "timeout": 30},
    {"command": "git status", "description": "p", "workdir": "", "timeout": 30},
    {"command": 'python -c "print(1)"', "description": "p",
     "workdir": "", "timeout": 30},
]


@pytest.fixture(autouse=True)
def _no_broker():
    previous = approval_mod.get_approval_broker()
    approval_mod.set_approval_broker(None)
    try:
        yield
    finally:
        approval_mod.set_approval_broker(previous)


def _orch() -> ToolOrchestrator:
    """Orchestrator with stub tools.

    ``func=None`` + ``coroutine`` keeps the stub callable without a sync path,
    and args_schema is omitted so any kwargs are accepted (the real schemas
    would reject a partial edit payload).
    """
    async def _stub(**_kwargs):
        return "EXECUTED"

    orch = ToolOrchestrator()
    for name in TOOLS:
        orch.register(
            name,
            StructuredTool(
                name=name,
                description="stub",
                args_schema=None,
                coroutine=_stub,
            ),
        )
    return orch


def _config(mode: str, *, auto_approve: list[str] | None = None) -> dict:
    return {
        "safety": {
            "enabled": True,
            "permission_mode": mode,
            "auto_approve": auto_approve or [],
        }
    }


def _asks(mode: str, tool: str, args: dict, *, auto_approve=None) -> bool:
    """True when the call reached approval and was refused for lack of a broker."""
    out = str(
        asyncio.run(
            _orch().execute_tool(
                tool, args, config=_config(mode, auto_approve=auto_approve)
            )
        )
    )
    if "blocked" in out:
        return False  # blacklist: blocked before approval
    return "terminal for the current turn" in out


def _ran(mode: str, tool: str, args: dict, *, auto_approve=None) -> bool:
    """True when the gate let the call reach execution.

    A stub tool performs no real write, so post-execution evidence checks may
    complain afterwards.  What matters here is whether the APPROVAL stage let
    it through: anything other than the approval rejection counts as allowed.
    """
    out = str(
        asyncio.run(
            _orch().execute_tool(
                tool, args, config=_config(mode, auto_approve=auto_approve)
            )
        )
    )
    if "terminal for the current turn" in out:
        return False
    if "no approval broker" in out:
        return False
    if out.strip().startswith("[blocked"):
        return False
    return True


class TestConfirmAll:
    @pytest.mark.parametrize("tool,args", READ_CALLS)
    def test_read_tools_are_free(self, tool: str, args: dict) -> None:
        assert _ran("confirm_all", tool, args) is True

    @pytest.mark.parametrize("tool,args", EDIT_CALLS)
    def test_edits_ask(self, tool: str, args: dict) -> None:
        assert _asks("confirm_all", tool, args) is True
        assert _ran("confirm_all", tool, args) is False

    @pytest.mark.parametrize("args", SHELL_CALLS)
    def test_every_bash_asks(self, args: dict) -> None:
        assert _asks("confirm_all", "bash", args) is True
        assert _ran("confirm_all", "bash", args) is False, (
            "read-only-looking bash must not execute under confirm_all"
        )


class TestAutoEdit:
    @pytest.mark.parametrize("tool,args", READ_CALLS)
    def test_read_tools_are_free(self, tool: str, args: dict) -> None:
        assert _ran("auto_edit", tool, args) is True

    @pytest.mark.parametrize("tool,args", EDIT_CALLS)
    def test_edits_are_free(self, tool: str, args: dict) -> None:
        assert _ran("auto_edit", tool, args) is True

    @pytest.mark.parametrize("args", SHELL_CALLS)
    def test_every_bash_asks(self, args: dict) -> None:
        """The regression: read-only-looking shell must still ask."""
        assert _asks("auto_edit", "bash", args) is True
        assert _ran("auto_edit", "bash", args) is False


class TestFullAuto:
    @pytest.mark.parametrize(
        "tool,args", EDIT_CALLS + [("bash", SHELL_CALLS[0])]
    )
    def test_nothing_asks(self, tool: str, args: dict) -> None:
        assert _ran("full_auto", tool, args) is True

    def test_catastrophic_command_is_high_risk(self) -> None:
        """A destructive command must at least classify as high risk.

        NOTE: this tree has no hard shell blacklist (``hard_denied_shell_reason``
        is absent), so "blocked before approval" is NOT asserted here.  The
        guarantee available today is risk classification, and that full_auto
        executes only because it is allowed to -- recorded as a known gap.
        """
        from RxyCode.RxyCode1_1_0.core.governance import classify_tool_risk
        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        assert classify_tool_risk("bash", {"command": "rm -rf /"}) >= RiskLevel.WRITE


class TestAutoApproveLevels:
    def test_read_level_does_not_waive_shell(self) -> None:
        assert _asks(
            "confirm_all", "bash", SHELL_CALLS[0], auto_approve=["read"]
        ) is True

    def test_write_level_waives_shell(self) -> None:
        assert _asks(
            "confirm_all", "bash", SHELL_CALLS[0], auto_approve=["write"]
        ) is False
