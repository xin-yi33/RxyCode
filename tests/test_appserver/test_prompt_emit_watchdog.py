"""Prompt-job liveness must survive child-session RPCs on the same worker.

Root cause of same-session second-turn ``job stalled >120s``: GUI/TUI
``child_sessions/list|events`` call ``AgentHost.run_subagent_rpc``, which
replaced ``host._emit``. Worker heartbeats then went through
``_emit_host_notification`` (no ``touch_job``). Collapsed thinking emits
no reasoning events, so the watchdog saw 120s of silence and killed the
worker. OpenCode/Claude do not treat silent thinking as a dead job.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock

import pytest

from appserver.agent_host import AgentHost
from appserver.agent_worker import AgentWorker
from appserver.server import AppServer
from appserver.watchdog import WatchdogState


def _host(tmp_path) -> AgentHost:
    import asyncio

    loop = asyncio.get_running_loop()
    return AgentHost(
        session_id="s1",
        workspace_root=tmp_path,
        stub=True,
        project_root=tmp_path,
        forward_server_request=AsyncMock(),
        main_loop=loop,
    )


@pytest.mark.asyncio
async def test_prompt_stalled_wording_admits_the_next_session(tmp_path, monkeypatch):
    """A stall without a client wall clock must not latch the whole appserver.

    ``_await_prompt_activity`` records ``prompt stalled after …``, which is
    the same isolated failure as ``prompt timed out``. The next session's
    prompt has to reach ``_run_prompt``.
    """
    monkeypatch.setattr("appserver.server.write_message", AsyncMock())
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path)
    server._watchdog.degrade("prompt stalled after 2.0s (session old)")
    seen: dict[str, str] = {}

    async def _run_prompt(**kwargs):
        seen["text"] = kwargs["text"]
        await server._respond(kwargs["request_id"], {"status": "succeeded", "text": "ok"})

    server._run_prompt = _run_prompt  # type: ignore[method-assign]
    await server._handle_prompt(
        {"session_id": record.session_id, "text": "hello while sibling is stalled"},
        7,
    )
    assert seen["text"] == "hello while sibling is stalled"
    assert server._watchdog.degraded is False


@pytest.mark.asyncio
async def test_subagent_rpc_does_not_replace_live_prompt_emit(tmp_path, monkeypatch):
    host = _host(tmp_path)
    prompt_emit = object()
    host._emit = prompt_emit
    monkeypatch.setattr(host, "_pipe_request", AsyncMock(return_value={"ok": True}))

    await host.run_subagent_rpc(
        "child_sessions/list",
        {"root_session_id": "s1"},
        timeout=5.0,
        emit=lambda _msg: None,
    )

    assert host._emit is prompt_emit


def test_host_notification_touches_active_job_for_session():
    server = AppServer(stub=True)
    server._watchdog = WatchdogState()
    server._watchdog.register_job("job-1", "s1", request_id=1)
    job = server._watchdog.jobs["job-1"]
    job.last_progress_at = time.monotonic() - 50.0

    server._emit_host_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/heartbeat",
            "params": {"session_id": "s1"},
        }
    )

    assert time.monotonic() - job.last_progress_at < 1.0
    assert server._watchdog.stalled_jobs() == []


@pytest.mark.asyncio
async def test_prompt_heartbeat_emits_user_visible_waiting_progress(monkeypatch):
    """A silent provider remains observable without treating heartbeat as text."""

    worker = object.__new__(AgentWorker)
    messages: list[dict] = []
    worker._schedule_write = messages.append
    monkeypatch.setenv("RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS", "0.25")

    heartbeat = asyncio.create_task(worker._prompt_heartbeat("s1"))
    try:
        await asyncio.sleep(0.3)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

    methods = [message["method"] for message in messages]
    assert "event/heartbeat" in methods
    assert not any(message["method"] == "event/progress" for message in messages)


def test_watchdog_stall_requires_missed_heartbeat_not_model_silence():
    server = AppServer(stub=True)
    server._watchdog = WatchdogState()
    server._watchdog.register_job("job-1", "s1", request_id=1)
    job = server._watchdog.jobs["job-1"]
    job.last_progress_at = time.monotonic() - 50.0
    assert server._watchdog.stalled_jobs() == []
    server._emit_host_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/heartbeat",
            "params": {"session_id": "s1"},
        }
    )
    assert server._watchdog.stalled_jobs() == []
    job.last_progress_at = time.monotonic() - 1000.0
    stalled = server._watchdog.stalled_jobs()
    assert [item.job_id for item in stalled] == ["job-1"]
