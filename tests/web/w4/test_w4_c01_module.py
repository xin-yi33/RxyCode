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


def test_w4_c01_integration(tmp_path: Path) -> None:
    """The same command is rejected under ask and runs under full."""
    from langchain_core.tools import StructuredTool

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

    asked: list[str] = []
    body: list[str] = []

    class Reject(ApprovalBroker):
        async def _ask(self, request: object) -> ApprovalDecision:
            asked.append(str(getattr(request, "tool_name", "")))
            return ApprovalDecision.REJECTED

    def sandbox_body(command: str = "", argv: list[str] | None = None, target: str = "local") -> str:
        del argv, target
        body.append(command)
        return "sandbox-body"

    marker = tmp_path / "ran.txt"
    argv = [sys.executable, "-c", f"open(r'{marker}', 'w', encoding='utf-8').write('ok')"]
    payload = {"argv": argv, "command": "print-only", "target": "local", "cwd": str(tmp_path)}
    set_approval_broker(Reject())
    port = ExecutionPort()
    token = bind_execution_port(port)
    try:
        orchestrator = ToolOrchestrator()
        orchestrator.register(
            "bash",
            StructuredTool.from_function(func=sandbox_body, name="bash", description="shell"),
        )
        refused = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                payload,
                config={"safety": {"enabled": True, "permission_mode": "ask"}},
            )
        )
        assert "rejected" in refused
        assert body == []
        assert not marker.exists()
        assert asked == ["bash"]
        ran = asyncio.run(
            orchestrator.execute_tool(
                "bash",
                payload,
                config={"safety": {"enabled": True, "permission_mode": "full"}},
            )
        )
        assert body == []
        assert marker.read_text(encoding="utf-8") == "ok"
        assert asked == ["bash"]
        assert "sandbox-body" not in ran
    finally:
        reset_execution_port(token)
        set_approval_broker(None)
