"""B12 · ChildSessionEvent, persistence, and recovery tests."""

from __future__ import annotations

import json
import pytest

from protocol.subagents import ChildStatus
from core.subagents.events import (
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_STARTED,
    ChildSessionEvent,
    EventBus,
    EventStore,
    build_event,
    terminal_event_name_for,
)


def _ev(name: str, session_id: str = "child_1", parent: str = "primary_1") -> ChildSessionEvent:
    return build_event(name, session_id, parent)


# ============================================================================
# Event construction and metadata
# ============================================================================

class TestEventConstruction:
    """Each event carries full trace metadata."""

    def test_event_has_required_fields(self):
        event = build_event(
            EVENT_CREATED,
            "child_1",
            "primary_1",
            request_id="req_1",
            definition_version="def-v1",
            redaction_metadata="redacted:[api_key]",
            payload={"agent_id": "explore"},
        )
        assert event.event_id != ""
        assert event.session_id == "child_1"
        assert event.parent_session_id == "primary_1"
        assert event.request_id == "req_1"
        assert event.definition_version == "def-v1"
        assert event.redaction_metadata == "redacted:[api_key]"
        assert event.payload == {"agent_id": "explore"}
        assert event.timestamp > 0

    def test_to_dict(self):
        event = build_event(EVENT_CREATED, "child_1", "primary_1")
        d = event.to_dict()
        assert d["event_name"] == EVENT_CREATED
        assert d["session_id"] == "child_1"
        assert d["parent_session_id"] == "primary_1"

    def test_terminal_event_name_mapping(self):
        assert terminal_event_name_for(ChildStatus.COMPLETED) == EVENT_COMPLETED
        assert terminal_event_name_for(ChildStatus.FAILED) == "child_session/failed"
        assert terminal_event_name_for(ChildStatus.CANCELLED) == "child_session/cancelled"
        assert terminal_event_name_for(ChildStatus.TIMED_OUT) == "child_session/timed_out"
        assert terminal_event_name_for(ChildStatus.DENIED) == "child_session/denied"


# ============================================================================
# Event store — sequence and gap detection
# ============================================================================

class TestEventStore:
    """Monotonic seq, gap detection, and terminal checks."""

    def test_monotonic_sequence(self):
        store = EventStore()
        e1 = store.append(_ev(EVENT_CREATED))
        e2 = store.append(_ev(EVENT_STARTED))
        e3 = store.append(_ev(EVENT_COMPLETED))
        assert e1.seq == 1
        assert e2.seq == 2
        assert e3.seq == 3
        assert store.latest_cursor() == 3

    def test_duplicate_event_idempotent(self):
        store = EventStore()
        event = build_event(EVENT_CREATED, "child_1", "primary_1")
        first = store.append(event)
        second = store.append(event)  # Same event_id → ignored
        assert second.event_id == first.event_id
        assert second.seq == first.seq
        assert len(store._events) == 1
        assert store.latest_cursor() == 1

    def test_events_from_cursor(self):
        store = EventStore()
        store.append(_ev(EVENT_CREATED))
        store.append(_ev(EVENT_STARTED))
        store.append(_ev(EVENT_COMPLETED))
        after_1 = store.events_from(1)
        assert len(after_1) == 2
        assert after_1[0].seq == 2
        assert after_1[1].seq == 3

    def test_detect_gaps(self):
        store = EventStore()
        store.append(_ev(EVENT_CREATED))   # seq 1
        store.append(_ev(EVENT_STARTED))   # seq 2
        # simulate gap by adding a manual seq-4 event
        e4 = _ev(EVENT_COMPLETED)
        e4.seq = 4
        store._events.append(e4)
        store._by_id[e4.event_id] = e4
        store._next_seq = 5

        gaps = store.detect_gaps(1, 4)
        assert gaps == [3]

    def test_terminal_check(self):
        store = EventStore()
        store.append(_ev(EVENT_CREATED))
        assert not store.has_terminal_event("child_1")

        store.append(_ev(EVENT_COMPLETED))
        assert store.has_terminal_event("child_1")
        assert store.terminal_status_for("child_1") == EVENT_COMPLETED

    def test_events_for_session(self):
        store = EventStore()
        store.append(_ev(EVENT_CREATED, "a"))
        store.append(_ev(EVENT_STARTED, "b"))
        store.append(_ev(EVENT_COMPLETED, "a"))
        a_events = store.events_for_session("a")
        assert len(a_events) == 2
        assert all(e.session_id == "a" for e in a_events)


# ============================================================================
# Persistence and recovery
# ============================================================================

class TestPersistence:
    """Events persist to disk and replay after restart."""

    def test_persist_and_reload(self, tmp_path):
        store = EventStore(persist_dir=tmp_path)
        store.append(_ev(EVENT_CREATED, "child_1"))
        store.append(_ev(EVENT_STARTED, "child_1"))
        store.append(_ev(EVENT_COMPLETED, "child_1"))

        # Simulate restart
        store2 = EventStore(persist_dir=tmp_path)
        assert len(store2._events) == 3
        assert store2.latest_cursor() == 3

    def test_persist_preserves_sequence(self, tmp_path):
        store = EventStore(persist_dir=tmp_path)
        store.append(_ev(EVENT_CREATED, "c1"))
        store.append(_ev(EVENT_STARTED, "c1"))

        store2 = EventStore(persist_dir=tmp_path)
        new = store2.append(_ev(EVENT_COMPLETED, "c1"))
        assert new.seq == 3  # continues after reload

    def test_terminal_event_available_after_restart(self, tmp_path):
        """Recovery can see a completed child's terminal event."""
        store = EventStore(persist_dir=tmp_path)
        store.append(_ev(EVENT_CREATED, "child_9"))
        store.append(_ev(EVENT_COMPLETED, "child_9"))

        store2 = EventStore(persist_dir=tmp_path)
        assert store2.has_terminal_event("child_9")
        assert store2.terminal_status_for("child_9") == EVENT_COMPLETED

    def test_recovery_never_reruns_completed(self, tmp_path):
        """A completed child is not re-run after recovery."""
        store = EventStore(persist_dir=tmp_path)
        store.append(_ev(EVENT_COMPLETED, "child_5"))

        store2 = EventStore(persist_dir=tmp_path)
        # Recovery logic: if terminal exists, don't schedule a new run
        assert store2.has_terminal_event("child_5")
        assert store2.terminal_status_for("child_5") == EVENT_COMPLETED

    def test_corrupt_line_skipped(self, tmp_path):
        """Corrupt persisted lines don't crash recovery."""
        (tmp_path / "child_x.jsonl").write_text(
            "{not valid json}\n",
            encoding="utf-8",
        )
        store = EventStore(persist_dir=tmp_path)  # Should not raise
        assert len(store._events) == 0


# ============================================================================
# Event bus — subscription and replay
# ============================================================================

class TestEventBus:
    """Subscriber delivery, filtering, and cursor replay."""

    def test_subscriber_receives_events(self):
        bus = EventBus()
        received = []
        bus.subscribe(["child_1"], lambda e: received.append(e.event_name))

        bus.store.append(_ev(EVENT_CREATED, "child_1"))
        bus.publish(bus.store._events[-1])
        bus.store.append(_ev(EVENT_STARTED, "child_2"))
        bus.publish(bus.store._events[-1])

        assert received == [EVENT_CREATED]

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        unsub = bus.subscribe(["child_1"], lambda e: received.append(e.event_name))
        unsub()

        bus.store.append(_ev(EVENT_CREATED, "child_1"))
        bus.publish(bus.store._events[-1])
        assert received == []

    def test_replay_from_cursor(self):
        bus = EventBus()
        bus.store.append(_ev(EVENT_CREATED, "child_1"))
        bus.store.append(_ev(EVENT_STARTED, "child_2"))
        bus.store.append(_ev(EVENT_COMPLETED, "child_1"))

        replayed = bus.replay(["child_1"], cursor=0)
        assert len(replayed) == 2  # created + completed for child_1
        assert all(e.session_id == "child_1" for e in replayed)

    def test_replay_subtree(self):
        bus = EventBus()
        bus.store.append(_ev(EVENT_CREATED, "child_1"))
        bus.store.append(_ev(EVENT_CREATED, "child_1a", parent="child_1"))
        bus.store.append(_ev(EVENT_CREATED, "other_child"))

        subtree = bus.replay(["child_1", "child_1a"])
        assert len(subtree) == 2
        assert {e.session_id for e in subtree} == {"child_1", "child_1a"}

    def test_failing_subscriber_does_not_break_others(self):
        bus = EventBus()
        received = []

        def bad(e):
            raise RuntimeError("boom")

        bus.subscribe(["child_1"], bad)
        bus.subscribe(["child_1"], lambda e: received.append(e.event_name))

        bus.store.append(_ev(EVENT_CREATED, "child_1"))
        bus.publish(bus.store._events[-1])

        assert received == [EVENT_CREATED]
