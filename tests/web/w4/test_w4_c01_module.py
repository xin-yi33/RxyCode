"""WEB-W4-C01. Ask mode still uses the approval broker. Full does not."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _rel in (
    Path("packages") / "rxycode-runner" / "src",
    Path("packages") / "rxycode-core" / "src",
):
    _src = REPO / _rel
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


def test_w4_c01_integration() -> None:
    """The same command is rejected under ask and runs under full."""
    from core.safety.approval import (
        ApprovalBroker,
        ApprovalDecision,
        set_approval_broker,
    )
    from execution.tool_orchestrator import ToolOrchestrator
    from rxycode_core.runtime.execution_port import (
        ExecutionPort,
        bind_execution_port,
        reset_execution_port,
    )
    from core.session_runtime import set_working_directory
    from tools.bash import bash_tool

    asked: list[str] = []
    work = REPO / "tests" / "web" / "w4" / "_run"
    nested = work / "sub"
    nested.mkdir(parents=True, exist_ok=True)
    set_working_directory(work, persist=False)

    class Reject(ApprovalBroker):
        async def _ask(self, request: object) -> ApprovalDecision:
            asked.append(str(getattr(request, "tool_name", "")))
            return ApprovalDecision.REJECTED

    marker = nested / "ran.txt"
    marker.unlink(missing_ok=True)
    command = f'''{sys.executable} -c "open('ran.txt', 'w', encoding='utf-8').write('ok')"'''
    payload = {
        "command": command,
        "target": "local",
        "workdir": "sub",
        "timeout": 30,
    }
    set_approval_broker(Reject())
    port = ExecutionPort()
    token = bind_execution_port(port)
    try:
        orchestrator = ToolOrchestrator()
        orchestrator.register("bash", bash_tool)
        refused = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                payload,
                config={"safety": {"enabled": True, "permission_mode": "confirm_all"}},
            )
        )
        assert "rejected" in refused
        assert not marker.exists()
        assert asked == ["bash"]
        ran = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                payload,
                config={"safety": {"enabled": True, "permission_mode": "full_auto"}},
            )
        )
        assert marker.read_text(encoding="utf-8") == "ok"
        assert asked == ["bash"]
        assert "sandbox-body" not in ran
    finally:
        reset_execution_port(token)
        set_approval_broker(None)
