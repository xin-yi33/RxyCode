"""Safety checks for bounded idle session-worker retention."""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from appserver.agent_worker import AgentWorker, _subagents_enabled_from_env
from appserver.idle_policy import IdleWorkerPolicy
from appserver.server import AppServer
from core.subagents.definitions import AgentDefinitionRegistry
from core.subagents.manager import ChildSessionManager
from core.subagents.sessions import ChildSession, SessionTree
from protocol.subagents import ChildStatus, TaskRequest


class _Memory:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saves = 0

    def save_session(self) -> None:
        self.saves += 1
        if self.fail:
            raise OSError("persistence unavailable")


class _Manager:
    def __init__(
        self,
        *,
        active_children: int = 0,
        leases: int = 0,
        history: list[object] | None = None,
    ) -> None:
        self.active_children = active_children
        self.active_lease_count = leases
        self.history = history or []

    def get_tree(self, _session_id: str):
        return SimpleNamespace(
            list_active=lambda: [object()] * self.active_children,
            list_all=lambda: self.history,
        )


def _worker(
    *, enabled: bool | None, manager: object | None, memory: _Memory | None = None
) -> AgentWorker:
    worker = AgentWorker()
    worker._agent = SimpleNamespace(
        _memory=memory or _Memory(),
        _user_turn_active=False,
        _prewarm_task=None,
    )
    worker._subagent_manager = manager
    worker._subagents_enabled = enabled
    worker._run_task = None
    worker._subagent_tasks = set()
    worker._pending = {}
    worker._write_failures = []
    worker._background_tasks = set()
    worker._flush_pending_writes = AsyncMock()
    worker._write_ordered = AsyncMock()
    return worker


class _Host:
    def __init__(self, *, prepare=None, pid: int = 101) -> None:
        self._alive = True
        self._retiring = False
        self._active_rpc_count = 0
        self._bootstrap_task = None
        self.bootstrapped = True
        self.degraded = False
        self.last_activity_at = 0.0
        self.pid = pid
        self.prepare = prepare
        self.kill_calls = 0

    def alive(self) -> bool:
        return self._alive

    @property
    def active_rpc_count(self) -> int:
        return self._active_rpc_count

    @property
    def retiring(self) -> bool:
        return self._retiring

    def begin_retirement(self, *, force: bool = False) -> bool:
        del force
        if self._retiring:
            return False
        self._retiring = True
        return True

    def cancel_retirement(self) -> None:
        self._retiring = False

    async def prepare_suspend(self, **_kwargs):
        if self.prepare is not None:
            return await self.prepare()
        return {"safe": True, "persisted": True}

    async def kill_async(self) -> None:
        self.kill_calls += 1
        self._alive = False


def _server_with_host(tmp_path: Path, host: _Host):
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path)
    server._sessions.update_status(record.session_id, "succeeded")
    server._session_hosts[record.session_id] = host
    server._worker_idle_policy = IdleWorkerPolicy(idle_seconds=1, max_idle_workers=2)
    return server, record.session_id


@pytest.mark.asyncio
async def test_subagents_disabled_manager_none_can_retire_idle_worker(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    enabled = _subagents_enabled_from_env()
    assert enabled is False
    memory = _Memory()
    worker = _worker(enabled=enabled, manager=None, memory=memory)
    responses: list[dict] = []

    async def capture_response(message):
        responses.append(message)

    worker._write_ordered = capture_response

    async def prepare():
        await worker._handle_prepare_suspend(1)
        return responses[-1]["result"]

    host = _Host(prepare=prepare)
    server, session_id = _server_with_host(tmp_path, host)

    retired = await server._reap_idle_workers_once(now=2.0)

    assert retired == [session_id]
    assert memory.saves == 1
    assert responses[-1]["result"] == {"ok": True, "safe": True, "persisted": True}
    assert host.kill_calls == 1
    assert session_id not in server._session_hosts
    server._instance_lock.release()


@pytest.mark.parametrize("enabled", [True, None])
def test_missing_enabled_or_unknown_subagent_manager_fails_closed(enabled):
    worker = _worker(enabled=enabled, manager=None)
    assert worker._prepare_suspend_blocker() == "subagent_state_unavailable"


@pytest.mark.asyncio
async def test_worker_prepare_blocks_pending_approval_and_question():
    for request_id in (41, 42):
        worker = _worker(enabled=True, manager=_Manager())
        worker._pending[request_id] = asyncio.get_running_loop().create_future()
        assert worker._prepare_suspend_blocker() == "approval_or_question_pending"


@pytest.mark.parametrize(
    ("children", "leases", "reason"),
    [
        (1, 0, "child_session_active"),
        (0, 1, "write_lease_active"),
    ],
)
def test_worker_prepare_blocks_live_children_and_write_leases(children, leases, reason):
    worker = _worker(
        enabled=True,
        manager=_Manager(active_children=children, leases=leases),
    )
    assert worker._prepare_suspend_blocker() == reason


def test_completed_child_history_blocks_suspend_with_distinct_active_reason():
    history = [object()]
    history_worker = _worker(
        enabled=True,
        manager=_Manager(history=history),
    )
    assert history_worker._prepare_suspend_blocker() == "child_history_not_rehydratable"

    active_worker = _worker(
        enabled=True,
        manager=_Manager(active_children=1, history=history),
    )
    assert active_worker._prepare_suspend_blocker() == "child_session_active"


@pytest.mark.asyncio
async def test_terminal_child_history_pins_worker_and_list_retry_remain_available(
    tmp_path,
):
    server, session_id = _server_with_host(tmp_path, _Host())
    manager = ChildSessionManager(registry=AgentDefinitionRegistry())
    tree = SessionTree(root_session_id=session_id)
    child = ChildSession(
        session_id="terminal-child-history",
        parent_session_id=session_id,
        root_session_id=session_id,
        agent_id="test-agent",
    )
    child._status = ChildStatus.COMPLETED
    tree.add(child)
    manager._trees[session_id] = tree
    manager._requests_by_session[child.session_id] = TaskRequest(
        request_id="original-child-request",
        parent_session_id=session_id,
        agent_id=child.agent_id,
        prompt="original child task",
    )
    manager.dispatch = AsyncMock()

    worker = _worker(enabled=True, manager=manager)
    worker._session_id = session_id
    responses: list[dict] = []

    async def capture_response(message):
        responses.append(message)

    worker._write_ordered = capture_response

    async def prepare():
        await worker._handle_prepare_suspend(1)
        return responses[-1]["result"]

    host = _Host(prepare=prepare)
    server._session_hosts[session_id] = host
    try:
        assert (
            worker._prepare_suspend_blocker()
            == "child_history_not_rehydratable"
        )
        assert await server._reap_idle_workers_once(now=2.0) == []
        assert server._session_hosts[session_id] is host
        assert host.alive()
        assert host.kill_calls == 0

        await worker._handle_child_sessions_list(
            {"root_session_id": session_id}, 2
        )
        listed = responses[-1]["result"]["sessions"]
        assert [item["session_id"] for item in listed] == [child.session_id]
        assert listed[0]["status"] == ChildStatus.COMPLETED.value

        await worker._handle_child_session_retry(
            {
                "root_session_id": session_id,
                "session_id": child.session_id,
                "request_id": "retry-child-request",
            },
            3,
        )
        assert responses[-1]["result"] == {
            "accepted": True,
            "request_id": "retry-child-request",
        }
        retry_tasks = tuple(worker._subagent_tasks)
        assert len(retry_tasks) == 1
        await asyncio.gather(*retry_tasks)
        manager.dispatch.assert_awaited_once()
        retry_request = manager.dispatch.await_args.args[0]
        assert retry_request.request_id == "retry-child-request"
        assert retry_request.prompt == "original child task"
    finally:
        await server._kill_session_host(session_id)
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_empty_subagent_tree_does_not_pin_idle_worker(tmp_path):
    server, session_id = _server_with_host(tmp_path, _Host())
    manager = ChildSessionManager(registry=AgentDefinitionRegistry())
    worker = _worker(enabled=True, manager=manager)
    worker._session_id = session_id
    responses: list[dict] = []

    async def capture_response(message):
        responses.append(message)

    worker._write_ordered = capture_response

    async def prepare():
        await worker._handle_prepare_suspend(1)
        return responses[-1]["result"]

    host = _Host(prepare=prepare)
    server._session_hosts[session_id] = host
    try:
        assert worker._prepare_suspend_blocker() is None
        assert await server._reap_idle_workers_once(now=2.0) == [session_id]
        assert session_id not in server._session_hosts
        assert not host.alive()
    finally:
        await server._kill_session_host(session_id)
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_persisted_child_pin_is_excluded_from_idle_capacity(tmp_path):
    server = AppServer(stub=True)
    pinned_record = server._sessions.create(tmp_path)
    normal_records = [server._sessions.create(tmp_path) for _ in range(2)]
    for record in (pinned_record, *normal_records):
        server._sessions.update_status(record.session_id, "succeeded")
    child = server._sessions.ensure_child(
        session_id="persisted-terminal-child",
        parent_session_id=pinned_record.session_id,
        workspace_root=tmp_path,
    )
    server._sessions.record_child_terminal(child.session_id, "succeeded")

    pinned_host = _Host(pid=201)
    normal_hosts = [_Host(pid=202), _Host(pid=203)]
    hosts = {
        pinned_record.session_id: pinned_host,
        **{
            record.session_id: host
            for record, host in zip(normal_records, normal_hosts, strict=True)
        },
    }
    server._session_hosts.update(hosts)
    now = max(1000.0, time.monotonic())
    pinned_host.last_activity_at = now - 100
    normal_hosts[0].last_activity_at = now - 200
    normal_hosts[1].last_activity_at = now - 300
    server._worker_idle_policy = IdleWorkerPolicy(
        idle_seconds=600,
        max_idle_workers=2,
    )

    try:
        assert server._sessions.child_count(pinned_record.session_id) == 1
        assert (
            server._idle_worker_protection_reason(
                pinned_record.session_id, pinned_host
            )
            == "persisted_child_history"
        )
        for record, host in zip(normal_records, normal_hosts, strict=True):
            assert server._idle_worker_protection_reason(record.session_id, host) is None

        assert await server._reap_idle_workers_once(now=now) == []
        assert all(server._session_hosts[sid] is host for sid, host in hosts.items())
        assert all(host.alive() and host.kill_calls == 0 for host in hosts.values())
    finally:
        for session_id in hosts:
            await server._kill_session_host(session_id)
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_persistence_failure_retains_idle_worker(tmp_path):
    async def fail_prepare():
        raise OSError("save failed")

    host = _Host(prepare=fail_prepare)
    server, session_id = _server_with_host(tmp_path, host)

    assert await server._reap_idle_workers_once(now=2.0) == []
    assert server._session_hosts[session_id] is host
    assert host.alive()
    assert host.kill_calls == 0
    assert not host.retiring
    server._instance_lock.release()


@pytest.mark.asyncio
async def test_server_pending_request_and_enabled_schedule_protect_idle_worker(
    tmp_path,
):
    host = _Host()
    server, session_id = _server_with_host(tmp_path, host)
    pending = asyncio.get_running_loop().create_future()
    server._pending_server[7] = pending
    assert (
        server._idle_worker_protection_reason(session_id, host)
        == "server_request_pending"
    )
    server._pending_server.clear()
    server._schedule._jobs["goal-or-loop"] = {
        "enabled": True,
        "action": {"session_id": session_id},
    }
    assert (
        server._idle_worker_protection_reason(session_id, host)
        == "session_schedule_enabled_or_active"
    )
    server._schedule._jobs["goal-or-loop"]["enabled"] = False
    server._schedule._queue.append("goal-or-loop")
    assert (
        server._idle_worker_protection_reason(session_id, host)
        == "session_schedule_enabled_or_active"
    )
    server._instance_lock.release()


@pytest.mark.asyncio
async def test_unowned_or_unknown_running_schedule_fails_closed(tmp_path):
    host = _Host()
    server, session_id = _server_with_host(tmp_path, host)
    server._schedule._jobs["unknown-owner"] = {"enabled": False}
    server._schedule._running.add("unknown-owner")
    assert (
        server._idle_worker_protection_reason(session_id, host)
        == "schedule_state_unknown"
    )
    server._instance_lock.release()


@pytest.mark.asyncio
async def test_real_worker_prompt_remains_protected_past_idle_ttl(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path)
    server._sessions.update_status(record.session_id, "succeeded")
    server._worker_idle_policy = IdleWorkerPolicy(idle_seconds=0.1, max_idle_workers=2)
    try:
        host = await server._host_for_session(record.session_id)
        await host.ensure_bootstrapped(timeout=20)
        host._last_activity_at = time.monotonic() - 100
        prompt = asyncio.create_task(
            host.run_prompt(
                text="silent:0.7",
                run_id="idle-lifecycle-long-turn",
                timeout=10,
                emit=lambda _message: None,
            )
        )
        deadline = time.monotonic() + 5
        while host.active_rpc_count == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert host.active_rpc_count > 0

        assert await server._reap_idle_workers_once(now=time.monotonic()) == []
        assert host.alive()
        assert server._session_hosts[record.session_id] is host
        assert (await prompt)["text"] == "stub:silent-complete"
    finally:
        await server._kill_session_host(record.session_id)
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_new_queued_placeholder_warms_then_retires_on_idle_sweep(
    monkeypatch, tmp_path
):
    """The default queued status means an empty session, not queued prompt work."""
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    server = AppServer(stub=True)
    responses: list[dict] = []
    server._respond = AsyncMock(
        side_effect=lambda _request_id, payload: responses.append(payload)
    )
    server._emit_model = AsyncMock()
    server._worker_idle_policy = IdleWorkerPolicy(idle_seconds=0.1, max_idle_workers=2)
    try:
        await server._handle_session_new({"workspace_root": str(tmp_path)}, 1)
        session_id = responses[-1]["session_id"]
        record = server._sessions.get(session_id)
        assert record is not None
        assert record.status == "queued"

        await server._handle_warm({"session_id": session_id}, 2)
        host = server._session_hosts[session_id]
        host._last_activity_at = time.monotonic() - 100
        assert server._idle_worker_protection_reason(session_id, host) is None

        assert await server._reap_idle_workers_once(now=time.monotonic()) == [session_id]
        assert not host.alive()
        assert server._sessions.get(session_id).status == "queued"
    finally:
        await server._kill_session_host(responses[-1].get("session_id", ""))
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_prompt_arriving_during_prepare_save_is_not_lost(monkeypatch, tmp_path):
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path)
    server._sessions.update_status(record.session_id, "succeeded")
    server._worker_idle_policy = IdleWorkerPolicy(idle_seconds=0.1, max_idle_workers=2)
    try:
        host = await server._host_for_session(record.session_id)
        await host.ensure_bootstrapped(timeout=20)
        original_prepare = host.prepare_suspend
        entered, release = asyncio.Event(), asyncio.Event()

        async def paused_prepare(**kwargs):
            entered.set()
            await release.wait()
            return await original_prepare(**kwargs)

        host.prepare_suspend = paused_prepare
        host._last_activity_at = time.monotonic() - 100
        reaper = asyncio.create_task(
            server._reap_idle_workers_once(now=time.monotonic())
        )
        await asyncio.wait_for(entered.wait(), timeout=5)

        async def resumed_turn():
            async with server._session_lock(record.session_id):
                current = await server._host_for_session(record.session_id)
                return await current.run_prompt(
                    text="turn-arrived-during-save",
                    run_id="idle-lifecycle-race",
                    timeout=10,
                    emit=lambda _message: None,
                )

        prompt = asyncio.create_task(resumed_turn())
        server._track_prompt_task(prompt, record.session_id)
        await asyncio.sleep(0)
        release.set()

        assert await reaper == []
        assert (await prompt)["text"] == "stub:turn-arrived-during-save"
        assert host.alive()
        assert server._session_hosts[record.session_id] is host
    finally:
        await server._kill_session_host(record.session_id)
        server._instance_lock.release()


@pytest.mark.asyncio
async def test_graceful_worker_exit_disconnects_owned_mcp_child(monkeypatch):
    from core.agent_v2 import AgentV2
    from mcp.client import MCPClient

    client = MCPClient("lifecycle-test", sys.executable)
    sidecar = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client._process = sidecar
    agent = object.__new__(AgentV2)
    agent._mcp_lock = threading.RLock()
    agent._mcp_clients = {"lifecycle-test": client}
    agent._mcp_tool_names = set()
    agent._mcp_server_tool_names = {}
    agent._mcp_server_fingerprints = {}
    agent._mcp_errors = {}
    agent._mcp_retry_state = {}
    agent._mcp_config_fingerprint = None
    agent._mcp_runtime = {}
    worker = AgentWorker()
    worker._agent = agent
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "shutdown", "params": {}}
            )
            + "\n"
        ),
    )
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)

    try:
        await worker.run()
        assert sidecar.wait(timeout=3) is not None
        assert client._process is None
        assert json.loads(output.getvalue().strip())["result"] == {"ok": True}
    finally:
        if sidecar.poll() is None:
            sidecar.kill()
            sidecar.wait(timeout=3)


def test_idle_worker_policy_env_validation(monkeypatch):
    monkeypatch.setenv("RXYCODE_WORKER_IDLE_SECONDS", "0")
    monkeypatch.setenv("RXYCODE_MAX_IDLE_WORKERS", "3")
    assert IdleWorkerPolicy.from_env() == IdleWorkerPolicy(0, 3)
    monkeypatch.setenv("RXYCODE_WORKER_IDLE_SECONDS", "nan")
    monkeypatch.setenv("RXYCODE_MAX_IDLE_WORKERS", "-1")
    assert IdleWorkerPolicy.from_env() == IdleWorkerPolicy(600, 2)
