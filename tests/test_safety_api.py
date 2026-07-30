"""API-level integration tests for the safety gate (阶段二):
POST /approve endpoint and approval_request SSE events in /chat/stream.
"""
import json
import threading
import pytest
from unittest.mock import MagicMock, AsyncMock

from RxyCode.RxyCode1_1_0.core.safety.approval import SseApproval, set_approval_broker


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Test response")
    agent.model_config = {"model_name": "test-model", "api_key": "test-key"}
    agent._memory = MagicMock()
    agent._session_loaded = False
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._stream_mode = False
    return agent


@pytest.fixture
def client(mock_agent):
    from fastapi.testclient import TestClient
    from RxyCode.RxyCode1_1_0 import api_server

    original_state = dict(api_server._state)
    api_server._state["agent"] = mock_agent
    api_server._state["tui_proxy"] = api_server.APIProxyTUI()
    api_server._state["busy"] = False
    api_server._state["chat_history"] = []
    api_server._state["mode"] = "build"

    token = api_server.configure_api_token()
    with TestClient(
        api_server.app,
        client=("127.0.0.1", 50000),
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c

    api_server._state.clear()
    api_server._state.update(original_state)
    set_approval_broker(None)


class TestApproveEndpoint:
    def test_resolve_pending_approval(self, client):
        broker = SseApproval(timeout=30)
        set_approval_broker(broker)

        # Register a pending request directly
        import asyncio
        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalRequest
        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        req = ApprovalRequest(tool_name="bash", args_summary={"command": "ls"},
                              risk=RiskLevel.WRITE)
        event = asyncio.Event()
        broker._pending[req.approval_id] = event

        resp = client.post("/approve", json={
            "approval_id": req.approval_id, "decision": "approved"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert event.is_set()

    def test_unknown_id_returns_404(self, client):
        set_approval_broker(SseApproval(timeout=30))
        resp = client.post("/approve", json={
            "approval_id": "no-such-id", "decision": "approved"})
        assert resp.status_code == 404

    def test_no_broker_returns_409(self, client):
        set_approval_broker(None)
        resp = client.post("/approve", json={
            "approval_id": "x", "decision": "approved"})
        assert resp.status_code == 409


class TestStreamApprovalEvent:
    def test_stream_endpoint_installs_queue_sink(self, mock_agent):
        """The /chat/stream endpoint must route the broker's
        approval_request events into its SSE queue (deterministic: we
        capture the installed sink instead of consuming the stream)."""
        from fastapi.testclient import TestClient
        from RxyCode.RxyCode1_1_0 import api_server
        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalRequest
        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        original_state = dict(api_server._state)
        api_server._state["agent"] = mock_agent
        api_server._state["tui_proxy"] = api_server.APIProxyTUI()
        api_server._state["busy"] = False
        api_server._state["chat_history"] = []
        api_server._state["mode"] = "build"

        broker = SseApproval(timeout=30)

        async def run_quick(message, mode="build"):
            # Wait until the endpoint installs the sink, then emit one
            # approval_request through the broker and resolve it ourselves.
            req = ApprovalRequest(tool_name="write",
                                  args_summary={"filePath": "f.txt"},
                                  risk=RiskLevel.WRITE)
            import asyncio
            ev = asyncio.Event()
            broker._pending[req.approval_id] = ev
            if broker._sink:
                broker._sink(req.to_event())
            broker.resolve(req.approval_id, "approved")
            return "done"

        mock_agent.run = run_quick

        try:
            token = api_server.configure_api_token()
            with TestClient(
                api_server.app,
                client=("127.0.0.1", 50000),
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                # Lifespan startup installs its own broker; replace it only
                # after entering so both HTTP calls share this portal loop.
                set_approval_broker(broker)
                resp = client.post(
                    "/chat/stream", json={"message": "hi", "mode": "build"}
                )
                assert resp.status_code == 200
                body = resp.text
                assert "approval_request" in body, (
                    f"no approval_request in SSE body: {body[:400]}"
                )
                assert '"type": "final"' in body
                assert not api_server._chat_lock.locked()
        finally:
            api_server._state.clear()
            api_server._state.update(original_state)

    def test_approve_resolves_sse_broker_end_to_end(self, mock_agent):
        """Full round-trip: agent run awaits approval; POST /approve
        resolves the pending broker event so the run can complete.

        Deterministic: we assert on the broker's pending registry (the
        /approve contract) instead of consuming the SSE stream — the
        TestClient portal thread schedules the stream consumer too slowly
        for reliable body assertions."""
        from fastapi.testclient import TestClient
        from RxyCode.RxyCode1_1_0 import api_server
        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalRequest
        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        original_state = dict(api_server._state)
        api_server._state["agent"] = mock_agent
        api_server._state["tui_proxy"] = api_server.APIProxyTUI()
        api_server._state["busy"] = False
        api_server._state["chat_history"] = []
        api_server._state["mode"] = "build"

        broker = SseApproval(timeout=30)

        published: dict[str, str] = {}
        stream_result: dict[str, object] = {}
        got = threading.Event()

        async def run_with_approval(message, mode="build"):
            req = ApprovalRequest(tool_name="write",
                                  args_summary={"filePath": "f.txt"},
                                  risk=RiskLevel.WRITE)
            published["id"] = req.approval_id
            got.set()
            decision = await broker.request_approval(req)
            return f"decision={decision.value}"

        mock_agent.run = run_with_approval
        try:
            token = api_server.configure_api_token()
            with TestClient(
                api_server.app,
                client=("127.0.0.1", 50000),
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                set_approval_broker(broker)

                def do_stream():
                    try:
                        stream_result["response"] = client.post(
                            "/chat/stream",
                            json={"message": "hi", "mode": "build"},
                        )
                    except BaseException as exc:
                        stream_result["error"] = exc

                t = threading.Thread(target=do_stream, daemon=True)
                t.start()

                assert got.wait(timeout=30), "agent never reached approval request"
                approval_id = published["id"]
                assert approval_id in broker._pending, "request not pending in broker"

                resp = client.post("/approve", json={
                    "approval_id": approval_id, "decision": "approved"})
                assert resp.status_code == 200

                t.join(timeout=10)
                assert not t.is_alive(), "stream request thread did not terminate"
                assert "error" not in stream_result
                stream_response = stream_result["response"]
                assert stream_response.status_code == 200
                assert "decision=approved" in stream_response.text
                assert approval_id not in broker._pending
                assert approval_id not in broker._decisions
                assert broker._sink is None
                assert api_server._state["busy"] is False
                assert not api_server._chat_lock.locked()
        finally:
            api_server._state.clear()
            api_server._state.update(original_state)
