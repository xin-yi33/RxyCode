"""WEB-W1-C05. CLI, OpenTUI, Desktop, and Web share one core facade."""
from __future__ import annotations

from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.main import browser_entry_status, open_shared_core
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec


async def test_w1_c05_contract():
    """One task through every surface creates a single AgentRuntime."""
    from appserver.agent_worker import session_type_for_worker

    session = Session(session_id="ses-c05", workspace_root=".", emit=lambda _n: None)
    spec = AgentSpec(
        role="c05",
        display_name="c05",
        goal="share one runtime",
        prompt_stage="default",
        tools=[],
        mechanical=True,
    )
    class _Agent:
        async def run(self, text: str, mode: str = "build") -> str:
            del text, mode
            return "ok"

        def cancel(self) -> bool:
            return True

    core = open_shared_core(session, spec)
    agent = _Agent()
    runtimes = [
        await core.run(surface, "same-task", agent)
        for surface in ("cli", "opentui", "desktop", "web")
    ]
    assert core.creations == 1
    assert all(runtime is runtimes[0] for runtime in runtimes)
    assert type(runtimes[0]) is AgentRuntime
    assert session.agent_runtimes["c05"] is runtimes[0]
    assert session_type_for_worker() is Session


def test_w1_c05_negative():
    """A browser entry that imports Electron preload is rejected."""
    repo = Path(__file__).resolve().parents[3]
    adapter = repo / "frontend" / "protocol-client" / "src" / "webTransport.ts"
    assert browser_entry_status(adapter.read_text(encoding="utf-8")) == "OK"
    samples = [
        'import "electron";\n',
        'await import("electron");\n',
        'require ("electron");\n',
        'require("./preload.js");\n',
    ]
    for sample in samples:
        assert browser_entry_status(sample) == "BLOCKED"
