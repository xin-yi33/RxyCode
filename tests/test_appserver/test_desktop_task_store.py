"""Persistence and lifecycle contract for Desktop task history."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from appserver.sessions import SessionStore
from appserver.task_store import DesktopTaskStore
from appserver.server import AppServer


def test_task_store_persists_rename_trash_restore_and_purge(tmp_path: Path):
    path = tmp_path / "desktop" / "tasks.json"
    store = DesktopTaskStore(path)
    record = store.upsert(
        session_id="s1",
        title="Release audit",
        workspace_root=tmp_path / "workspace",
        model_id="deepseek/deepseek-v4",
        provider_id="deepseek",
    )

    assert record["session_id"] == "s1"
    store.rename("s1", "Payment audit")
    store.trash("s1")
    assert store.list(include_trashed=False) == []
    assert store.list(include_trashed=True)[0]["trashed_at"] is not None

    reloaded = DesktopTaskStore(path)
    reloaded.restore("s1")
    assert reloaded.list()[0]["title"] == "Payment audit"
    reloaded.purge("s1")
    assert reloaded.list(include_trashed=True) == []


def test_second_window_save_keeps_the_first_windows_session(tmp_path: Path):
    path = tmp_path / "tasks.json"
    first = DesktopTaskStore(path)
    first.upsert(session_id="winA", title="A", workspace_root=tmp_path, status="running")
    first.append_event("winA", {"method": "event/message", "params": {"text": "only-A"}})
    second = DesktopTaskStore(path)
    second.upsert(session_id="winB", title="B", workspace_root=tmp_path, status="running")
    first.append_event("winA", {"method": "event/message", "params": {"text": "A-again"}})
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(disk["tasks"]) == {"winA", "winB"}
    assert len(disk["events"]["winA"]) == 2
    assert disk["events"].get("winB", []) == []


def test_session_store_hydrates_persistent_tasks_and_updates_them(tmp_path: Path):
    task_store = DesktopTaskStore(tmp_path / "tasks.json")
    first = SessionStore(task_store=task_store)
    record = first.create(tmp_path / "workspace", title="Investigate outage")
    first.rename(record.session_id, "Outage report")
    first.set_model(record.session_id, "glm/glm-5", "glm")

    second = SessionStore(task_store=DesktopTaskStore(tmp_path / "tasks.json"))
    hydrated = second.get(record.session_id)
    assert hydrated is not None
    assert hydrated.title == "Outage report"
    assert hydrated.model_id == "glm/glm-5"
    assert hydrated.provider_id == "glm"


def test_server_task_lifecycle_routes_keep_workspace_intact(monkeypatch, tmp_path: Path):
    import asyncio
    from unittest.mock import AsyncMock

    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path / "workspace", title="Audit")
    responses: list[object] = []
    monkeypatch.setattr(
        server,
        "_respond",
        AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload)),
    )

    server._sessions.note_user_prompt(record.session_id, "audit the workspace")
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 1))
    assert responses[-1]["sessions"][0]["session_id"] == record.session_id

    asyncio.run(
        server._handle_session_rename(
            {"session_id": record.session_id, "title": "Renamed"}, 2
        )
    )
    asyncio.run(
        server._handle_session_trash({"session_id": record.session_id}, 3)
    )
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 4))
    assert responses[-1]["sessions"] == []
    asyncio.run(
        server._handle_session_restore({"session_id": record.session_id}, 5)
    )
    asyncio.run(
        server._handle_session_purge({"session_id": record.session_id}, 6)
    )
    assert not (tmp_path / "workspace").exists()


def test_server_persists_host_notifications_for_cursor_replay(tmp_path: Path):
    server = AppServer(stub=True)
    server._task_store = DesktopTaskStore(tmp_path / "tasks.json")
    server._sessions = SessionStore(task_store=server._task_store)
    record = server._sessions.create(tmp_path / "workspace", title="Replay audit")

    server._persist_notification({
        "jsonrpc": "2.0",
        "method": "event/tool_end",
        "params": {
            "session_id": record.session_id,
            "call_id": "call-1",
            "ok": True,
            "summary": "read completed",
        },
    })

    events, cursor, gap = server._task_store.events(record.session_id, 0)
    assert cursor == 1
    assert gap is False
    assert events[0]["method"] == "event/tool_end"
    assert events[0]["params"]["call_id"] == "call-1"


def test_server_replay_skips_stream_deltas_and_redacts_tool_secrets(tmp_path: Path):
    server = AppServer(stub=True)
    server._task_store = DesktopTaskStore(tmp_path / "tasks.json")
    server._sessions = SessionStore(task_store=server._task_store)
    record = server._sessions.create(tmp_path / "workspace", title="Safe replay")

    server._persist_notification({
        "method": "event/message_delta",
        "params": {"session_id": record.session_id, "text": "do not persist prompt-like text"},
    })
    server._persist_notification({
        "method": "event/tool_begin",
        "params": {
            "session_id": record.session_id,
            "call_id": "call-secret",
            "tool_name": "bash",
            "arguments": {"command": "curl --api-key sk-live-secret https://example.invalid"},
        },
    })

    events, cursor, gap = server._task_store.events(record.session_id, 0)
    assert cursor == 1
    assert gap is False
    assert len(events) == 1
    serialized = str(events[0])
    assert "do not persist prompt-like text" not in serialized
    assert "sk-live-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_server_replay_keeps_terminal_error_and_task_lifecycle_events(tmp_path: Path):
    server = AppServer(stub=True)
    server._task_store = DesktopTaskStore(tmp_path / "tasks.json")
    server._sessions = SessionStore(task_store=server._task_store)
    record = server._sessions.create(tmp_path / "workspace", title="Failed audit")

    for method, params in (
        ("event/task_started", {"session_id": record.session_id}),
        ("event/error", {"session_id": record.session_id, "message": "provider unavailable"}),
        ("event/task_complete", {"session_id": record.session_id, "ok": False}),
    ):
        server._persist_notification({"method": method, "params": params})

    events, cursor, gap = server._task_store.events(record.session_id, 0)
    assert cursor == 3
    assert gap is False
    assert [event["method"] for event in events] == [
        "event/task_started",
        "event/error",
        "event/task_complete",
    ]


def test_task_store_cursor_is_monotonic_when_protocol_event_has_its_own_seq(tmp_path: Path):
    store = DesktopTaskStore(tmp_path / "tasks.json")
    store.upsert(session_id="s1", title="Replay", workspace_root=tmp_path)

    first = store.append_event("s1", {"method": "event/tool_end", "seq": 42})
    second = store.append_event("s1", {"method": "event/recovery_started", "seq": 1})

    events, cursor, gap = store.events("s1", 0)
    assert (first, second) == (1, 2)
    assert cursor == 2
    assert gap is False
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["protocol_seq"] == 42
    assert events[1]["protocol_seq"] == 1


def test_task_store_migrates_legacy_protocol_seq_into_storage_cursor(tmp_path: Path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({
        "tasks": {},
        "events": {
            "s1": [
                {"seq": 42, "method": "event/tool_end", "params": {}},
                {"seq": 7, "method": "event/final", "params": {}},
            ]
        },
    }), encoding="utf-8")

    store = DesktopTaskStore(path)
    events, cursor, gap = store.events("s1", 0)

    assert cursor == 2
    assert gap is False
    assert [event["seq"] for event in events] == [1, 2]
    assert [event["protocol_seq"] for event in events] == [42, 7]


async def test_buffered_appends_coalesce_into_few_disk_writes(monkeypatch, tmp_path: Path):
    store = DesktopTaskStore(tmp_path / "tasks.json")
    calls = 0
    original = store._save_snapshot

    def counting(snapshot):
        nonlocal calls
        calls += 1
        return original(snapshot)

    monkeypatch.setattr(store, "_save_snapshot", counting)

    for index in range(50):
        store.append_event_buffered("s1", "event/progress", {"i": index})
    await store.flush_pending(timeout=5.0)

    assert calls <= 3
    disk = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert [event["params"]["i"] for event in disk["events"]["s1"]] == list(range(50))


async def test_persist_notification_does_not_block_the_loop(monkeypatch, tmp_path: Path):
    """The 26MB lock+read+merge+fsync save must not run on the appserver loop."""
    server = AppServer(stub=True)
    store = DesktopTaskStore(tmp_path / "tasks.json")
    server._task_store = store
    server._sessions = SessionStore(task_store=store)
    record = server._sessions.create(tmp_path / "workspace", title="Replay audit")

    def slow_save(_snapshot):
        time.sleep(0.1)

    monkeypatch.setattr(store, "_save_snapshot", slow_save)

    started = time.perf_counter()
    server._persist_notification({
        "method": "event/tool_end",
        "params": {
            "session_id": record.session_id,
            "call_id": "call-1",
            "ok": True,
            "summary": "read completed",
        },
    })
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    await store.flush_pending(timeout=5.0)
    events, cursor, gap = store.events(record.session_id, 0)
    assert cursor == 1
    assert gap is False
    assert events[0]["method"] == "event/tool_end"


async def test_flush_pending_matches_direct_append_event_results(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("appserver.task_store._now", lambda: "2026-10-11T00:00:00Z")
    ids = {"n": 0}

    def fake_uuid4():
        ids["n"] += 1
        return SimpleNamespace(hex=f"{ids['n']:032x}")

    monkeypatch.setattr(uuid, "uuid4", fake_uuid4)

    events = [
        ("event/tool_begin", {"call_id": f"call-{i}", "tool_name": "bash"})
        for i in range(30)
    ]
    direct = DesktopTaskStore(tmp_path / "direct.json")
    for method, params in events:
        direct.append_event("s1", {"method": method, "params": dict(params)})

    ids["n"] = 0  # same deterministic event_id sequence for the buffered run
    buffered = DesktopTaskStore(tmp_path / "buffered.json")
    for method, params in events:
        buffered.append_event_buffered("s1", method, dict(params))
    await buffered.flush_pending(timeout=5.0)

    # Raw JSON differs in the legacy protocol_seq migration field (the direct
    # store re-normalizes it on every save; the buffered flush writes once).
    # Compare through the same read path the replay RPC uses.
    direct_view = DesktopTaskStore(tmp_path / "direct.json")
    buffered_view = DesktopTaskStore(tmp_path / "buffered.json")
    assert buffered_view.events("s1", 0) == direct_view.events("s1", 0)
    assert json.loads((tmp_path / "buffered.json").read_text(encoding="utf-8"))["tasks"] == json.loads(
        (tmp_path / "direct.json").read_text(encoding="utf-8")
    )["tasks"]


async def test_two_store_instances_keep_each_others_buffered_events(tmp_path: Path):
    path = tmp_path / "tasks.json"
    first = DesktopTaskStore(path)
    second = DesktopTaskStore(path)

    first.append_event_buffered("winA", "event/progress", {"n": 1})
    second.append_event_buffered("winB", "event/progress", {"n": 2})
    first.append_event_buffered("winA", "event/progress", {"n": 3})
    await first.flush_pending(timeout=5.0)
    await second.flush_pending(timeout=5.0)

    disk = json.loads(path.read_text(encoding="utf-8"))
    assert [event["params"]["n"] for event in disk["events"]["winA"]] == [1, 3]
    assert [event["params"]["n"] for event in disk["events"]["winB"]] == [2]


async def test_purge_during_pending_flush_does_not_resurrect_session(monkeypatch, tmp_path: Path):
    path = tmp_path / "tasks.json"
    store = DesktopTaskStore(path)
    store.upsert(session_id="s1", title="Gone", workspace_root=tmp_path)
    store.append_event("s1", {"method": "event/final", "params": {"text": "old"}})

    original_snapshot = store._event_snapshot
    purged = False

    def racing_snapshot():
        # Interleave the purge between the frozen snapshot and its save.
        nonlocal purged
        snapshot = original_snapshot()
        if not purged:
            purged = True
            store.purge("s1")
        return snapshot

    monkeypatch.setattr(store, "_event_snapshot", racing_snapshot)

    store.append_event_buffered("s2", "event/progress", {"n": 1})
    await store.flush_pending(timeout=5.0)

    disk = json.loads(path.read_text(encoding="utf-8"))
    assert "s1" not in disk["tasks"]
    assert "s1" not in disk["events"]
    assert [event["params"]["n"] for event in disk["events"]["s2"]] == [1]
