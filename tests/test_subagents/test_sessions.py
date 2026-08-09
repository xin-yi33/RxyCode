"""B4 · Child Session lifecycle and state machine tests."""

from __future__ import annotations

import pytest

from protocol.subagents import (
    ChildStatus,
    EffectiveTaskPolicy,
    TaskRequest,
    TriggerKind,
)
from core.subagents.sessions import (
    ChildSession,
    InvalidStateTransition,
    SessionNotFound,
    SessionTree,
    create_child_session,
    transition,
)


# ============================================================================
# State machine
# ============================================================================

class TestStateMachine:
    """The CREATED→QUEUED→RUNNING→FINALIZING→TERMINATED state machine."""

    def test_initial_state_is_created(self):
        session = ChildSession()
        assert session.status == ChildStatus.CREATED
        assert not session.is_terminal
        assert session.is_active

    def test_created_to_queued(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        assert session.status == ChildStatus.QUEUED

    def test_created_to_cancelled(self):
        session = ChildSession()
        transition(session, ChildStatus.CANCELLED)
        assert session.status == ChildStatus.CANCELLED
        assert session.is_terminal

    def test_created_to_denied(self):
        session = ChildSession()
        transition(session, ChildStatus.DENIED)
        assert session.status == ChildStatus.DENIED
        assert session.is_terminal

    def test_queued_to_running(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        assert session.status == ChildStatus.RUNNING
        assert session.started_at is not None

    def test_running_to_completed(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.COMPLETED)
        assert session.status == ChildStatus.COMPLETED
        assert session.is_terminal
        assert session.terminal_at is not None

    def test_running_to_failed(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.FAILED)
        assert session.status == ChildStatus.FAILED

    def test_running_to_timed_out(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.TIMED_OUT)
        assert session.status == ChildStatus.TIMED_OUT

    def test_running_to_cancelled(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.CANCELLED)
        assert session.status == ChildStatus.CANCELLED

    def test_running_to_finalizing_then_completed(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.FINALIZING)
        assert session.status == ChildStatus.FINALIZING
        transition(session, ChildStatus.COMPLETED)
        assert session.status == ChildStatus.COMPLETED

    def test_created_directly_to_completed_not_allowed(self):
        session = ChildSession()
        with pytest.raises(InvalidStateTransition):
            transition(session, ChildStatus.COMPLETED)


# ============================================================================
# Terminal idempotency
# ============================================================================

class TestTerminalIdempotency:
    """Terminal states must be idempotent — no duplicate transitions."""

    def test_completed_to_completed_is_noop(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.COMPLETED)
        # Second transition to same terminal is idempotent
        transition(session, ChildStatus.COMPLETED)  # Does not raise
        assert session.status == ChildStatus.COMPLETED

    def test_completed_cannot_transition_to_failed(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.COMPLETED)
        with pytest.raises(InvalidStateTransition):
            transition(session, ChildStatus.FAILED)

    def test_failed_cannot_transition_to_completed(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.FAILED)
        with pytest.raises(InvalidStateTransition):
            transition(session, ChildStatus.COMPLETED)

    def test_cancelled_to_cancelled_is_idempotent(self):
        session = ChildSession()
        transition(session, ChildStatus.CANCELLED)
        transition(session, ChildStatus.CANCELLED)  # No-op
        assert session.status == ChildStatus.CANCELLED

    def test_denied_to_denied_is_idempotent(self):
        session = ChildSession()
        transition(session, ChildStatus.DENIED)
        transition(session, ChildStatus.DENIED)  # No-op
        assert session.status == ChildStatus.DENIED

    def test_timed_out_to_timed_out_is_idempotent(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        transition(session, ChildStatus.RUNNING)
        transition(session, ChildStatus.TIMED_OUT)
        transition(session, ChildStatus.TIMED_OUT)  # No-op
        assert session.status == ChildStatus.TIMED_OUT


# ============================================================================
# Session creation
# ============================================================================

class TestSessionCreation:
    """ChildSession factory and metadata."""

    def test_create_child_session(self):
        request = TaskRequest(
            parent_session_id="ses_primary_1",
            agent_id="explore",
            prompt="Find auth files",
            trigger=TriggerKind.AUTOMATIC,
        )
        policy = EffectiveTaskPolicy()
        session = create_child_session(request, policy)

        assert session.agent_id == "explore"
        assert session.parent_session_id == "ses_primary_1"
        assert session.trigger == TriggerKind.AUTOMATIC
        assert session.status == ChildStatus.CREATED
        assert session.created_at is not None
        assert session.started_at is None
        assert session.terminal_at is None
        assert session.result is None

    def test_session_ids_are_unique(self):
        request = TaskRequest(parent_session_id="p1", agent_id="a1", prompt="t")
        policy = EffectiveTaskPolicy()
        s1 = create_child_session(request, policy)
        s2 = create_child_session(request, policy)
        assert s1.session_id != s2.session_id


# ============================================================================
# Session tree
# ============================================================================

class TestSessionTree:
    """Parent/child session tree management."""

    def test_add_and_get(self):
        tree = SessionTree(root_session_id="root")
        session = ChildSession(session_id="child1", parent_session_id="root")
        tree.add(session)
        assert tree.get("child1") is session

    def test_get_missing_raises(self):
        tree = SessionTree(root_session_id="root")
        with pytest.raises(SessionNotFound):
            tree.get("nonexistent")

    def test_get_children(self):
        tree = SessionTree(root_session_id="root")
        c1 = ChildSession(session_id="c1", parent_session_id="root")
        c2 = ChildSession(session_id="c2", parent_session_id="root")
        tree.add(c1)
        tree.add(c2)
        children = tree.get_children("root")
        assert len(children) == 2
        assert {c.session_id for c in children} == {"c1", "c2"}

    def test_get_active_children(self):
        tree = SessionTree(root_session_id="root")
        c1 = ChildSession(session_id="c1", parent_session_id="root")
        c2 = ChildSession(session_id="c2", parent_session_id="root")
        tree.add(c1)
        tree.add(c2)

        # Both start active
        assert len(tree.get_active_children("root")) == 2

        # Make c1 terminal
        transition(c1, ChildStatus.CANCELLED)
        active = tree.get_active_children("root")
        assert len(active) == 1
        assert active[0].session_id == "c2"

    def test_duplicate_add_raises(self):
        tree = SessionTree(root_session_id="root")
        s = ChildSession(session_id="child1", parent_session_id="root")
        tree.add(s)
        with pytest.raises(ValueError, match="already exists"):
            tree.add(s)


# ============================================================================
# Cancellation propagation
# ============================================================================

class TestCancellationPropagation:
    """Parent cancellation must recursively cancel descendants."""

    def test_cancel_single_child(self):
        tree = SessionTree(root_session_id="root")
        child = ChildSession(session_id="child1", parent_session_id="root")
        tree.add(child)
        transition(child, ChildStatus.QUEUED)
        transition(child, ChildStatus.RUNNING)

        tree.cancel_session("child1")
        assert child.status == ChildStatus.CANCELLED

    def test_cancel_already_terminal_is_noop(self):
        tree = SessionTree(root_session_id="root")
        child = ChildSession(session_id="child1", parent_session_id="root")
        tree.add(child)
        transition(child, ChildStatus.QUEUED)
        transition(child, ChildStatus.RUNNING)
        transition(child, ChildStatus.COMPLETED)

        tree.cancel_session("child1")  # Should not raise
        assert child.status == ChildStatus.COMPLETED

    def test_cancel_parent_cancels_children(self):
        tree = SessionTree(root_session_id="root")
        parent = ChildSession(session_id="parent", parent_session_id="root")
        child = ChildSession(session_id="child", parent_session_id="parent")
        tree.add(parent)
        tree.add(child)
        transition(parent, ChildStatus.QUEUED)
        transition(parent, ChildStatus.RUNNING)
        transition(child, ChildStatus.QUEUED)
        transition(child, ChildStatus.RUNNING)

        tree.cancel_session("parent")
        assert parent.status == ChildStatus.CANCELLED
        assert child.status == ChildStatus.CANCELLED

    def test_cancel_all(self):
        tree = SessionTree(root_session_id="root")
        for i in range(3):
            s = ChildSession(session_id=f"child{i}", parent_session_id="root")
            tree.add(s)
            transition(s, ChildStatus.QUEUED)
            transition(s, ChildStatus.RUNNING)

        tree.cancel_all()
        assert len(tree.list_active()) == 0
        assert len(tree.list_terminal()) == 3

    def test_cancel_deep_tree(self):
        """Cancel cascades through multi-level tree."""
        tree = SessionTree(root_session_id="root")
        c1 = ChildSession(session_id="c1", parent_session_id="root")
        c2 = ChildSession(session_id="c2", parent_session_id="c1")
        c3 = ChildSession(session_id="c3", parent_session_id="c2")
        for s in (c1, c2, c3):
            tree.add(s)
            transition(s, ChildStatus.QUEUED)
            transition(s, ChildStatus.RUNNING)

        tree.cancel_session("c1")
        for s in (c1, c2, c3):
            assert s.status == ChildStatus.CANCELLED

    def test_cancel_callback_invoked(self):
        tree = SessionTree(root_session_id="root")
        called = []

        child = ChildSession(session_id="child1", parent_session_id="root")
        child._cancel_callback = lambda: called.append(True)
        tree.add(child)
        transition(child, ChildStatus.QUEUED)
        transition(child, ChildStatus.RUNNING)

        tree.cancel_session("child1")
        assert len(called) == 1
        assert child.status == ChildStatus.CANCELLED

    def test_cancel_callback_failure_does_not_block(self):
        """A failing callback must not prevent cancellation."""
        tree = SessionTree(root_session_id="root")

        child = ChildSession(session_id="child1", parent_session_id="root")
        child._cancel_callback = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        tree.add(child)
        transition(child, ChildStatus.QUEUED)
        transition(child, ChildStatus.RUNNING)

        # Should not raise despite callback failure
        tree.cancel_session("child1")
        assert child.status == ChildStatus.CANCELLED


# ============================================================================
# Tree listing and iteration
# ============================================================================

class TestTreeIteration:
    """Session tree listing and containment."""

    def test_list_all_order(self):
        tree = SessionTree(root_session_id="root")
        s1 = ChildSession(session_id="c1", parent_session_id="root")
        s2 = ChildSession(session_id="c2", parent_session_id="root")
        tree.add(s1)
        tree.add(s2)
        all_sessions = tree.list_all()
        assert len(all_sessions) == 2

    def test_len_and_contains(self):
        tree = SessionTree(root_session_id="root")
        s = ChildSession(session_id="child1", parent_session_id="root")
        tree.add(s)
        assert len(tree) == 1
        assert "child1" in tree
        assert "nonexistent" not in tree

    def test_empty_tree(self):
        tree = SessionTree(root_session_id="root")
        assert len(tree) == 0
        assert tree.list_all() == []
        assert tree.list_active() == []
        assert tree.list_terminal() == []


# ============================================================================
# Transition error details
# ============================================================================

class TestTransitionErrors:
    """InvalidStateTransition must carry context."""

    def test_error_includes_session_and_states(self):
        session = ChildSession(session_id="test_session")
        with pytest.raises(InvalidStateTransition) as exc_info:
            transition(session, ChildStatus.COMPLETED)

        err = exc_info.value
        assert err.session_id == "test_session"
        assert err.current == ChildStatus.CREATED
        assert err.target == ChildStatus.COMPLETED

    def test_created_cannot_go_to_running_directly(self):
        session = ChildSession()
        with pytest.raises(InvalidStateTransition):
            transition(session, ChildStatus.RUNNING)

    def test_queued_cannot_go_to_completed_directly(self):
        session = ChildSession()
        transition(session, ChildStatus.QUEUED)
        with pytest.raises(InvalidStateTransition):
            transition(session, ChildStatus.COMPLETED)
