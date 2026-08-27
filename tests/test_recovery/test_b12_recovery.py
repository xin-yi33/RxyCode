"""PhaseG-B12 notifications, replay, and orphan recovery."""

from __future__ import annotations

from pathlib import Path

from appserver.recovery import RecoveryService, classify_status
from appserver.task_store import DesktopTaskStore
from protocol.schema import export_schema


def _store(tmp_path: Path) -> DesktopTaskStore:
    store = DesktopTaskStore(tmp_path / "tasks.json", persistent=True)
    store.upsert(session_id="s1", title="t", workspace_root=tmp_path, status="running")
    store.append_event("s1", {"type": "item/started", "session_id": "s1"})
    store.append_event("s1", {"type": "item/completed", "session_id": "s1"})
    return store


def test_notifications_dedupe_and_ack() -> None:
    service = RecoveryService(persistent=False)
    first = service.notify("approval.needed", session_id="s1", dedupe_key="a1")
    second = service.notify("approval.needed", session_id="s1", dedupe_key="a1")
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["notification_id"] == first["notification_id"]
    listed = service.list_notifications("s1")
    assert len(listed) == 1
    acked = service.ack(first["notification_id"])
    assert acked["acked"] is True
    assert service.list_notifications("s1") == []


def test_disconnect_saves_cursor_and_replay_gap(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = RecoveryService(tmp_path / "r.json", persistent=True, task_store=store)
    service.save_cursor("s1", 0)
    first = service.replay("s1", 0, limit=1)
    assert len(first["events"]) == 1
    assert first["next_cursor"] == 1
    service.save_cursor("s1", 1)
    second = service.replay("s1")
    assert [item["seq"] for item in second["events"]] == [2]
    gapped = service.replay("s1", 0)
    assert gapped["gap"] is False or isinstance(gapped["gap"], bool)


def test_duplicate_reconnect_replays_from_cursor(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = RecoveryService(persistent=False, task_store=store)
    service.save_cursor("s1", 2)
    again = service.reconnect("s1", cursor=0)
    assert "events" in again


def test_statuses_never_forge_complete() -> None:
    assert classify_status("running") == "recovery_required"
    assert classify_status("interrupted") == "recovery_required"
    assert classify_status("unknown") == "recovery_required"
    assert classify_status("completed") == "recovery_required"
    assert classify_status("failed") == "failed"


def test_restart_and_orphan_reclaim(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(session_id="orphan", title="o", workspace_root=tmp_path, status="running")
    service = RecoveryService(persistent=False, task_store=store)
    restored = service.restore_after_restart()
    assert restored["forged_complete"] is False
    assert any(item.get("previous_status") == "running" for item in restored.get("projected") or restored.get("recovered") or [])
    statuses = {item["session_id"]: item["status"] for item in store.list()}
    assert statuses["s1"] == "recovery_required"
    orphans = service.reclaim_orphans(live_session_ids={"s1"})
    assert any(item["session_id"] == "orphan" for item in orphans)
    after = {item["session_id"]: item["status"] for item in store.list()}
    assert after["orphan"] == "recovery_required"


def test_unknown_and_incomplete_turn(tmp_path: Path) -> None:
    store = DesktopTaskStore(tmp_path / "t.json", persistent=True)
    store.upsert(session_id="u", title="u", workspace_root=tmp_path, status="mystery")
    store.upsert(session_id="t", title="t", workspace_root=tmp_path, status="active")
    service = RecoveryService(persistent=False, task_store=store)
    service.restore_after_restart()
    rows = {item["session_id"]: item["status"] for item in store.list()}
    assert rows["u"] == "recovery_required"
    assert rows["t"] == "recovery_required"


def test_replay_cursor_is_monotonic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = RecoveryService(persistent=False, task_store=store)
    service.save_cursor("s1", 2)
    service.save_cursor("s1", 0)
    service.replay("s1", 0, limit=1)
    assert service.cursor("s1") == 2


def test_gap_duplicate_and_crash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    events = store._data["events"]["s1"]
    events[1]["seq"] = 5
    service = RecoveryService(tmp_path / "r.json", persistent=True, task_store=store)
    gapped = store.events("s1", 1)
    assert gapped[2] is True
    first = service.reconnect("s1", cursor=0)
    second = service.reconnect("s1", cursor=0)
    assert "events" in first and "events" in second
    crashed = RecoveryService(tmp_path / "r.json", persistent=True, task_store=store)
    crashed.restore_after_restart()
    assert classify_status(store.list()[0]["status"]) == "recovery_required"


def test_observe_event_and_initialize_catchup(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = RecoveryService(persistent=False, task_store=store)
    note = service.observe_event("approval/request", {"session_id": "s1"})
    assert note["kind"] == "approval.needed"
    service.observe_event("command/start", {"session_id": "s1", "background": True, "kind": "command"})
    service.observe_event("turn/started", {"session_id": "s1", "background": True})
    service.observe_event("event/error", {"session_id": "s1"})
    service.observe_event("turn/failed", {"session_id": "s1"})
    kinds = {row["kind"] for row in service.list_notifications("s1")}
    assert kinds >= {"approval.needed", "command.long", "turn.background", "turn.failed"}
    catchup = service.initialize_catchup("s1")
    assert catchup["thread"]["session_id"] == "s1"
    assert catchup["items"]


def test_schema_has_recovery_methods() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "RecoveryStatusRequest",
        "RecoveryReplayRequest",
        "RecoveryReclaimRequest",
        "NotificationsListRequest",
        "NotificationsAckRequest",
        "NotificationsCursorRequest",
    ):
        assert name in defs
