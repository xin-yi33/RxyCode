"""GX7-B: event/agent_usage from Phase 3 usage; never hardcode 8192."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from appserver.usage_tracker import HEARTBEAT_SECONDS, UsageTracker
from protocol.notifications import AgentUsage, TokenUsage


def test_event_is_agent_namespace_and_not_token_usage() -> None:
    assert AgentUsage.model_fields["method"].default == "event/agent_usage"
    assert TokenUsage.model_fields["method"].default == "event/token_usage"
    event = AgentUsage(session_id="s", seq=1, cost_available=False)
    assert event.cost is None
    assert HEARTBEAT_SECONDS == 30


def test_seq_and_phase3_tokens_without_invented_cost() -> None:
    tracker = UsageTracker(context_window_lookup=lambda _sid: 128000)
    first = tracker.ingest(
        "s1",
        {"input_tokens": 100, "output_tokens": 20, "reporting_status": "reported"},
    )
    assert first["seq"] == 1
    assert first["context_window"] == 128000
    assert first["context_used"] is None
    assert first["used_pct"] is None
    assert first["cost_available"] is False
    assert first["cost"] is None
    assert 8192 not in (first["context_window"], first["context_used"])
    second = tracker.on_tool("s1")
    assert second["seq"] == 2
    assert second["reason"] == "tool"
    beat = tracker.heartbeat("s1")
    assert beat["seq"] == 3
    assert beat["reason"] == "heartbeat"
    priced = tracker.ingest("s1", {}, cost=0.12, currency="USD")
    assert priced["cost_available"] is True
    assert priced["cost"] == 0.12


def test_occupancy_ignores_billing_and_survives_none_wipe() -> None:
    tracker = UsageTracker(context_window_lookup=lambda _sid: 1048576)
    billing = tracker.ingest(
        "s1",
        {
            "input_tokens": 3_703_115,
            "output_tokens": 16_935,
            "reporting_status": "reported",
        },
    )
    assert billing["context_used"] is None
    occupied = tracker.ingest("s1", {"context_used": 87965})
    assert occupied["context_used"] == 87965
    assert occupied["used_pct"] == pytest.approx(87965 * 100 / 1048576)
    final_like = tracker.ingest(
        "s1",
        {"input_tokens": 3_703_115, "output_tokens": 16_935, "context_used": None},
    )
    assert final_like["context_used"] == 87965
    assert final_like["input_tokens"] == 3_703_115


def test_unknown_window_is_none_not_8192() -> None:
    tracker = UsageTracker(context_window_lookup=lambda _sid: None)
    snap = tracker.ingest("s", {"input_tokens": 10, "output_tokens": 2})
    assert snap["context_window"] is None
    assert snap["used_pct"] is None


@pytest.mark.asyncio
async def test_appserver_emits_agent_usage_on_token_usage(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="gx7")
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/token_usage",
            "params": {
                "session_id": session.session_id,
                "input_tokens": 40,
                "output_tokens": 10,
                "reporting_status": "reported",
            },
        }
    )
    await server._drain_emit_writes()
    usage_events = [item for item in sent if item.get("method") == "event/agent_usage"]
    assert usage_events
    params = usage_events[-1]["params"]
    assert params["seq"] == 1
    assert params["input_tokens"] == 40
    assert params["cost_available"] is False
    assert params["context_used"] is None


@pytest.mark.asyncio
async def test_final_does_not_replace_occupancy_with_billing(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="occ")
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/token_usage",
            "params": {
                "session_id": session.session_id,
                "input_tokens": 3_703_115,
                "output_tokens": 16_935,
                "context_used": 87_965,
                "reporting_status": "reported",
            },
        }
    )
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/final",
            "params": {
                "session_id": session.session_id,
                "text": "ok",
                "input_tokens": 3_703_115,
                "output_tokens": 16_935,
                "reporting_status": "reported",
            },
        }
    )
    await server._drain_emit_writes()
    usage_events = [item for item in sent if item.get("method") == "event/agent_usage"]
    assert usage_events
    params = usage_events[-1]["params"]
    assert params["context_used"] == 87_965
    assert params["input_tokens"] == 3_703_115
    assert params["reason"] == "final"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
