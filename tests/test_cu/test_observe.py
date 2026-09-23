"""PP40 observe path: accessibility facts, not model guesses."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _connect(script: Path) -> MCPClient:
    client = MCPClient(OCU_SERVER_NAME, sys.executable, [str(script)], timeout=5)
    assert client.connect() is True
    return client


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={"computer_use": {"enabled": True, "approved": True, "browser": True}},
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )


def test_observe_payload_has_accessibility_source(fake_ocu, monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    client = _connect(fake_ocu)
    agent = _agent()
    try:
        bind_computer_use(agent, client=client)
        listed = agent._tool_orchestrator.get("list_apps").invoke({})
        data = json.loads(listed)
        assert data["source"] == "accessibility"
        assert data["apps"][0]["name"] == "msedge"
        state = agent._tool_orchestrator.get("get_app_state").invoke({"app": "msedge"})
        parsed = json.loads(state)
        assert parsed["source"] == "accessibility"
        assert "screenshot" not in parsed
        assert parsed["tree"][0]["role"] == "button"
    finally:
        unbind_computer_use(agent)
        client.disconnect()
