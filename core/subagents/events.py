"""ChildSessionEvent, persistence, and recovery.

B12 · Lets CLI, Desktop, and future LinkAgent observe, re-read, and recover
child sessions in real time.

Event invariants:
  - monotonic sequence numbers with gap detection
  - idempotent duplicates
  - terminal event persisted BEFORE lease release
  - recovery never re-runs a completed child
  - clients may subscribe to a single child subtree
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from protocol.subagents import ChildStatus


# ---------------------------------------------------------------------------
# Event names (frozen)
# ---------------------------------------------------------------------------

EVENT_CREATED = "child_session/created"
EVENT_QUEUED = "child_session/queued"
EVENT_STARTED = "child_session/started"
EVENT_CONTEXT_READY = "child_session/context_ready"
EVENT_TOOL_CALL = "child_session/tool_call"
EVENT_APPROVAL_REQUIRED = "child_session/approval_required"
EVENT_PROGRESS = "child_session/progress"
EVENT_PARTIAL_RESULT = "child_session/partial_result"
EVENT_COMPLETED = "child_session/completed"
EVENT_FAILED = "child_session/failed"
EVENT_CANCELLED = "child_session/cancelled"
EVENT_RECOVERED = "child_session/recovered"

_ALL_EVENTS: tuple[str, ...] = (
    EVENT_CREATED, EVENT_QUEUED, EVENT_STARTED, EVENT_CONTEXT_READY,
    EVENT_TOOL_CALL, EVENT_APPROVAL_REQUIRED, EVENT_PROGRESS,
    EVENT_PARTIAL_RESULT, EVENT_COMPLETED, EVENT_FAILED, EVENT_CANCELLED,
    EVENT_RECOVERED,
)

# Terminal events (persisted before lease release)
TERMINAL_EVENTS: frozenset[str] = frozenset({
    EVENT_COMPLETED, EVENT_FAILED, EVENT_CANCELLED,
    "child_session/timed_out", "child_session/denied",
})


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------

@dataclass
class ChildSessionEvent:
    """A single child session event with full trace context."""

    event_name: str
    session_id: str
    parent_session_id: str
    request_id: str = ""
    seq: int = 0
    timestamp: float = field(default_factory=time.time)
    definition_version: str = ""
    redaction_metadata: str = ""          # e.g. "redacted:[api_key]"
    payload: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Event store
# ---------------------------------------------------------------------------

@dataclass
class EventStore:
    """In-memory event log with optional JSON file persistence.

    Assigns monotonic sequence numbers; clients read from a cursor and
    can detect gaps.
    """

    persist_dir: Path | None = None
    _events: list[ChildSessionEvent] = field(default_factory=list)
    _next_seq: int = field(default=1, init=False)
    _by_id: dict[str, ChildSessionEvent] = field(default_factory=dict)

    def __post_init__(self):
        if self.persist_dir is not None:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted()

    # -- writing -------------------------------------------------------------

    def append(self, event: ChildSessionEvent) -> ChildSessionEvent:
        """Append an event, assigning the next monotonic sequence number.

        Idempotent: an event with the same event_id is ignored.
        """
        if event.event_id in self._by_id:
            return self._by_id[event.event_id]

        event.seq = self._next_seq
        self._next_seq += 1

        self._events.append(event)
        self._by_id[event.event_id] = event
        self._persist(event)
        return event

    # -- reading -------------------------------------------------------------

    def events_from(self, cursor: int) -> list[ChildSessionEvent]:
        """Return events with seq > cursor (for catch-up after disconnect)."""
        return [e for e in self._events if e.seq > cursor]

    def events_for_session(self, session_id: str) -> list[ChildSessionEvent]:
        """Return all events for one session, in seq order."""
        return [e for e in self._events if e.session_id == session_id]

    def events_for_subtree(self, session_ids: Sequence[str]) -> list[ChildSessionEvent]:
        """Return events for a set of session ids (a subtree)."""
        id_set = set(session_ids)
        return [e for e in self._events if e.session_id in id_set]

    def latest_cursor(self) -> int:
        """Return the highest assigned seq (0 if empty)."""
        return self._next_seq - 1

    def detect_gaps(self, from_seq: int, to_seq: int) -> list[int]:
        """Return missing seq numbers in (from_seq, to_seq]."""
        present = {e.seq for e in self._events if from_seq < e.seq <= to_seq}
        return [s for s in range(from_seq + 1, to_seq + 1) if s not in present]

    # -- terminal check ------------------------------------------------------

    def has_terminal_event(self, session_id: str) -> bool:
        """Return True if a session already has a persisted terminal event."""
        return any(
            e.session_id == session_id and e.event_name in TERMINAL_EVENTS
            for e in self._events
        )

    def terminal_status_for(self, session_id: str) -> str | None:
        """Return the terminal event name for a session, or None."""
        for e in reversed(self._events):
            if e.session_id == session_id and e.event_name in TERMINAL_EVENTS:
                return e.event_name
        return None

    # -- persistence ---------------------------------------------------------

    def _persist(self, event: ChildSessionEvent) -> None:
        if self.persist_dir is None:
            return
        path = self._path_for(event.session_id)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def _path_for(self, session_id: str) -> Path:
        return self.persist_dir / f"{session_id}.jsonl"

    def _load_persisted(self) -> None:
        """Replay persisted events on startup (crash recovery)."""
        if self.persist_dir is None:
            return
        for path in sorted(self.persist_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    event = ChildSessionEvent(**data)
                    # Preserve original seq; don't reassign
                    self._events.append(event)
                    self._by_id[event.event_id] = event
                    if event.seq >= self._next_seq:
                        self._next_seq = event.seq + 1
                except (json.JSONDecodeError, TypeError):
                    continue


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

Subscriber = Callable[[ChildSessionEvent], None]


@dataclass
class EventBus:
    """Subscribes consumers to events for a session or a subtree.

    Subscribers can be filtered by:
      - session_id (single child)
      - root_session_id + session_ids (a subtree)
    """

    store: EventStore = field(default_factory=EventStore)
    _subscribers: list[tuple[set[str], Subscriber]] = field(default_factory=list)

    def subscribe(self, session_ids: Sequence[str], subscriber: Subscriber) -> Callable[[], None]:
        """Subscribe to events for specific session ids; returns an unsubscribe fn."""
        ids = set(session_ids)
        entry = (ids, subscriber)
        self._subscribers.append(entry)

        def unsubscribe() -> None:
            if entry in self._subscribers:
                self._subscribers.remove(entry)

        return unsubscribe

    def publish(self, event: ChildSessionEvent) -> None:
        """Publish an event to matching subscribers (after store append)."""
        for ids, subscriber in list(self._subscribers):
            if event.session_id in ids:
                try:
                    subscriber(event)
                except Exception:
                    # A failing subscriber must not break delivery to others
                    continue

    def replay(self, session_ids: Sequence[str], cursor: int = 0) -> list[ChildSessionEvent]:
        """Replay events for a subtree from a cursor (catch-up)."""
        id_set = set(session_ids)
        return [
            e for e in self.store.events_from(cursor)
            if e.session_id in id_set
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_event(
    event_name: str,
    session_id: str,
    parent_session_id: str,
    *,
    request_id: str = "",
    definition_version: str = "",
    redaction_metadata: str = "",
    payload: dict | None = None,
) -> ChildSessionEvent:
    """Convenience factory for ChildSessionEvent."""
    return ChildSessionEvent(
        event_name=event_name,
        session_id=session_id,
        parent_session_id=parent_session_id,
        request_id=request_id,
        definition_version=definition_version,
        redaction_metadata=redaction_metadata,
        payload=payload or {},
    )


def terminal_event_name_for(status: ChildStatus) -> str:
    """Map a terminal ChildStatus to its frozen event name."""
    mapping = {
        ChildStatus.COMPLETED: EVENT_COMPLETED,
        ChildStatus.FAILED: EVENT_FAILED,
        ChildStatus.CANCELLED: EVENT_CANCELLED,
        ChildStatus.TIMED_OUT: "child_session/timed_out",
        ChildStatus.DENIED: "child_session/denied",
    }
    return mapping.get(status, EVENT_FAILED)
