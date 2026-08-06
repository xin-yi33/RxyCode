"""Child Session lifecycle, state machine, and parent/child tree.

B4 · Implements the session state machine:
    CREATED → QUEUED → RUNNING → FINALIZING → TERMINATED

with terminal states: COMPLETED, FAILED, CANCELLED, DENIED, TIMED_OUT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from protocol.subagents import (
    AgentDefinition,
    ChildStatus,
    EffectiveTaskPolicy,
    TaskRequest,
    TaskResult,
    TriggerKind,
)


# ---------------------------------------------------------------------------
# Session metadata (persisted)
# ---------------------------------------------------------------------------

@dataclass
class ChildSession:
    """Runtime representation of a child session.

    Tracks lifecycle state, lineage, policy snapshot, and result pointer.
    """

    session_id: str = field(default_factory=lambda: str(uuid4()))
    parent_session_id: str = ""
    root_session_id: str = ""

    # Identity
    agent_id: str = ""
    trigger: TriggerKind = TriggerKind.AUTOMATIC
    definition_version: str = ""         # Hash or version of AgentDefinition

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    terminal_at: datetime | None = None

    # Policy snapshot (frozen at creation time)
    policy: EffectiveTaskPolicy = field(default_factory=EffectiveTaskPolicy)

    # Event cursor for recovery
    event_cursor: int = 0

    # Result pointer (set when terminal)
    result: TaskResult | None = None

    # Status
    _status: ChildStatus = field(default=ChildStatus.CREATED, repr=False)

    # Cancellation callback (set by runtime)
    _cancel_callback: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def status(self) -> ChildStatus:
        return self._status

    @property
    def is_terminal(self) -> bool:
        """Has this session reached a terminal state?"""
        return self._status in _TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        """Is this session still running (not terminal, not cancelled)?"""
        return self._status in _ACTIVE_STATES


# ---------------------------------------------------------------------------
# State groups
# ---------------------------------------------------------------------------

_TERMINAL_STATES: frozenset[ChildStatus] = frozenset({
    ChildStatus.COMPLETED,
    ChildStatus.FAILED,
    ChildStatus.CANCELLED,
    ChildStatus.DENIED,
    ChildStatus.TIMED_OUT,
})

_ACTIVE_STATES: frozenset[ChildStatus] = frozenset({
    ChildStatus.CREATED,
    ChildStatus.QUEUED,
    ChildStatus.RUNNING,
    ChildStatus.FINALIZING,
})

# Valid state transitions
_VALID_TRANSITIONS: dict[ChildStatus, frozenset[ChildStatus]] = {
    ChildStatus.CREATED: frozenset({ChildStatus.QUEUED, ChildStatus.CANCELLED, ChildStatus.DENIED}),
    ChildStatus.QUEUED: frozenset({ChildStatus.RUNNING, ChildStatus.CANCELLED}),
    ChildStatus.RUNNING: frozenset({
        ChildStatus.FINALIZING,
        ChildStatus.COMPLETED,
        ChildStatus.FAILED,
        ChildStatus.CANCELLED,
        ChildStatus.TIMED_OUT,
    }),
    ChildStatus.FINALIZING: frozenset({
        ChildStatus.COMPLETED,
        ChildStatus.FAILED,
        ChildStatus.CANCELLED,
        ChildStatus.TIMED_OUT,
    }),
    # Terminal states — no outgoing transitions (idempotent)
    ChildStatus.COMPLETED: frozenset(),
    ChildStatus.FAILED: frozenset(),
    ChildStatus.CANCELLED: frozenset(),
    ChildStatus.DENIED: frozenset(),
    ChildStatus.TIMED_OUT: frozenset(),
}


# ---------------------------------------------------------------------------
# State machine errors
# ---------------------------------------------------------------------------

class InvalidStateTransition(ValueError):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, session_id: str, current: ChildStatus, target: ChildStatus):
        super().__init__(
            f"Cannot transition session '{session_id}' "
            f"from '{current.value}' to '{target.value}'"
        )
        self.session_id = session_id
        self.current = current
        self.target = target


class SessionNotFound(KeyError):
    """Raised when a session id is not found in the tree."""

    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def transition(session: ChildSession, target: ChildStatus) -> None:
    """Attempt to transition a session to a new status.

    Raises InvalidStateTransition if the transition is not allowed.
    Terminal→terminal transitions are silently idempotent (no-op).
    """
    current = session._status
    allowed = _VALID_TRANSITIONS.get(current, frozenset())

    if target in allowed:
        session._status = target
        if target in _TERMINAL_STATES:
            session.terminal_at = datetime.now(timezone.utc)
        elif target == ChildStatus.RUNNING:
            session.started_at = datetime.now(timezone.utc)
        return

    # Terminal → same terminal is idempotent
    if current in _TERMINAL_STATES and current == target:
        return

    raise InvalidStateTransition(session.session_id, current, target)


# ---------------------------------------------------------------------------
# Session tree
# ---------------------------------------------------------------------------

@dataclass
class SessionTree:
    """Parent/child session tree for a single root (Primary) session.

    Manages the full lifecycle of all child sessions under one Primary,
    including recursive cancellation.
    """

    root_session_id: str
    _sessions: dict[str, ChildSession] = field(default_factory=dict)
    _children: dict[str, list[str]] = field(default_factory=dict)  # parent → [child ids]

    # -- registration --------------------------------------------------------

    def add(self, session: ChildSession) -> None:
        """Register a child session in the tree."""
        if session.session_id in self._sessions:
            raise ValueError(f"Session already exists: {session.session_id}")

        self._sessions[session.session_id] = session

        parent = session.parent_session_id or self.root_session_id
        self._children.setdefault(parent, []).append(session.session_id)

    # -- lookup --------------------------------------------------------------

    def get(self, session_id: str) -> ChildSession:
        """Return a session by id, raising SessionNotFound if missing."""
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        return self._sessions[session_id]

    def get_children(self, session_id: str) -> list[ChildSession]:
        """Return direct children of a session."""
        child_ids = self._children.get(session_id, [])
        return [self._sessions[cid] for cid in child_ids if cid in self._sessions]

    def get_active_children(self, session_id: str) -> list[ChildSession]:
        """Return children that are not yet terminal."""
        return [c for c in self.get_children(session_id) if c.is_active]

    # -- cancellation --------------------------------------------------------

    def cancel_session(self, session_id: str) -> None:
        """Cancel a session and all its descendants recursively."""
        session = self.get(session_id)

        # Cancel descendants first
        for child in self.get_children(session_id):
            self.cancel_session(child.session_id)

        # Then cancel this session (if not already terminal)
        if session.is_active:
            try:
                transition(session, ChildStatus.CANCELLED)
            except InvalidStateTransition:
                pass  # Already terminal — idempotent

            # Invoke cancellation callback if set
            if session._cancel_callback is not None:
                try:
                    session._cancel_callback()
                except Exception:
                    pass  # Callback failures must not block cancellation propagation

    def cancel_all(self) -> None:
        """Cancel all active sessions under this root."""
        for child in self.get_children(self.root_session_id):
            self.cancel_session(child.session_id)

    # -- iteration -----------------------------------------------------------

    def list_all(self) -> list[ChildSession]:
        """Return all sessions in creation order."""
        return sorted(self._sessions.values(), key=lambda s: s.created_at)

    def list_terminal(self) -> list[ChildSession]:
        """Return all terminal sessions."""
        return [s for s in self._sessions.values() if s.is_terminal]

    def list_active(self) -> list[ChildSession]:
        """Return all active (non-terminal) sessions."""
        return [s for s in self._sessions.values() if s.is_active]

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def create_child_session(
    request: TaskRequest,
    policy: EffectiveTaskPolicy,
    *,
    definition: AgentDefinition | None = None,
) -> ChildSession:
    """Create a new ChildSession from a TaskRequest and computed policy.

    The session starts in CREATED state. Caller must transition through
    QUEUED → RUNNING → FINALIZING → TERMINAL.
    """
    session = ChildSession(
        session_id=f"ses_child_{uuid4().hex[:12]}",
        parent_session_id=request.parent_session_id,
        root_session_id=request.parent_session_id,  # Simplified; manager sets actual root
        agent_id=request.agent_id,
        trigger=request.trigger,
        definition_version=_definition_fingerprint(definition),
        policy=policy,
    )
    return session


def _definition_fingerprint(definition: AgentDefinition | None) -> str:
    """Produce a short version string for an AgentDefinition."""
    if definition is None:
        return "unknown"
    # Use a stable representation: id + hash of key fields
    import hashlib

    key = f"{definition.id}:{definition.mode.value}:{definition.steps}:{definition.subagent_depth}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]
