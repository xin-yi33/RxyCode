"""Behavior tests for lifespan-owned API queue and scheduling services."""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


def _agent(result: str):
    agent = MagicMock()
    agent.run = AsyncMock(return_value=result)
    agent.cancel = MagicMock(return_value=True)
    agent.model_config = {"model_name": "test-model", "api_key": "test-key"}
    agent._memory = MagicMock()
    agent._session_loaded = False
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._stream_mode = False
    return agent


def _client(api_server):
    token = api_server.configure_api_token()
    return TestClient(
        api_server.app,
        client=("127.0.0.1", 50100),
        headers={"Authorization": f"Bearer {token}"},
    )


def test_queue_singleton_executes_real_prompt_and_persists_terminal_result(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0 import api_server

    expected = "queue-result:" + "x" * 2000
    agent = _agent(expected)
    previous = dict(api_server._state)
    api_server._state["agent"] = agent
    api_server._state["busy"] = False
    try:
        with _client(api_server) as client:
            queue_manager = api_server.app.state.queue_manager
            assert queue_manager is api_server._state["queue_manager"]
            assert api_server.app.state.task_deadline_seconds == 0

            added = client.post(
                "/command", json={"command": "/queue add inspect project"}
            ).json()
            task_id = added["task"]["id"]
            assert added["task"]["status"] == "pending"

            completed = client.post(
                "/command", json={"command": f"/queue run {task_id}"}
            ).json()
            assert completed["task"]["status"] == "succeeded"
            assert completed["task"]["result"] == expected
            assert completed["task"]["finished"]
            assert api_server.app.state.queue_manager is queue_manager

            listed = client.post(
                "/command", json={"command": "/queue list"}
            ).json()
            assert listed["tasks"] == [completed["task"]]
            agent.run.assert_awaited_once_with("inspect project", mode="build")
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


def test_scheduler_singleton_executes_prompt_and_persists_terminal_result(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler

    expected = "scheduled-result"
    agent = _agent(expected)
    previous = dict(api_server._state)
    api_server._state["agent"] = agent
    api_server._state["busy"] = False
    scheduler = None
    try:
        with _client(api_server) as client:
            scheduler = api_server.app.state.scheduler
            assert isinstance(scheduler, TaskScheduler)
            assert scheduler is api_server._state["scheduler"]
            assert scheduler._running is True

            added = client.post(
                "/command",
                json={"command": "/schedule add @daily index repository"},
            ).json()
            task_id = added["task"]["id"]

            completed = client.post(
                "/command", json={"command": f"/schedule run {task_id}"}
            ).json()
            assert completed["task"]["last_status"] == "succeeded"
            assert completed["task"]["last_result"] == expected
            assert completed["task"]["run_count"] == 1
            assert completed["task"]["last_run"]
            assert api_server.app.state.scheduler is scheduler

            listed = client.post(
                "/command", json={"command": "/schedule list"}
            ).json()
            assert listed["tasks"] == [completed["task"]]
            agent.run.assert_awaited_once_with("index repository", mode="build")

        assert scheduler._running is False
        assert api_server.app.state.scheduler is None
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


def test_zero_deadline_does_not_cancel_slow_queue_prompt(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server

    agent = _agent("unused")

    async def slow_run(message, mode):
        await asyncio.sleep(0.03)
        return f"finished:{message}:{mode}"

    agent.run = AsyncMock(side_effect=slow_run)
    previous = dict(api_server._state)
    api_server._state["agent"] = agent
    api_server._state["busy"] = False
    try:
        with _client(api_server) as client:
            assert api_server.app.state.task_deadline_seconds == 0
            added = client.post(
                "/command", json={"command": "/queue add patient task"}
            ).json()
            completed = client.post(
                "/command",
                json={"command": f"/queue run {added['task']['id']}"},
            ).json()

            assert completed["task"]["status"] == "succeeded"
            assert completed["task"]["result"] == "finished:patient task:build"
            agent.cancel.assert_not_called()
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


def test_configured_deadline_cancels_and_joins_queue_prompt(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server

    config_path = Path(os.environ["RXYCODE_DATA_DIR"]) / "config.yaml"
    config_path.write_text(
        "scheduler:\n"
        "  enabled: true\n"
        "  check_interval: 30\n"
        "  task_timeout_seconds: 0.01\n",
        encoding="utf-8",
    )
    cleanup_finished = threading.Event()
    agent = _agent("unused")

    async def blocking_run(_message, mode):
        assert mode == "build"
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_finished.set()

    agent.run = AsyncMock(side_effect=blocking_run)
    previous = dict(api_server._state)
    api_server._state["agent"] = agent
    api_server._state["busy"] = False
    try:
        with _client(api_server) as client:
            assert api_server.app.state.task_deadline_seconds == 0.01
            added = client.post(
                "/command", json={"command": "/queue add bounded task"}
            ).json()
            completed = client.post(
                "/command",
                json={"command": f"/queue run {added['task']['id']}"},
            ).json()

            assert completed["task"]["status"] == "timed_out"
            assert completed["task"]["result"].startswith(
                "[task_stall_timeout]"
            )
            assert cleanup_finished.is_set()
            assert api_server._state["service_tasks"] == set()
            agent.cancel.assert_called_once()
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


@pytest.mark.asyncio
async def test_cancel_joins_manual_scheduled_run_before_returning(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler

    started = asyncio.Event()
    release = asyncio.Event()
    side_effects = []
    agent = _agent("unused")

    async def blocking_run(message, mode):
        started.set()
        await release.wait()
        side_effects.append((message, mode))
        return "late mutation"

    agent.run = AsyncMock(side_effect=blocking_run)
    scheduler = TaskScheduler(storage_path=isolated_runtime.data_dir / "schedule.json")
    scheduled = scheduler.add_task("@daily", "mutate after cancel")
    previous = dict(api_server._state)
    api_server._state.update({
        "agent": agent,
        "scheduler": scheduler,
        "busy": False,
        "service_tasks": set(),
    })
    try:
        command_task = asyncio.create_task(
            api_server.command(
                api_server.CommandRequest(command=f"/schedule run {scheduled.id}")
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        cancel_result = await api_server.cancel_active_run()
        command_result = await asyncio.wait_for(command_task, timeout=1)

        assert cancel_result["cancelled"] is True
        assert command_result == {
            "action": "cancelled",
            "message": "Command cancelled",
        }
        assert scheduled.last_status == "cancelled"
        assert scheduled.last_result == "[cancelled: scheduled task]"
        assert api_server._state["service_tasks"] == set()
        agent.cancel.assert_called_once()

        release.set()
        await asyncio.sleep(0)
        assert side_effects == []
    finally:
        release.set()
        if not command_task.done():
            command_task.cancel()
            await asyncio.gather(command_task, return_exceptions=True)
        api_server._state.clear()
        api_server._state.update(previous)
