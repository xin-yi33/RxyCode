"""MCP kill-tree: Computer Use child dies with unbind/session close."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.cu.bind import bind_computer_use, unbind_computer_use
from RxyCode.RxyCode1_1_0.core.cu.spec import OCU_SERVER_NAME
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.mcp.client import MCPClient

from tests.test_cu.fake_ocu import FAKE_OCU


@pytest.fixture
def fake_ocu(tmp_path: Path) -> Path:
    script = tmp_path / "fake_ocu.py"
    script.write_text(FAKE_OCU, encoding="utf-8")
    return script


def test_unbind_kills_ocu_process_tree(fake_ocu, monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    client = MCPClient(OCU_SERVER_NAME, sys.executable, [str(fake_ocu)], timeout=5)
    assert client.connect() is True
    process = client._process
    assert process is not None and process.poll() is None
    from types import SimpleNamespace

    agent = SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={"computer_use": {"enabled": True, "approved": True, "browser": False}},
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )
    bind_computer_use(agent, client=client)
    assert agent._tool_orchestrator.get("list_apps") is not None
    unbind_computer_use(agent)
    deadline = time.time() + 3.0
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None
    assert agent._cu_client is None
    assert agent._tool_orchestrator.get("list_apps") is None
