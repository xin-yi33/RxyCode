"""Regression tests for task-scoped model selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from appserver.agent_worker import AgentWorker
from appserver.server import AppServer, _DEFAULT_WARM_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_worker_switches_model_only_when_idle(monkeypatch):
    worker = AgentWorker()
    calls: list[str] = []

    class Agent:
        def switch_model(self, model_id: str) -> dict[str, str]:
            calls.append(model_id)
            return {"model_id": model_id, "provider_id": "deepseek"}

    worker._agent = Agent()
    responses = []
    async def capture(payload):
        responses.append(payload)

    monkeypatch.setattr(worker, "_write_ordered", capture)

    await worker._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "model/switch",
            "params": {"model_id": "deepseek/deepseek-v4"},
        }
    )

    assert calls == ["deepseek/deepseek-v4"]
    assert responses[-1]["result"] == {
        "ok": True,
        "model_id": "deepseek/deepseek-v4",
        "provider_id": "deepseek",
    }


@pytest.mark.asyncio
async def test_worker_rejects_model_switch_during_prompt(monkeypatch):
    worker = AgentWorker()
    worker._agent = SimpleNamespace(switch_model=lambda _model_id: pytest.fail("must not switch"))
    worker._run_task = SimpleNamespace(done=lambda: False)
    responses = []
    async def capture(payload):
        responses.append(payload)

    monkeypatch.setattr(worker, "_write_ordered", capture)

    await worker._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "model/switch",
            "params": {"model_id": "glm/glm-5"},
        }
    )

    assert responses[-1]["error"]["code"] == -32001
    assert "active run" in responses[-1]["error"]["message"]


@pytest.mark.asyncio
async def test_server_session_set_model_updates_task_record(monkeypatch, tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path)
    host = SimpleNamespace(
        alive=lambda: True,
        bootstrapped=True,
        ensure_bootstrapped=AsyncMock(),
        set_model=AsyncMock(side_effect=lambda model_id, timeout=30.0: {
            "ok": True,
            "model_id": model_id,
            "provider_id": "glm",
        }),
    )
    server._session_hosts[record.session_id] = host
    monkeypatch.setattr(server, "_host_for_session", AsyncMock(return_value=host))
    responses = []
    monkeypatch.setattr(
        server, "_respond", AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload))
    )

    await server._handle_session_set_model(
        {"session_id": record.session_id, "model_id": "glm/glm-5"}, 11
    )

    assert record.model_id == "glm/glm-5"
    assert record.provider_id == "glm"
    assert responses[-1]["model_id"] == "glm/glm-5"
    host.ensure_bootstrapped.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_session_set_model_joins_inflight_bootstrap(monkeypatch, tmp_path):
    """Task model selection must not race the background worker warm-up."""
    monkeypatch.setattr(
        "appserver.model_routes.set_active",
        lambda params: {"ok": True, "id": params.get("id")},
    )
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path)
    host = SimpleNamespace(
        alive=lambda: True,
        bootstrapped=False,
        ensure_bootstrapped=AsyncMock(),
        set_model=AsyncMock(return_value={
            "ok": True,
            "model_id": "deepseek/deepseek-v4-flash",
            "provider_id": "deepseek",
        }),
    )
    server._session_hosts[record.session_id] = host
    responses = []
    monkeypatch.setattr(
        server,
        "_respond",
        AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload)),
    )

    await server._handle_session_set_model(
        {"session_id": record.session_id, "model_id": "deepseek/deepseek-v4-flash"},
        13,
    )

    host.ensure_bootstrapped.assert_awaited_once_with(timeout=_DEFAULT_WARM_TIMEOUT_SECONDS)
    host.set_model.assert_awaited_once()
    assert responses[-1]["ok"] is True


@pytest.mark.asyncio
async def test_session_set_model_persists_without_starting_worker(monkeypatch, tmp_path):
    persisted: list[str] = []

    def fake_set_active(params):
        persisted.append(str(params.get("id", "")))
        return {"ok": True, "id": params.get("id")}

    monkeypatch.setattr("appserver.model_routes.set_active", fake_set_active)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path)
    host_factory = AsyncMock(side_effect=AssertionError("must not spawn worker"))
    monkeypatch.setattr(server, "_host_for_session", host_factory)
    responses = []
    monkeypatch.setattr(
        server, "_respond", AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload))
    )

    await server._handle_session_set_model(
        {"session_id": record.session_id, "model_id": "deepseek/deepseek-v4-flash"}, 12
    )

    assert persisted == ["deepseek/deepseek-v4-flash"]
    assert record.model_id == "deepseek/deepseek-v4-flash"
    assert responses[-1]["ok"] is True
    host_factory.assert_not_awaited()
