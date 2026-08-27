import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from appserver.agent_worker import AgentWorker, bootstrap_subagent_manager
from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import reset_manager


def test_worker_bootstrap_owns_manager_and_persists_outside_workspace(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "rxycode-data"
    workspace = tmp_path / "user-workspace"
    workspace.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "1")
    monkeypatch.setenv("RXYCODE_SUBAGENTS_TASK", "1")
    reset_manager()
    try:
        manager, store = bootstrap_subagent_manager(
            session_id="primary-1",
            workspace_root=workspace,
            emit=lambda _method, _params: None,
        )
        assert manager.capability.subagents_enabled is True
        assert manager.capability.task is True
        assert manager.registry.get("primary").task_permission.allows("explore") is True
        assert store.persist_dir is not None
        assert Path(store.persist_dir).is_relative_to(data_dir)
        assert not Path(store.persist_dir).is_relative_to(workspace)
    finally:
        reset_manager()


def test_worker_bootstrap_enables_subagents_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("RXYCODE_SUBAGENTS", raising=False)
    monkeypatch.delenv("RXYCODE_SUBAGENTS_TASK", raising=False)
    monkeypatch.delenv("RXYCODE_SUBAGENTS_MENTION", raising=False)
    reset_manager()
    try:
        manager, _store = bootstrap_subagent_manager(
            session_id="primary-2",
            workspace_root=tmp_path,
            emit=lambda _method, _params: None,
        )
        assert manager.capability.subagents_enabled is True
        assert manager.capability.task is True
        assert manager.capability.mention is True
        assert manager.capability.child_tasks is False
    finally:
        reset_manager()


def test_worker_bootstrap_honors_master_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    reset_manager()
    try:
        manager, _store = bootstrap_subagent_manager(
            session_id="primary-off",
            workspace_root=tmp_path,
            emit=lambda _method, _params: None,
        )
        assert manager.capability.subagents_enabled is False
        assert manager.capability.task is False
        assert manager.capability.mention is False
    finally:
        reset_manager()


@pytest.mark.asyncio
async def test_worker_serves_capability_from_its_owned_manager(monkeypatch):
    worker = AgentWorker()
    worker._subagent_manager = SimpleNamespace(
        active_lease_count=0,
        capability=SimpleNamespace(
            protocol_version=1,
            subagents_enabled=True,
            task=True,
            mention=True,
            child_tasks=False,
        )
    )
    write = AsyncMock()
    monkeypatch.setattr(worker, "_write_ordered", write)

    await worker._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "subagents/capability",
            "params": {},
        }
    )

    payload = write.await_args.args[0]
    assert payload["id"] == 41
    assert payload["result"]["subagents_enabled"] is True
    assert payload["result"]["task"] is True


@pytest.mark.asyncio
async def test_worker_lists_agents_from_its_owned_manager(monkeypatch):
    worker = AgentWorker()
    worker._subagent_manager = SimpleNamespace(
        registry=SimpleNamespace(
            list_visible=lambda: [
                SimpleNamespace(
                    id="explore",
                    description="Read-only repository explorer",
                    mode=SimpleNamespace(value="subagent"),
                    model=None,
                    hidden=False,
                )
            ]
        )
    )
    write = AsyncMock()
    monkeypatch.setattr(worker, "_write_ordered", write)

    await worker._dispatch(
        {"jsonrpc": "2.0", "id": 42, "method": "subagents/list", "params": {}}
    )

    result = write.await_args.args[0]["result"]
    assert result["agents"] == [
        {
            "id": "explore",
            "description": "Read-only repository explorer",
            "mode": "subagent",
            "model": None,
        }
    ]


@pytest.mark.asyncio
async def test_worker_accepts_child_task_without_blocking_rpc(monkeypatch):
    worker = AgentWorker()
    dispatch = AsyncMock(return_value=SimpleNamespace())
    worker._subagent_manager = SimpleNamespace(dispatch=dispatch)
    write = AsyncMock()
    monkeypatch.setattr(worker, "_write_ordered", write)

    await worker._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 43,
            "method": "task/start",
            "params": {
                "request_id": "req-43",
                "root_session_id": "primary-1",
                "parent_session_id": "primary-1",
                "agent_id": "explore",
                "prompt": "Audit the release",
            },
        }
    )
    await asyncio.sleep(0)

    response = write.await_args_list[0].args[0]
    assert response["result"] == {"accepted": True, "request_id": "req-43"}
    request = dispatch.await_args.args[0]
    assert request.parent_session_id == "primary-1"
    assert request.agent_id == "explore"


@pytest.mark.asyncio
async def test_worker_replays_only_events_for_requested_root(monkeypatch):
    worker = AgentWorker()
    event = SimpleNamespace(
        root_session_id="primary-1", seq=3, to_dict=lambda: {"seq": 3}
    )
    worker._subagent_event_store = SimpleNamespace(
        events_from=lambda cursor: [event],
        latest_cursor=lambda: 3,
        detect_gaps=lambda start, end: [],
    )
    write = AsyncMock()
    monkeypatch.setattr(worker, "_write_ordered", write)

    await worker._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 44,
            "method": "child_sessions/events",
            "params": {"root_session_id": "primary-1", "cursor": 0},
        }
    )

    result = write.await_args.args[0]["result"]
    assert result == {
        "events": [{"seq": 3}],
        "next_cursor": 3,
        "gap_detected": False,
    }


@pytest.mark.asyncio
async def test_worker_interrupt_cancels_entire_child_tree(monkeypatch):
    worker = AgentWorker()
    manager = SimpleNamespace(cancel_root=Mock())
    worker._subagent_manager = manager
    child_task = asyncio.create_task(asyncio.Event().wait())
    worker._subagent_tasks.add(child_task)
    write = AsyncMock()
    monkeypatch.setattr(worker, "_write_ordered", write)

    await worker._handle_interrupt(45)

    manager.cancel_root.assert_called_once_with(worker._session_id)
    assert child_task.cancelled()
    assert write.await_args.args[0]["result"]["cancelled"] is True
