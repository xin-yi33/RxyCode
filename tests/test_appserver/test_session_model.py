"""Regression tests for task-scoped model selection."""

from __future__ import annotations

import asyncio
import threading
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
async def test_worker_model_switch_does_not_freeze_the_loop(monkeypatch):
    """switch_model 的磁盘 I/O 必须跑在线程里，不能卡住 worker 事件循环。"""
    worker = AgentWorker()
    release = threading.Event()

    class Agent:
        def switch_model(self, model_id: str) -> dict[str, str]:
            release.wait(5.0)
            return {"model_id": model_id, "provider_id": "glm"}

    worker._agent = Agent()
    responses = []

    async def capture(payload):
        responses.append(payload)

    monkeypatch.setattr(worker, "_write_ordered", capture)

    task = asyncio.create_task(
        worker._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "model/switch",
                "params": {"model_id": "glm/glm-5"},
            }
        )
    )
    ticks = 0
    for _ in range(20):
        await asyncio.sleep(0.001)
        ticks += 1
    assert ticks == 20
    assert not task.done()
    release.set()
    await asyncio.wait_for(task, timeout=5.0)
    assert responses[-1]["result"]["ok"] is True
    assert responses[-1]["result"]["model_id"] == "glm/glm-5"


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
async def test_session_set_model_does_not_persist_active_model(monkeypatch, tmp_path):
    """前端先调 models/set_active 持久化；set_model 只做任务级切换，不再重写。"""
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

    assert persisted == []
    assert record.model_id == "deepseek/deepseek-v4-flash"
    assert responses[-1]["ok"] is True
    host_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_models_list_and_set_active_run_off_the_event_loop(monkeypatch):
    """models/list 与 models/set_active 的同步磁盘 I/O 移出 appserver 事件循环。"""
    server = AppServer(stub=True)
    server._initialized = True
    calls: list[str] = []
    real_to_thread = asyncio.to_thread

    async def spy(func, /, *args, **kwargs):
        calls.append(getattr(func, "__name__", repr(func)))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)

    def list_models() -> dict:
        return {"ok": True, "models": []}

    def set_active(params: dict) -> dict:
        return {"ok": True, "id": params.get("id")}

    monkeypatch.setattr("appserver.model_routes.list_models", list_models)
    monkeypatch.setattr("appserver.model_routes.set_active", set_active)
    responses = []
    monkeypatch.setattr(
        server,
        "_respond",
        AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload)),
    )

    await server._dispatch({"jsonrpc": "2.0", "id": 1, "method": "models/list", "params": {}})
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "models/set_active", "params": {"id": "glm/glm-5"}}
    )

    assert calls == ["list_models", "set_active"]
    assert responses == [{"ok": True, "models": []}, {"ok": True, "id": "glm/glm-5"}]
