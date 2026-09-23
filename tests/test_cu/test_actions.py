"""PP41 actions + first-run approval. cli_list/cli_run stay separate."""

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


def _agent(*, approved: bool) -> SimpleNamespace:
    return SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={"computer_use": {"enabled": True, "approved": approved, "browser": True}},
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )


def test_unapproved_actions_fail_closed(fake_ocu, monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    client = MCPClient(OCU_SERVER_NAME, sys.executable, [str(fake_ocu)], timeout=5)
    assert client.connect() is True
    agent = _agent(approved=False)
    try:
        bind_computer_use(agent, client=client)
        listed = agent._tool_orchestrator.get("list_apps").invoke({})
        assert json.loads(listed)["source"] == "accessibility"
        clicked = agent._tool_orchestrator.get("click").invoke(
            {"app": "msedge", "element_index": "0"}
        )
        assert "first-run approval" in clicked
    finally:
        unbind_computer_use(agent)
        client.disconnect()


def test_approved_click_executes_and_is_not_cli_run(fake_ocu, monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    client = MCPClient(OCU_SERVER_NAME, sys.executable, [str(fake_ocu)], timeout=5)
    assert client.connect() is True
    agent = _agent(approved=True)
    try:
        names = bind_computer_use(agent, client=client)
        assert "click" in names
        assert "cli_list" not in names
        assert "cli_run" not in names
        assert agent._tool_orchestrator.get("cli_run") is None
        clicked = agent._tool_orchestrator.get("click").invoke(
            {"app": "msedge", "element_index": "0"}
        )
        payload = json.loads(clicked)
        assert payload["ok"] is True
        assert payload["source"] == "accessibility"
    finally:
        unbind_computer_use(agent)
        client.disconnect()
