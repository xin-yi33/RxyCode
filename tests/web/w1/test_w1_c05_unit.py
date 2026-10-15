"""WEB-W1-C05. CLI, OpenTUI, Desktop, and Web share one core facade."""
from __future__ import annotations

from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.main import browser_entry_status, core_for_surface


def test_w1_c05_contract():
    """Every surface initializes the same AgentRuntime and Session classes."""
    from appserver.agent_worker import session_type_for_worker

    facades = [
        core_for_surface(name)
        for name in ("cli", "opentui", "desktop", "web")
    ]
    assert {id(item["agent_runtime"]) for item in facades} == {id(AgentRuntime)}
    assert {id(item["session"]) for item in facades} == {id(Session)}
    assert session_type_for_worker() is Session
    assert session_type_for_worker() is facades[0]["session"]


def test_w1_c05_negative(tmp_path: Path):
    """A browser entry that imports Electron preload is rejected."""
    repo = Path(__file__).resolve().parents[3]
    adapter = repo / "frontend" / "protocol-client" / "src" / "webTransport.ts"
    assert browser_entry_status(adapter.read_text(encoding="utf-8")) == "OK"
    blocked = tmp_path / "bad-entry.ts"
    blocked.write_text('import preload from "electron";\n', encoding="utf-8")
    assert browser_entry_status(blocked.read_text(encoding="utf-8")) == "BLOCKED"
