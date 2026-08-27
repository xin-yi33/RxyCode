"""PhaseG-B16 application-layer asyncio scheduler."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from appserver.permission import PermissionStore
from appserver.schedule_service import ScheduleService
from appserver.sessions import SessionStore
from appserver.task_store import DesktopTaskStore
from protocol.schema import export_schema
from scheduler.rules import next_fire, parse_rule


def _perms() -> PermissionStore:
    store = PermissionStore(persistent=False)
    store.set_profile("workspace_write")
    return store


def _service(tmp_path: Path) -> ScheduleService:
    store = DesktopTaskStore(persistent=False)
    sessions = SessionStore(task_store=store)
    return ScheduleService(
        path=tmp_path / "schedules.json",
        persistent=True,
        sessions=sessions,
        permissions=_perms(),
        task_store=store,
        max_parallel=2,
    )


def test_interval_and_at_rules() -> None:
    interval = parse_rule({"kind": "interval", "every": 10, "unit": "minutes"})
    stamp = datetime(2026, 8, 19, 12, 0, 0)
    nxt = next_fire(interval, stamp)
    assert nxt == datetime(2026, 8, 19, 12, 10, 0)
    at = parse_rule({"kind": "at", "time": "14:30"})
    assert next_fire(at, datetime(2026, 8, 19, 14, 0, 0)).hour == 14
    assert next_fire(at, datetime(2026, 8, 19, 15, 0, 0)).day == 20


def test_create_tick_persist_restore(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.sessions.create(tmp_path, title="s")
    job = service.create(
        rule={"kind": "interval", "every": 1, "unit": "minutes"},
        action={"kind": "session", "session_id": session.session_id, "message": "hello"},
        now=datetime(2026, 8, 19, 12, 0, 0),
    )
    assert job["next_fire"]
    fired = service.tick(datetime(2026, 8, 19, 12, 2, 0))
    assert fired[0]["ok"] is True
    assert fired[0]["result"]["delivered"] is True
    events, _, _ = service.task_store.events(session.session_id, 0)
    assert any(item.get("method") == "event/user_message" for item in events)
    assert any(row.get("action") == "fire" for row in service.audit())
    service._jobs[job["id"]]["run_status"] = "running"
    service._save()
    restored = ScheduleService(
        path=tmp_path / "schedules.json",
        persistent=True,
        sessions=service.sessions,
        permissions=_perms(),
        task_store=service.task_store,
    )
    assert restored._jobs[job["id"]]["run_status"] == "recovery_required"
    restored.reclaim_orphans()
    assert restored._jobs[job["id"]]["run_status"] == "idle"


def test_permission_not_bypassed(tmp_path: Path) -> None:
    store = DesktopTaskStore(persistent=False)
    sessions = SessionStore(task_store=store)
    session = sessions.create(tmp_path, title="s")
    denied = ScheduleService(
        path=tmp_path / "s.json",
        persistent=False,
        sessions=sessions,
        permissions=PermissionStore(persistent=False),
        task_store=store,
    )
    denied.create(
        rule={"kind": "interval", "every": 1, "unit": "minutes"},
        action={"kind": "session", "session_id": session.session_id, "message": "x"},
        now=datetime(2026, 8, 19, 12, 0, 0),
    )
    result = denied.tick(datetime(2026, 8, 19, 12, 2, 0))[0]
    assert result["ok"] is False
    assert result["error_code"] == "SCHEDULE_DENIED"


def test_parallel_queue(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.sessions.create(tmp_path, title="s")
    ids = []
    for _ in range(3):
        job = service.create(
            rule={"kind": "interval", "every": 1, "unit": "minutes"},
            action={"kind": "session", "session_id": session.session_id, "message": "x"},
            now=datetime(2026, 8, 19, 12, 0, 0),
        )
        ids.append(job["id"])
    service._running = set(ids[:2])
    queued = service.fire(ids[2], now=datetime(2026, 8, 19, 12, 2, 0))
    assert queued["queued"] is True
    assert ids[2] in service.list_jobs()["queue"]


def test_no_os_scheduler_dependency() -> None:
    text = Path("appserver/schedule_service.py").read_text(encoding="utf-8") + Path(
        "scheduler/rules.py"
    ).read_text(encoding="utf-8")
    for banned in ("import launchd", "schtasks", "crontab -", "from crontab"):
        assert banned not in text
    assert "asyncio" in Path("appserver/schedule_service.py").read_text(encoding="utf-8")
    assert "next_fire" in Path("scheduler/rules.py").read_text(encoding="utf-8")


def test_schema_has_schedule_methods() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "ScheduleListRequest",
        "ScheduleCreateRequest",
        "ScheduleUpdateRequest",
        "ScheduleDeleteRequest",
        "ScheduleToggleRequest",
    ):
        assert name in defs


@pytest.mark.asyncio
async def test_protocol_schedule_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    session = server._sessions.create(tmp_path, title="s")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "schedule/create",
            "params": {
                "rule": {"kind": "at", "time": "09:00"},
                "action": {"kind": "session", "session_id": session.session_id, "message": "hi"},
            },
        }
    )
    created = next(item["result"] for item in sent if item.get("id") == 1)
    assert created["id"].startswith("sch_")
    sent.clear()
    await server._dispatch({"jsonrpc": "2.0", "id": 2, "method": "schedule/list", "params": {}})
    listed = next(item["result"] for item in sent if item.get("id") == 2)
    assert listed["jobs"]
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "schedule/toggle", "params": {"job_id": created["id"], "enabled": False}}
    )
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "schedule/delete", "params": {"job_id": created["id"]}}
    )


def test_once_at_does_not_repeat(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.sessions.create(tmp_path, title="s")
    job = service.create(
        rule={"kind": "at", "time": "2026-08-19T12:00:00"},
        action={"kind": "session", "session_id": session.session_id, "message": "once"},
        now=datetime(2026, 8, 19, 11, 0, 0),
    )
    first = service.tick(datetime(2026, 8, 19, 12, 1, 0))
    assert first[0]["ok"] is True
    assert service._jobs[job["id"]]["enabled"] is False
    assert service.tick(datetime(2026, 8, 19, 12, 2, 0)) == []


def test_budget_blocks_fire(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.sessions.create(tmp_path, title="s")
    session.budget = {"max_tokens": 10}
    session.usage = {"input_tokens": 8, "output_tokens": 4}
    service.create(
        rule={"kind": "interval", "every": 1, "unit": "minutes"},
        action={"kind": "session", "session_id": session.session_id, "message": "x"},
        now=datetime(2026, 8, 19, 12, 0, 0),
    )
    result = service.tick(datetime(2026, 8, 19, 12, 2, 0))[0]
    assert result["error_code"] == "SCHEDULE_BUDGET"


def test_no_handlers_package() -> None:
    assert not Path("appserver/handlers").exists()
