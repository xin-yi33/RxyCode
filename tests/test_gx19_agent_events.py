"""GX19-B path A: consume E4 AgentEvent. No new protocol fields."""

from __future__ import annotations

from pathlib import Path

from protocol.notifications import AgentEvent


def test_e4_agent_event_methods_exist() -> None:
    methods = (
        "event/agent_started",
        "event/agent_tool",
        "event/agent_progress",
        "event/agent_done",
        "event/agent_paused",
        "event/agent_cancelled",
        "event/agent_budget_exceeded",
        "event/agent_denied",
    )
    for method in methods:
        kwargs: dict = {
            "method": method,
            "session_id": "s",
            "agent_id": "a1",
            "seq": 1,
        }
        if method == "event/agent_budget_exceeded":
            kwargs["tokens_used"] = 0
            kwargs["budget_used"] = 0
        event = AgentEvent(**kwargs)
        assert event.method == method
        assert event.seq == 1


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
