"""Appserver instance lock, preempt, and recovery_required."""

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


def test_unreaped_killed_holder_lock_is_stolen(tmp_path: Path) -> None:
    holder = _live_holder(tmp_path)
    try:
        holder.kill()
        ok, _ = InstanceLock(tmp_path / "appserver.lock").acquire()
        assert ok is True
    finally:
        holder.wait(timeout=5)


def test_preempt_kills_live_holder_then_acquires(tmp_path: Path) -> None:
    path = tmp_path / "appserver.lock"
    holder = _live_holder(tmp_path)
    try:
        lock = InstanceLock(path)
        ok, reason = lock.acquire()
        assert ok is False
        assert "already running" in reason
        ok, _ = lock.preempt_and_acquire()
        assert ok is True
        holder.wait(timeout=5)
        assert holder.poll() is not None
        lock.release()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_preempt_env_lets_appserver_take_over(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_APPSERVER_LOCK", str(tmp_path / "appserver.lock"))
    monkeypatch.setenv("RXYCODE_APPSERVER_PREEMPT", "1")
    holder = _live_holder(tmp_path)
    try:
        server = AppServer(stub=True)
        assert server._instance_blocked is None
        holder.wait(timeout=5)
        assert holder.poll() is not None
        server._instance_lock.release()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


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
        server._instance_lock.release()
    finally:
        holder.kill()
        holder.wait(timeout=5)
