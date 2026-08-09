"""B5 · Isolated AgentRuntime tests — prove all namespaces are independent."""

from __future__ import annotations

import pytest

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    BudgetSpec,
    ChildStatus,
    EffectiveTaskPolicy,
    PermissionSpec,
    PermissionVerdict,
    TaskRequest,
    TriggerKind,
    WorkspaceMode,
    WorkspaceScope,
)
from core.subagents.sessions import ChildSession, create_child_session, transition
from core.subagents.runtime import (
    AgentRuntime,
    BudgetExceededError,
    BudgetGuard,
    CancellationToken,
    ChildCancelledError,
    ChildRuntime,
    NamespaceIsolator,
    ScopedToolRegistry,
    AuditScope,
    create_runtime,
    create_child_runtime,
)


# ============================================================================
# Namespace isolation
# ============================================================================

class TestNamespaceIsolation:
    """Memory and cache namespaces must be independent per child."""

    def test_different_sessions_have_different_namespaces(self):
        ns1 = NamespaceIsolator(session_id="child_a")
        ns2 = NamespaceIsolator(session_id="child_b")

        assert ns1.memory_key("x") != ns2.memory_key("x")
        assert ns1.cache_key("x") != ns2.cache_key("x")

    def test_memory_isolation(self):
        ns1 = NamespaceIsolator(session_id="child_a")
        ns2 = NamespaceIsolator(session_id="child_b")

        ns1.memory_set("key", "value_from_a")
        ns2.memory_set("key", "value_from_b")

        assert ns1.memory_get("key") == "value_from_a"
        assert ns2.memory_get("key") == "value_from_b"

    def test_cache_isolation(self):
        ns1 = NamespaceIsolator(session_id="child_a")
        ns2 = NamespaceIsolator(session_id="child_b")

        ns1.cache_set("result", 42)
        ns2.cache_set("result", 99)

        assert ns1.cache_get("result") == 42
        assert ns2.cache_get("result") == 99

    def test_clear_removes_all(self):
        ns = NamespaceIsolator(session_id="test")
        ns.memory_set("a", 1)
        ns.cache_set("b", 2)
        ns.clear()
        assert ns.memory_get("a") is None
        assert ns.cache_get("b") is None


# ============================================================================
# Cancellation token
# ============================================================================

class TestCancellationToken:
    """CancellationToken must signal and raise correctly."""

    def test_default_not_cancelled(self):
        token = CancellationToken()
        assert not token.is_cancelled
        token.throw_if_cancelled()  # Does not raise

    def test_cancel_sets_flag(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_cancel_raises(self):
        token = CancellationToken()
        token.cancel()
        with pytest.raises(ChildCancelledError):
            token.throw_if_cancelled()

    def test_reset(self):
        token = CancellationToken()
        token.cancel()
        token.reset()
        assert not token.is_cancelled
        token.throw_if_cancelled()  # Does not raise


# ============================================================================
# Budget guard
# ============================================================================

class TestBudgetGuard:
    """BudgetGuard must enforce limits and track usage."""

    def test_initial_budget_has_remaining(self):
        budget = BudgetSpec(max_steps=10, max_tokens=5000)
        guard = BudgetGuard(budget=budget)
        assert guard.remaining_steps == 10
        assert guard.remaining_tokens == 5000
        assert not guard.is_exhausted

    def test_consume_step(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=3))
        guard.consume_step()
        assert guard.steps_used == 1
        assert guard.remaining_steps == 2
        guard.consume_step()
        assert guard.remaining_steps == 1

    def test_step_limit_exceeded(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=1))
        guard.consume_step()
        with pytest.raises(BudgetExceededError, match="Step limit exceeded"):
            guard.consume_step()

    def test_token_limit_exceeded(self):
        guard = BudgetGuard(budget=BudgetSpec(max_tokens=100))
        guard.consume_tokens(90)
        assert guard.remaining_tokens == 10
        with pytest.raises(BudgetExceededError, match="Token limit exceeded"):
            guard.consume_tokens(20)

    def test_is_exhausted_steps(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=1, max_tokens=9999))
        guard.consume_step()
        assert guard.is_exhausted

    def test_is_exhausted_tokens(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=9999, max_tokens=1))
        with pytest.raises(BudgetExceededError, match="Token limit exceeded"):
            guard.consume_tokens(2)
        assert guard.is_exhausted


# ============================================================================
# Scoped tool registry
# ============================================================================

class TestScopedToolRegistry:
    """Tool registry must be scoped per child."""

    def test_two_children_have_different_registries(self):
        reg1 = ScopedToolRegistry(
            agent_id="explore",
            workspace=WorkspaceScope(mode=WorkspaceMode.READ_ONLY),
            permission=PermissionSpec(),
        )
        reg2 = ScopedToolRegistry(
            agent_id="general",
            workspace=WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE),
            permission=PermissionSpec(),
        )

        reg1.register("read", {"name": "read", "description": "read file"}, lambda path: f"read:{path}")

        assert reg1.get_tool("read") is not None
        assert reg2.get_tool("read") is None

    def test_registry_empty_by_default(self):
        reg = ScopedToolRegistry(
            agent_id="test",
            workspace=WorkspaceScope(),
            permission=PermissionSpec(),
        )
        assert reg.list_tools() == []
        assert reg.is_empty()


# ============================================================================
# Audit scope
# ============================================================================

class TestAuditScope:
    """Audit scope must be independent per child."""

    def test_different_children_have_different_trace_ids(self):
        a1 = AuditScope(child_session_id="c1", agent_id="explore")
        a2 = AuditScope(child_session_id="c2", agent_id="reviewer")
        assert a1.trace_id != a2.trace_id

    def test_record_entries(self):
        audit = AuditScope(child_session_id="c1", agent_id="explore")
        audit.tool_call("read", "path=core/auth.py")
        audit.permission_decision("read", "allow", "src/**")
        audit.terminal("completed", "done")

        assert len(audit.entries) == 3
        assert audit.entries[0]["event"] == "tool_call"
        assert audit.entries[1]["event"] == "permission"
        assert audit.entries[2]["event"] == "terminal"

    def test_snapshot_is_copy(self):
        audit = AuditScope(child_session_id="c1", agent_id="explore")
        audit.tool_call("read", "test")
        snap = audit.snapshot()
        snap.clear()
        assert len(audit.entries) == 1  # Original unaffected


# ============================================================================
# AgentRuntime isolation
# ============================================================================

class TestAgentRuntimeIsolation:
    """Two children must have completely independent runtimes."""

    @pytest.fixture
    def explore_def(self):
        return AgentDefinition(
            id="explore",
            description="code explorer",
            mode=AgentMode.SUBAGENT,
            steps=12,
            permission=PermissionSpec(external_directory=PermissionVerdict.DENY),
        )

    @pytest.fixture
    def reviewer_def(self):
        return AgentDefinition(
            id="reviewer",
            description="code reviewer",
            mode=AgentMode.SUBAGENT,
            steps=8,
            permission=PermissionSpec(external_directory=PermissionVerdict.DENY),
        )

    def _make_session(self, agent_id: str, parent_id: str = "ses_primary_1") -> ChildSession:
        request = TaskRequest(
            parent_session_id=parent_id,
            agent_id=agent_id,
            prompt="test task",
            trigger=TriggerKind.AUTOMATIC,
        )
        return create_child_session(request, EffectiveTaskPolicy())

    def test_different_sessions_have_different_runtime_ids(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        assert rt1.session_id != rt2.session_id
        assert rt1.agent_id == "explore"
        assert rt2.agent_id == "reviewer"

    def test_different_namespaces(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        assert rt1.namespace.memory_key("x") != rt2.namespace.memory_key("x")

    def test_different_tool_registries(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        # Registries are different objects
        assert rt1.tools is not rt2.tools

    def test_different_budgets(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        # Budgets are different objects
        assert rt1.budget is not rt2.budget

    def test_different_cancel_tokens(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        assert rt1.cancel_token is not rt2.cancel_token

    def test_different_audit_scopes(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        assert rt1.audit.trace_id != rt2.audit.trace_id

    def test_cancelling_one_child_does_not_affect_other(self, explore_def, reviewer_def):
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        rt1.cancel_token.cancel()
        assert rt1.cancel_token.is_cancelled
        assert not rt2.cancel_token.is_cancelled

    def test_session_cancel_callback_wired(self, explore_def):
        s1 = self._make_session("explore")
        rt1 = create_runtime(explore_def, s1)

        # Cancel via session should trigger runtime cancellation
        assert not rt1.cancel_token.is_cancelled
        assert s1._cancel_callback is not None
        s1._cancel_callback()
        assert rt1.cancel_token.is_cancelled

    def test_no_shared_mutable_state(self, explore_def, reviewer_def):
        """Prove that two runtimes do not share any mutable state."""
        s1 = self._make_session("explore")
        s2 = self._make_session("reviewer")

        rt1 = create_runtime(explore_def, s1)
        rt2 = create_runtime(reviewer_def, s2)

        # Modify rt1's memory
        rt1.namespace.memory_set("shared_key", "rt1_value")
        rt2.namespace.memory_set("shared_key", "rt2_value")

        assert rt1.namespace.memory_get("shared_key") == "rt1_value"
        assert rt2.namespace.memory_get("shared_key") == "rt2_value"

    def _make_session_with_workspace(self, agent_id: str, workspace_mode: WorkspaceMode) -> ChildSession:
        """Create a session with a specific workspace mode in the policy."""
        request = TaskRequest(
            parent_session_id="ses_primary_1",
            agent_id=agent_id,
            prompt="test task",
            trigger=TriggerKind.AUTOMATIC,
        )
        policy = EffectiveTaskPolicy(
            workspace=WorkspaceScope(mode=workspace_mode),
        )
        return create_child_session(request, policy)

    def test_read_only_detection(self, explore_def):
        s = self._make_session_with_workspace("explore", WorkspaceMode.READ_ONLY)
        rt = create_runtime(explore_def, s)
        assert rt.is_read_only is True

    def test_leased_write_detection(self, explore_def):
        s = self._make_session_with_workspace("explore", WorkspaceMode.LEASED_WRITE)
        rt = create_runtime(explore_def, s)
        assert rt.is_read_only is False


# ============================================================================
# ChildRuntime facade
# ============================================================================

class TestChildRuntimeFacade:
    """ChildRuntime provides a stable public API for Phase C/D/E."""

    @pytest.fixture
    def child_runtime(self):
        definition = AgentDefinition(
            id="explore",
            description="explorer",
            mode=AgentMode.SUBAGENT,
        )
        request = TaskRequest(
            parent_session_id="p1",
            agent_id="explore",
            prompt="test",
            trigger=TriggerKind.AUTOMATIC,
        )
        session = create_child_session(request, EffectiveTaskPolicy())
        return create_child_runtime(definition, session)

    def test_facade_exposes_session_id(self, child_runtime):
        assert child_runtime.session_id.startswith("ses_child_")

    def test_facade_exposes_agent_id(self, child_runtime):
        assert child_runtime.agent_id == "explore"

    def test_facade_exposes_definition(self, child_runtime):
        assert child_runtime.definition.id == "explore"

    def test_facade_exposes_budget(self, child_runtime):
        assert isinstance(child_runtime.budget, BudgetGuard)

    def test_facade_exposes_cancel_token(self, child_runtime):
        assert isinstance(child_runtime.cancel_token, CancellationToken)

    def test_facade_exposes_audit(self, child_runtime):
        assert isinstance(child_runtime.audit, AuditScope)

    def test_facade_exposes_namespace(self, child_runtime):
        assert isinstance(child_runtime.namespace, NamespaceIsolator)

    def test_facade_exposes_tools(self, child_runtime):
        assert isinstance(child_runtime.tools, ScopedToolRegistry)

    def test_shutdown_clears_and_cancels(self, child_runtime):
        child_runtime.namespace.memory_set("x", 1)
        child_runtime.shutdown()
        assert child_runtime.namespace.memory_get("x") is None
        assert child_runtime.cancel_token.is_cancelled
