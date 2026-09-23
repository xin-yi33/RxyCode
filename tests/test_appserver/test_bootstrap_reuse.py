"""Cold-start reuse: one bootstrap, long warm, no double-spawn on timeout."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from appserver import server as server_mod
from appserver.agent_host import AgentHost
from appserver.server import AppServer


def _bare_host() -> AgentHost:
    host = object.__new__(AgentHost)
    host._bootstrapped = False
    host._bootstrap_task = None
    host._bootstrap_lock = asyncio.Lock()
    host._stub = True
    host.workspace_root = Path(".")
    host.session_id = "s1"
    host.model_id = None
    return host


def test_warm_timeout_covers_real_agent_ctor():
    """Background warm used to abort at 30s while AgentV2+MCP still starting."""
    timeout = getattr(server_mod, "_DEFAULT_WARM_TIMEOUT_SECONDS", 0)
    assert timeout >= 180.0
    src = inspect.getsource(AppServer._warm_session_host)
    assert "timeout=30.0" not in src
    assert "_DEFAULT_WARM_TIMEOUT_SECONDS" in src


@pytest.mark.asyncio
async def test_ensure_bootstrapped_is_single_flight():
    host = _bare_host()
    calls: list[str] = []

    async def fake_pipe(method, params, *, timeout):
        calls.append(method)
        await asyncio.sleep(0.15)
        return {"ok": True}

    host._pipe_request = fake_pipe  # type: ignore[method-assign]

    first, second = await asyncio.gather(
        host.ensure_bootstrapped(timeout=2.0),
        host.ensure_bootstrapped(timeout=2.0),
    )
    assert first is None and second is None
    assert calls == ["bootstrap"]
    assert host.bootstrapped is True


@pytest.mark.asyncio
async def test_ensure_bootstrapped_timeout_does_not_start_second_rpc():
    host = _bare_host()
    calls: list[float] = []

    async def fake_pipe(method, params, *, timeout):
        calls.append(timeout)
        await asyncio.sleep(0.4)
        return {"ok": True}

    host._pipe_request = fake_pipe  # type: ignore[method-assign]

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await host.ensure_bootstrapped(timeout=0.05)
    await host.ensure_bootstrapped(timeout=2.0)
    assert len(calls) == 1
    assert host.bootstrapped is True


@pytest.mark.asyncio
async def test_prompt_skips_starting_worker_progress_when_already_warm(monkeypatch, tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path)
    progress: list[str] = []

    host = SimpleNamespace(
        bootstrapped=True,
        ensure_bootstrapped=AsyncMock(),
        run_prompt=AsyncMock(
            return_value={"status": "succeeded", "text": "hi", "run_id": "r1"}
        ),
        alive=lambda: True,
        interrupt=AsyncMock(),
    )
    monkeypatch.setattr(server, "_host_for_session", AsyncMock(return_value=host))
    monkeypatch.setattr(
        server,
        "_emit_model",
        AsyncMock(side_effect=lambda model: progress.append(getattr(model, "text", ""))),
    )
    monkeypatch.setattr(server, "_emit_job_state", AsyncMock())
    monkeypatch.setattr(server, "_respond", AsyncMock())
    monkeypatch.setattr(server, "_drain_emit_and_degrades", AsyncMock())
    monkeypatch.setattr(server, "_persist_notification", lambda _msg: None)
    monkeypatch.setattr(server, "_schedule_notification", lambda _msg: None)

    await server._run_prompt(
        session_id=record.session_id,
        text="你好",
        request_id=1,
        job_id="job1",
        timeout_seconds=5.0,
    )
    assert not any("Starting Agent worker" in text for text in progress)
    assert any("思考中" in text for text in progress)
