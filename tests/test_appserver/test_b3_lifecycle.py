"""PhaseG-B3 process lifecycle, lock, and recovery_required."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from appserver.lifecycle import InstanceLock, mark_incomplete_recovery_required
from appserver.server import AppServer
from appserver.task_store import DesktopTaskStore


def _live_holder(tmp_path: Path) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock = tmp_path / "appserver.lock"
    lock.write_text(json.dumps({"pid": proc.pid}), encoding="utf-8")
    return proc


def test_instance_lock_refuses_live_holder(tmp_path: Path) -> None:
    path = tmp_path / "appserver.lock"
    holder = _live_holder(tmp_path)
    try:
        second = InstanceLock(path)
        ok, reason = second.acquire()
        assert ok is False
        assert "already running" in reason
    finally:
        holder.kill()
        holder.wait(timeout=5)
    ok, _ = InstanceLock(path).acquire()
    assert ok
    InstanceLock(path).release()


def test_stale_lock_is_stolen(tmp_path: Path) -> None:
    path = tmp_path / "appserver.lock"
    path.write_text(json.dumps({"pid": 2_000_000_000}), encoding="utf-8")
    lock = InstanceLock(path)
    ok, _ = lock.acquire()
    assert ok
    lock.release()


def test_incomplete_tasks_become_recovery_required_not_completed(tmp_path: Path) -> None:
    store = DesktopTaskStore(tmp_path / "tasks.json", persistent=True)
    store.upsert(session_id="run1", title="a", workspace_root=tmp_path, status="running")
    store.upsert(session_id="ok1", title="b", workspace_root=tmp_path, status="succeeded")
    store.upsert(session_id="q1", title="c", workspace_root=tmp_path, status="queued")
    changed = mark_incomplete_recovery_required(store)
    ids = {item[0] for item in changed}
    assert ids == {"run1", "q1"}
    assert store.get("run1")["status"] == "recovery_required"
    assert store.get("q1")["status"] == "recovery_required"
    assert store.get("ok1")["status"] == "succeeded"


@pytest.mark.asyncio
async def test_start_fails_when_instance_in_use(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "appserver.lock"
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(lock_path))
    holder = _live_holder(tmp_path)
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    assert server._instance_blocked
    try:
        await server.run()
        fail = next(item for item in sent if item.get("method") == "event/process_failed")
        assert fail["params"]["error_code"] == "INSTANCE_IN_USE"
    finally:
        holder.kill()
        holder.wait(timeout=5)


@pytest.mark.asyncio
async def test_force_close_marks_running_recovery_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "appserver.lock"))
    server = AppServer(stub=False)
    record = server._sessions.create(tmp_path, title="open")
    server._sessions.update_status(record.session_id, "running")
    sent: list[dict] = []
    monkeypatch.setattr("appserver.server.write_message_sync", lambda msg: sent.append(msg))
    server._mark_inflight_recovery_required()
    assert server._sessions.get(record.session_id).status == "recovery_required"
    assert store_status(tmp_path, record.session_id) != "succeeded"


def store_status(data_dir: Path, session_id: str) -> str:
    store = DesktopTaskStore(data_dir / "desktop" / "tasks.json", persistent=True)
    task = store.get(session_id)
    return str((task or {}).get("status"))


def test_restart_recovers_running_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "appserver.lock"))
    store = DesktopTaskStore(tmp_path / "desktop" / "tasks.json", persistent=True)
    store.upsert(session_id="dead", title="t", workspace_root=tmp_path, status="running")
    server = AppServer(stub=False)
    assert ("dead", "running") in server._recovered_sessions
    assert server._sessions.get("dead").status == "recovery_required"


def test_twenty_start_stop_releases_lock(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "appserver.lock"
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(lock_path))
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    for _ in range(20):
        server = AppServer(stub=True)
        assert server._instance_blocked is None
        server._instance_lock.release()
    assert not lock_path.exists()


@pytest.mark.asyncio
async def test_process_started_on_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "lock"))
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)

    class _EOF:
        def readline(self) -> str:
            return ""

    monkeypatch.setattr("appserver.server.sys.stdin", _EOF())
    server = AppServer(stub=True)
    await server.run()
    methods = [item.get("method") for item in sent]
    assert "event/process_started" in methods
    assert "event/process_shutdown" in methods


@pytest.mark.asyncio
async def test_boot_failure_emits_process_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("RXYCODE_APPSERVER_FAIL_BOOT", "1")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server.run()
    fail = next(item for item in sent if item.get("method") == "event/process_failed")
    assert fail["params"]["error_code"] == "BOOT_FAILED"
    assert not (tmp_path / "lock").exists()


def test_blocked_instance_does_not_rewrite_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "appserver.lock"))
    store = DesktopTaskStore(tmp_path / "desktop" / "tasks.json", persistent=True)
    store.upsert(session_id="keep", title="t", workspace_root=tmp_path, status="running")
    holder = _live_holder(tmp_path)
    try:
        server = AppServer(stub=False)
        assert server._instance_blocked
        assert server._recovered_sessions == []
        assert store.get("keep")["status"] == "running"
    finally:
        holder.kill()
        holder.wait(timeout=5)


def test_appserver_logs_stay_off_stdout() -> None:
    main = Path(__file__).resolve().parents[2] / "appserver" / "__main__.py"
    text = main.read_text(encoding="utf-8")
    assert "stream=sys.stderr" in text
