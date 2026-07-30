"""Tests for safety.permission_mode gating."""
from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.safety.approval import (
    ApprovalDecision,
    ApprovalRequest,
    set_approval_broker,
)
from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator


class _RecordingBroker:
    def __init__(self):
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision.APPROVED

    def is_level_always_allowed(self, level: RiskLevel) -> bool:
        return False


class _FakeTool:
    name = "write"

    def invoke(self, args):
        from pathlib import Path

        path = Path(args.get("filePath") or args.get("path") or "out.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(args.get("content", "")), encoding="utf-8")
        return f"wrote {path}"


class _FakeBash:
    name = "bash"

    def invoke(self, args):
        return "stdout"


@pytest.fixture(autouse=True)
def _clear_broker():
    set_approval_broker(None)
    yield
    set_approval_broker(None)


@pytest.mark.asyncio
async def test_auto_edit_skips_write_but_asks_bash(tmp_path, monkeypatch):
    broker = _RecordingBroker()
    set_approval_broker(broker)
    orch = ToolOrchestrator()
    orch.register("write", _FakeTool())
    orch.register("bash", _FakeBash())

    cfg = {
        "safety": {
            "enabled": True,
            "permission_mode": "auto_edit",
            "auto_approve": [],
            "allowed_write_paths": [str(tmp_path)],
        }
    }
    # write should auto
    out = await orch._execute_tool_gated(
        "write",
        {"filePath": str(tmp_path / "a.py"), "content": "print(1)\n"},
        cfg,
    )
    assert "wrote" in out
    assert broker.requests == []

    # bash still needs approval
    out2 = await orch._execute_tool_gated(
        "bash",
        {"command": "echo hi"},
        cfg,
    )
    assert out2 == "stdout"
    assert len(broker.requests) == 1
    assert broker.requests[0].tool_name == "bash"


@pytest.mark.asyncio
async def test_full_auto_skips_bash(tmp_path):
    broker = _RecordingBroker()
    set_approval_broker(broker)
    orch = ToolOrchestrator()
    orch.register("bash", _FakeBash())
    cfg = {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": [],
        }
    }
    out = await orch._execute_tool_gated("bash", {"command": "echo hi"}, cfg)
    assert out == "stdout"
    assert broker.requests == []


@pytest.mark.asyncio
async def test_confirm_all_asks_write(tmp_path):
    broker = _RecordingBroker()
    set_approval_broker(broker)
    orch = ToolOrchestrator()
    orch.register("write", _FakeTool())
    cfg = {
        "safety": {
            "enabled": True,
            "permission_mode": "confirm_all",
            "auto_approve": [],
            "allowed_write_paths": [str(tmp_path)],
        }
    }
    await orch._execute_tool_gated(
        "write",
        {"filePath": str(tmp_path / "b.py"), "content": "x\n"},
        cfg,
    )
    assert len(broker.requests) == 1
