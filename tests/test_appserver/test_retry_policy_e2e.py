"""E2E: Card D retry policy — short transport retry vs stall recycle."""

from __future__ import annotations

import json

import httpx
import pytest

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
from tests.test_appserver.test_stdio_integration import (
    PROJECT_ROOT,
    AppserverClient,
    _appserver_env,
    _appserver_proc_with_env,
)


def test_e2e_protocol_tui_emits_retry_then_resolved_for_connect(monkeypatch):
    import asyncio

    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_v2_module

    class FlakyLlm:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("gateway reset")
            return {"content": "recovered"}

    emitted = []
    tui = ProtocolTui("retry-e2e", emitted.append, run_id="retry-run")
    monkeypatch.setattr(agent_v2_module, "get_tui", lambda: tui)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_v2_module.asyncio, "sleep", no_sleep)

    llm = agent_v2_module.UsageTrackingLLM(FlakyLlm())
    llm._transport_retries = 1
    result = asyncio.run(llm._call_with_transport_retry(["prompt"], {}))

    assert result == {"content": "recovered"}
    assert [item.method for item in emitted] == [
        "event/recovery_started",
        "event/recovery_attempt",
        "event/recovery_resolved",
    ]


def test_e2e_appserver_stall_is_worker_recycle_not_llm_retry():
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0.5"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        result = client.request(
            "session/prompt",
            {"session_id": session["session_id"], "text": "silent:3"},
            timeout=10.0,
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:silent-complete"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)
