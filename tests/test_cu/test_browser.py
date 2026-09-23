"""Browser tools: a11y snapshot over pixels; fewer steps than raw ocu."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from RxyCode.RxyCode1_1_0.core.cu.bind import bind_computer_use, unbind_computer_use
from RxyCode.RxyCode1_1_0.core.cu.browser import pick_browser_app
from RxyCode.RxyCode1_1_0.core.cu.spec import OCU_SERVER_NAME
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.mcp.client import MCPClient

from tests.test_cu.fake_ocu import FAKE_OCU


@pytest.fixture
def fake_ocu(tmp_path: Path) -> Path:
    script = tmp_path / "fake_ocu.py"
    script.write_text(FAKE_OCU, encoding="utf-8")
    return script


def test_pick_browser_app_from_list_apps():
    payload = json.dumps(
        {"apps": [{"name": "notepad"}, {"name": "msedge", "title": "GitHub"}]}
    )
    assert pick_browser_app(payload) == "msedge"


def test_browser_snapshot_and_act_verify_loop(fake_ocu, monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    client = MCPClient(OCU_SERVER_NAME, sys.executable, [str(fake_ocu)], timeout=5)
    assert client.connect() is True
    agent = SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={"computer_use": {"enabled": True, "approved": True, "browser": True}},
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )
    try:
        names = bind_computer_use(agent, client=client)
        assert "browser_snapshot" in names
        assert "browser_act" in names
        snap = agent._tool_orchestrator.get("browser_snapshot").invoke({})
        parsed = json.loads(snap)
        assert parsed["source"] == "accessibility"
        assert "screenshot" not in parsed
        acted = agent._tool_orchestrator.get("browser_act").invoke(
            {"action": "click", "element_index": "0"}
        )
        assert "verify" in acted
        assert "SHOULD_STRIP" not in acted
    finally:
        unbind_computer_use(agent)
        client.disconnect()
