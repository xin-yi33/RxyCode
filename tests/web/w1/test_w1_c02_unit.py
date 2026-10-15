"""WEB-W1-C02. One Session opens many runs; the server owns tenant identity."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-protocol" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

AUTH = {
    "tenant_id": "tenant-real",
    "actor_id": "actor-1",
    "project_id": "project-1",
    "session_id": "client-must-not-win",
    "target_id": "target-1",
    "permission_profile": "default",
    "deadline_at": "2026-10-16T00:00:00Z",
    "trace_id": "trace-1",
}


async def test_w1_c02_contract(tmp_path: Path):
    """Two runs on one Session get different run ids and do not rebuild it."""
    from core.session import Session
    from rxycode_protocol.run_context import RunContext

    class _Agent:
        def __init__(self) -> None:
            self.seen: list[object] = []

        async def run(self, text: str, mode: str = "build") -> str:
            del text, mode
            from appserver.runtime import current_run_context

            self.seen.append(current_run_context())
            return "ok"

        def cancel(self) -> bool:
            return True

    emitted: list[object] = []
    session = Session(session_id="ses-c02", workspace_root=tmp_path, emit=emitted.append)
    same = session
    first = session.open_run(AUTH)
    second = session.open_run(AUTH)
    assert isinstance(first, RunContext)
    assert isinstance(second, RunContext)
    assert first.run_id != second.run_id
    assert first.session_id == second.session_id == "ses-c02"
    assert session is same
    assert session.emit == emitted.append
    agent = _Agent()
    await session.prompt(agent, "turn", mode="build", run_id="legacy-run", run_context=second)
    await session.prompt(agent, "next", mode="build", run_id="run-b")
    assert session is same
    assert session._active_run is second
    assert agent.seen[0] is second
    assert agent.seen[1] is None
    run_ids = [getattr(item, "run_id", None) for item in emitted]
    assert second.run_id in run_ids
    assert "run-b" in run_ids
    assert "legacy-run" not in run_ids


def test_w1_c02_negative():
    """A forged tenant id and secret fields never enter the server context."""
    from rxycode_protocol.run_context import RunContext

    claimed = {
        "tenant_id": "forged-tenant",
        "api_key": "sk-live-secret",
        "device_token": "device-secret",
    }
    context = RunContext.from_authenticated(AUTH, claimed=claimed)
    blob = str(context.to_dict())
    assert context.tenant_id == "tenant-real"
    assert "forged-tenant" not in blob
    assert "sk-live-secret" not in blob
    assert "device-secret" not in blob
    with pytest.raises(ValueError):
        RunContext.from_authenticated({**AUTH, "api_key": "sk-live-secret"})
