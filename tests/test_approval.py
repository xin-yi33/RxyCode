"""Tests for core/safety/approval.py — ApprovalBroker implementations
(TUI / SSE), timeout rejection and session-level always-allow cache.

Adapted from OpenHands (MIT) openhands/security/ confirmation-mode design.
"""
import asyncio
import pytest

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.core.safety.approval import (
    ApprovalRequest,
    ApprovalDecision,
    ApprovalBroker,
    TuiApproval,
    SseApproval,
    get_approval_broker,
    set_approval_broker,
)


def _req(tool="bash", risk=RiskLevel.WRITE, args=None):
    return ApprovalRequest(
        tool_name=tool,
        args_summary=args or {"command": "echo hi"},
        risk=risk,
    )


class TestApprovalRequest:
    def test_has_unique_id(self):
        r1, r2 = _req(), _req()
        assert r1.approval_id
        assert r1.approval_id != r2.approval_id

    def test_args_summary_truncated(self):
        long_args = {"command": "x" * 1000}
        r = ApprovalRequest(tool_name="bash", args_summary=long_args, risk=RiskLevel.WRITE)
        s = str(r.args_summary)
        assert len(s) <= 220  # truncated to ~200 + ellipsis margin


class TestTuiApproval:
    @pytest.mark.asyncio
    async def test_approve_via_tui(self, monkeypatch):
        answers = iter(["y"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        broker = TuiApproval()
        decision = await broker.request_approval(_req())
        assert decision == ApprovalDecision.APPROVED

    @pytest.mark.asyncio
    async def test_reject_via_tui(self, monkeypatch):
        answers = iter(["n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        broker = TuiApproval()
        decision = await broker.request_approval(_req())
        assert decision == ApprovalDecision.REJECTED

    @pytest.mark.asyncio
    async def test_always_allow_level_cached(self, monkeypatch):
        answers = iter(["a"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        broker = TuiApproval()
        d1 = await broker.request_approval(_req(risk=RiskLevel.WRITE))
        assert d1 == ApprovalDecision.ALWAYS_ALLOW_LEVEL
        # Second call at same level must NOT prompt again
        d2 = await broker.request_approval(_req(risk=RiskLevel.WRITE))
        assert d2 == ApprovalDecision.ALWAYS_ALLOW_LEVEL

    @pytest.mark.asyncio
    async def test_eof_defaults_rejected(self, monkeypatch):
        def _raise(prompt=""):
            raise EOFError
        monkeypatch.setattr("builtins.input", _raise)
        broker = TuiApproval()
        decision = await broker.request_approval(_req())
        assert decision == ApprovalDecision.REJECTED

    @pytest.mark.asyncio
    async def test_does_not_block_event_loop(self, monkeypatch):
        """input() must run in a thread so the event loop keeps spinning."""
        answers = iter(["y"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        broker = TuiApproval()
        ticked = []

        async def ticker():
            for _ in range(3):
                await asyncio.sleep(0.01)
                ticked.append(1)

        await asyncio.gather(broker.request_approval(_req()), ticker())
        assert ticked  # event loop was not blocked


class TestSseApproval:
    @pytest.mark.asyncio
    async def test_event_registered_and_resolved(self):
        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)

        async def respond():
            await asyncio.sleep(0.05)
            assert len(events) == 1
            ev = events[0]
            assert ev["type"] == "approval_request"
            broker.resolve(ev["approval_id"], "approved")

        decision, _ = await asyncio.gather(
            broker.request_approval(_req()), respond()
        )
        assert decision == ApprovalDecision.APPROVED

    @pytest.mark.asyncio
    async def test_timeout_defaults_rejected(self):
        broker = SseApproval(timeout=0.1)
        broker.set_event_sink(lambda ev: None)
        decision = await broker.request_approval(_req())
        assert decision == ApprovalDecision.REJECTED
        assert broker._pending == {}
        assert broker._pending_loops == {}
        assert broker._decisions == {}

    @pytest.mark.asyncio
    async def test_cancellation_cleans_pending_request(self):
        broker = SseApproval(timeout=30)
        published = asyncio.Event()
        broker.set_event_sink(lambda _event: published.set())

        task = asyncio.create_task(broker.request_approval(_req()))
        await published.wait()
        assert broker._pending
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert broker._pending == {}
        assert broker._pending_loops == {}
        assert broker._decisions == {}

    @pytest.mark.asyncio
    async def test_request_and_resolution_use_owner_loop(self):
        broker = SseApproval(timeout=5)
        owner_loop = asyncio.get_running_loop()
        published = asyncio.Event()
        event_holder = {}

        def sink(event):
            assert asyncio.get_running_loop() is owner_loop
            event_holder.update(event)
            published.set()

        broker.set_event_sink(sink)
        task = asyncio.create_task(broker.request_approval(_req()))
        await published.wait()
        approval_id = event_holder["approval_id"]
        assert broker._pending_loops[approval_id] is owner_loop
        assert broker.resolve(approval_id, "approved") is True
        assert await task == ApprovalDecision.APPROVED
        assert broker._pending == {}
        assert broker._pending_loops == {}
        assert broker._decisions == {}

    @pytest.mark.asyncio
    async def test_reject_decision(self):
        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)

        async def respond():
            await asyncio.sleep(0.02)
            broker.resolve(events[0]["approval_id"], "rejected")

        decision, _ = await asyncio.gather(
            broker.request_approval(_req()), respond()
        )
        assert decision == ApprovalDecision.REJECTED

    @pytest.mark.asyncio
    async def test_always_allow_cached(self):
        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)

        async def respond():
            await asyncio.sleep(0.02)
            broker.resolve(events[0]["approval_id"], "always_allow_level")

        decision, _ = await asyncio.gather(
            broker.request_approval(_req(risk=RiskLevel.WRITE)), respond()
        )
        assert decision == ApprovalDecision.ALWAYS_ALLOW_LEVEL
        # cached: no new event emitted
        d2 = await broker.request_approval(_req(risk=RiskLevel.WRITE))
        assert d2 == ApprovalDecision.ALWAYS_ALLOW_LEVEL
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_resolve_unknown_id_returns_false(self):
        broker = SseApproval(timeout=5)
        assert broker.resolve("no-such-id", "approved") is False


class TestBrokerSingleton:
    def test_set_and_get(self):
        b = SseApproval(timeout=1)
        set_approval_broker(b)
        assert get_approval_broker() is b
        set_approval_broker(None)
