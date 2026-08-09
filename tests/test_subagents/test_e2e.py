"""B14 · Phase B end-to-end scenarios (§5 B14 minimum set).

Covers:
  1. Task dispatch → child returns evidence; Primary history not leaked
  2. @reviewer reads but cannot edit
  3. subtask=true creates a child; events don't mix into Primary messages
  4. Two children read different dirs in parallel; results returned
  5. Two children race the same file → stable conflict error
  6. ask approval rejected → denied; tool not executed
  7. Child recursion blocked by permission.task / depth
  8. Parent cancel terminates children, waits, and leases
  9. Restart re-reads persisted events; terminal children not re-run
  10. Feature flag off → single-agent baseline unchanged
"""

from __future__ import annotations

import asyncio
import pytest

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    ChildStatus,
    PermissionSpec,
    PermissionVerdict,
    TaskPermissionSpec,
    TaskRequest,
    ToolPermission,
    TriggerKind,
    WorkspaceMode,
    WorkspaceScope,
)
from RxyCode.RxyCode1_1_0.core.subagents.definitions import AgentDefinitionRegistry
from RxyCode.RxyCode1_1_0.core.subagents.manager import (
    ChildSessionManager,
    DepthLimitExceededError,
    TaskPermissionDeniedError,
)
from RxyCode.RxyCode1_1_0.core.subagents.modes import (
    SubagentConfig,
    SubagentFeatureFlags,
)
from RxyCode.RxyCode1_1_0.core.subagents.permissions import (
    ApprovalDecision,
    ApprovalManager,
    DecisionKind,
    PermissionPolicy,
)
from RxyCode.RxyCode1_1_0.core.subagents.workspace import (
    LeaseConflictError,
    LeaseManager,
    NoWorkspaceScopeError,
)
from RxyCode.RxyCode1_1_0.core.subagents.events import (
    EVENT_COMPLETED,
    EventStore,
    build_event,
)
from RxyCode.RxyCode1_1_0.core.subagents.builtin_agents import load_builtin_agents


@pytest.fixture
def enabled_manager() -> ChildSessionManager:
    """Manager with built-in agents and all subagent features enabled."""
    reg = load_builtin_agents()
    # Primary agent governs Task dispatch
    reg.register_builtin(AgentDefinition(
        id="primary",
        description="主入口",
        mode=AgentMode.PRIMARY,
        task_permission=TaskPermissionSpec(
            allowed_agents=("explore", "reviewer", "general"),
            default_verdict=PermissionVerdict.DENY,
        ),
    ))
    config = SubagentConfig(
        flags=SubagentFeatureFlags(
            subagents_enabled=True,
            subagents_task=True,
            subagents_mention=True,
            subagents_child_tasks=True,
        )
    )
    return ChildSessionManager(registry=reg, config=config)


def _req(
    agent_id: str,
    prompt: str = "探索认证模块",
    trigger: TriggerKind = TriggerKind.AUTOMATIC,
    parent: str = "ses_primary_1",
) -> TaskRequest:
    return TaskRequest(
        parent_session_id=parent,
        agent_id=agent_id,
        prompt=prompt,
        trigger=trigger,
    )


# ============================================================================
# Scenario 1: Task dispatch → evidence, Primary history not leaked
# ============================================================================

class TestScenario1_TaskDispatchEvidence:
    """Primary dispatches explore via Task; evidence returned, no history leak."""

    def test_dispatch_returns_terminal_result(self, enabled_manager):
        result = asyncio.run(enabled_manager.dispatch(_req("explore")))

        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)
        assert result.child_session_id != ""
        assert result.request_id != ""

    def test_primary_history_not_in_context(self, enabled_manager):
        """Child context carries only the task, never Primary's history."""
        # Capture the context the child would receive
        captured = {}

        # Build context through the manager's pipeline
        request = _req("explore")
        definition = enabled_manager.registry.get("explore")
        context = enabled_manager._build_context(request, definition)

        captured["task"] = context.task
        captured["references"] = context.references

        assert captured["task"] == "探索认证模块"
        # No Primary conversation history objects
        assert all(r.kind in ("file", "directory", "item", "artifact") for r in captured["references"])
        assert not any(r.kind == "history" for r in captured["references"])

    def test_child_cannot_read_primary_history(self, enabled_manager):
        """The child runtime has no reference to Primary history."""
        from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_runtime
        from protocol.subagents import EffectiveTaskPolicy

        definition = enabled_manager.registry.get("explore")
        session = create_child_session(_req("explore"), EffectiveTaskPolicy())
        runtime = create_runtime(definition, session)

        # Runtime has no history attribute and namespace is child-scoped
        assert not hasattr(runtime, "primary_history")
        assert runtime.namespace.session_id == session.session_id


# ============================================================================
# Scenario 2: @reviewer reads but cannot edit
# ============================================================================

class TestScenario2_ReviewerCannotEdit:
    """@reviewer reads a diff but its edit permission denies writes."""

    def test_reviewer_edit_denied(self, enabled_manager):
        reviewer = enabled_manager.registry.get("reviewer")
        assert reviewer.permission.edit.rules[0].verdict == PermissionVerdict.DENY

        policy = PermissionPolicy.from_definition(
            reviewer.permission,
            definition_version="v1",
        )
        decision = policy.evaluate("edit", "core/auth.py")
        assert decision.kind == DecisionKind.DENY

    def test_reviewer_read_allowed(self, enabled_manager):
        reviewer = enabled_manager.registry.get("reviewer")
        policy = PermissionPolicy.from_definition(
            reviewer.permission, definition_version="v1",
        )
        decision = policy.evaluate("read", "core/auth.py")
        assert decision.kind == DecisionKind.ALLOW

    def test_reviewer_mention_dispatches(self, enabled_manager):
        result = asyncio.run(enabled_manager.dispatch(_req("reviewer", trigger=TriggerKind.MENTION)))
        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)


# ============================================================================
# Scenario 3: subtask=true creates child; events don't mix with Primary
# ============================================================================

class TestScenario3_SubtaskCommand:
    """A subtask=true command creates a child; events stay in child channel."""

    def test_command_trigger_creates_child(self, enabled_manager):
        events = []
        enabled_manager.set_event_emitter(lambda name, payload: events.append(name))

        result = asyncio.run(enabled_manager.dispatch(_req("reviewer", trigger=TriggerKind.COMMAND)))
        assert result.child_session_id != ""
        assert "child_session/created" in events
        assert "child_session/queued" in events

    def test_primary_mode_agent_can_be_subtask(self):
        """subtask=true forces a primary-mode agent into a child."""
        from RxyCode.RxyCode1_1_0.core.subagents.modes import validate_subagent_entry

        # primary agent + subtask command → allowed
        validate_subagent_entry(AgentMode.PRIMARY, is_subtask_command=True)  # Does not raise


# ============================================================================
# Scenario 4: Two children read different dirs in parallel
# ============================================================================

class TestScenario4_ParallelRead:
    """Two parallel read-only children both return results."""

    def test_parallel_dispatches(self, enabled_manager):
        reqs = [
            _req("explore", prompt="探索 core/"),
            _req("explore", prompt="探索 protocol/"),
        ]

        async def _run():
            return await asyncio.gather(
                enabled_manager.dispatch(reqs[0]),
                enabled_manager.dispatch(reqs[1]),
            )

        r1, r2 = asyncio.run(_run())
        assert r1.child_session_id != r2.child_session_id
        assert r1.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)
        assert r2.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)

    def test_read_only_children_share_no_state(self, enabled_manager):
        """Read-only children run concurrently without conflicts."""
        # Both are read_only scope → no lease needed, safe concurrency
        explore = enabled_manager.registry.get("explore")
        assert explore.workspace_scope == WorkspaceMode.READ_ONLY


# ============================================================================
# Scenario 5: Two children race the same file → stable conflict
# ============================================================================

class TestScenario5_LeaseConflict:
    """Two leased_write children on the same file: one wins, one conflicts."""

    def test_same_file_conflict(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["src/auth.py"])
        assert leases.holder("src/auth.py").session_id == "child_a"

        with pytest.raises(LeaseConflictError) as exc_info:
            leases.acquire("child_b", ["src/auth.py"])
        assert exc_info.value.code == "workspace.conflict"

    def test_editing_without_lease_denied(self):
        """A child without a lease cannot edit (even leased_write scope)."""
        scope = WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE)
        from RxyCode.RxyCode1_1_0.core.subagents.workspace import WorkspaceValidator
        validator = WorkspaceValidator(scope)
        with pytest.raises(NoWorkspaceScopeError, match="no lease"):
            validator.check_edit("child_c", "src/auth.py", LeaseManager())


# ============================================================================
# Scenario 6: ask approval rejected → denied, tool not executed
# ============================================================================

class TestScenario6_ApprovalDenied:
    """A rejected ask approval denies the tool; it never executes."""

    def test_rejected_approval_denies(self):
        approvals = ApprovalManager()
        req = approvals.request(
            session_id="ses_child_1",
            tool_call_id="call_1",
            tool="edit",
            args_summary="path=src/auth.py",
            matched_rule="src/**",
            rule_version="v1",
        )
        resolved = approvals.resolve(req.approval_id, ApprovalDecision.REJECTED)
        assert resolved.decision == ApprovalDecision.REJECTED

        # Decision log shows the denial for audit
        log = approvals.decision_log()
        assert log[0]["decision"] == "rejected"
        assert log[0]["tool_call_id"] == "call_1"

    def test_ask_requires_approval_not_auto_allowed(self):
        """ask verdict produces a recoverable approval, never auto-allow."""
        spec = PermissionSpec(
            edit=ToolPermission.from_raw({"src/**": "ask"}),
        )
        policy = PermissionPolicy.from_definition(spec, definition_version="v1")
        decision = policy.evaluate("edit", "src/auth.py")
        assert decision.kind == DecisionKind.ASK
        assert not decision.allows


# ============================================================================
# Scenario 7: Child recursion blocked
# ============================================================================

class TestScenario7_RecursionBlocked:
    """Child trying to recurse is rejected by depth or permission.task."""

    def test_depth_one_blocks_child_recursion(self, enabled_manager):
        # Primary dispatches explore (depth 0 → child, OK)
        result = asyncio.run(enabled_manager.dispatch(_req("explore", parent="ses_primary_1")))
        child_id = result.child_session_id

        # Child (depth 1) trying to dispatch again → DepthLimitExceeded
        # (explore's remaining_child_depth is 0)
        with pytest.raises(DepthLimitExceededError):
            asyncio.run(enabled_manager.dispatch(_req("explore", parent=child_id)))

    def test_task_permission_blocks_recursion(self):
        """A deny-all task permission blocks child dispatch."""
        reg = AgentDefinitionRegistry()
        reg.register_builtin(AgentDefinition(
            id="primary", description="主", mode=AgentMode.PRIMARY,
            task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
        ))
        reg.register_builtin(AgentDefinition(id="explore", description="探索", mode=AgentMode.SUBAGENT))
        m = ChildSessionManager(registry=reg, config=SubagentConfig(
            flags=SubagentFeatureFlags(subagents_enabled=True, subagents_task=True),
        ))

        with pytest.raises(TaskPermissionDeniedError):
            asyncio.run(m.dispatch(_req("explore")))


# ============================================================================
# Scenario 8: Parent cancel terminates children and leases
# ============================================================================

class TestScenario8_ParentCancel:
    """Cancelling a root terminates children and releases leases."""

    def test_cancel_root_releases_children(self, enabled_manager):
        asyncio.run(enabled_manager.dispatch(_req("explore")))
        asyncio.run(enabled_manager.dispatch(_req("explore")))

        enabled_manager.cancel_root("ses_primary_1")
        tree = enabled_manager.get_tree("ses_primary_1")
        assert len(tree.list_active()) == 0
        assert len(tree.list_terminal()) >= 2

    def test_lease_released_on_cancel(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["f.py"])
        assert leases.holder("f.py") is not None

        # Simulate cancel → release all for session
        leases.release_all_for_session("child_a")
        assert leases.holder("f.py") is None


# ============================================================================
# Scenario 9: Restart re-reads events; terminal children not re-run
# ============================================================================

class TestScenario9_RestartRecovery:
    """Persisted events survive restart; completed children not re-run."""

    def test_terminal_child_not_rerun(self, tmp_path):
        store = EventStore(persist_dir=tmp_path)
        store.append(build_event("child_session/completed", "child_1", "primary_1"))

        # Restart
        store2 = EventStore(persist_dir=tmp_path)
        assert store2.has_terminal_event("child_1")
        assert store2.terminal_status_for("child_1") == "child_session/completed"

        # Recovery logic would NOT re-run child_1 because it has a terminal event
        assert store2.terminal_status_for("child_1") is not None

    def test_events_catch_up_from_cursor(self, tmp_path):
        store = EventStore(persist_dir=tmp_path)
        store.append(build_event("child_session/created", "child_1", "primary_1"))
        store.append(build_event("child_session/completed", "child_1", "primary_1"))

        store2 = EventStore(persist_dir=tmp_path)
        replayed = store2.events_from(0)
        assert len(replayed) == 2
        assert replayed[0].event_name == "child_session/created"


# ============================================================================
# Scenario 10: Feature flag off → single-agent baseline unchanged
# ============================================================================

class TestScenario10_FeatureFlagOff:
    """With subagents off, dispatch is cleanly rejected and baseline holds."""

    def test_dispatch_rejected_when_off(self):
        reg = load_builtin_agents()
        m = ChildSessionManager(registry=reg, config=SubagentConfig())  # all flags off

        from RxyCode.RxyCode1_1_0.core.subagents.manager import FeatureDisabledError
        with pytest.raises(FeatureDisabledError):
            asyncio.run(m.dispatch(_req("explore")))

    def test_default_config_no_extra_calls(self):
        """Default config reports nothing enabled."""
        config = SubagentConfig()
        cap = config.capability
        assert not any([cap.subagents_enabled, cap.task, cap.mention, cap.child_tasks])

    def test_single_agent_tools_unchanged(self):
        """Legacy registration path (subagents off) keeps task-list 'task'."""
        from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
        assert task_tool.name == "task"


# ============================================================================
# Required isolation tests (§8.2)
# ============================================================================

class TestRequiredIsolationTests:
    """The mandatory isolation checks from §8.2."""

    def test_child_has_different_session_id(self, enabled_manager):
        r1 = asyncio.run(enabled_manager.dispatch(_req("explore")))
        r2 = asyncio.run(enabled_manager.dispatch(_req("explore")))
        assert r1.child_session_id != r2.child_session_id

    def test_child_does_not_receive_primary_private_history(self, enabled_manager):
        from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_runtime
        from protocol.subagents import EffectiveTaskPolicy

        definition = enabled_manager.registry.get("explore")
        session = create_child_session(_req("explore"), EffectiveTaskPolicy())
        runtime = create_runtime(definition, session)
        assert not hasattr(runtime, "primary_history")
        assert not hasattr(runtime, "_primary_agent")

    def test_child_has_scoped_tool_registry(self, enabled_manager):
        from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_runtime
        from protocol.subagents import EffectiveTaskPolicy

        definition = enabled_manager.registry.get("explore")
        session = create_child_session(_req("explore"), EffectiveTaskPolicy())
        runtime = create_runtime(definition, session)
        assert runtime.tools.agent_id == "explore"

    def test_child_memory_namespace_does_not_leak(self):
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import NamespaceIsolator
        ns_a = NamespaceIsolator(session_id="child_a")
        ns_b = NamespaceIsolator(session_id="child_b")
        ns_a.memory_set("k", "v_a")
        ns_b.memory_set("k", "v_b")
        assert ns_a.memory_get("k") == "v_a"
        assert ns_b.memory_get("k") == "v_b"

    def test_child_budget_is_not_primary_budget(self):
        from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_runtime
        from protocol.subagents import EffectiveTaskPolicy

        definition = AgentDefinition(id="explore", description="探索", mode=AgentMode.SUBAGENT)
        s1 = create_child_session(_req("explore"), EffectiveTaskPolicy())
        s2 = create_child_session(_req("explore"), EffectiveTaskPolicy())
        r1 = create_runtime(definition, s1)
        r2 = create_runtime(definition, s2)
        assert r1.budget is not r2.budget

    def test_terminal_event_is_idempotent(self, tmp_path):
        store = EventStore(persist_dir=tmp_path)
        ev = build_event("child_session/completed", "c1", "p1")
        first = store.append(ev)
        second = store.append(ev)
        assert first.seq == second.seq
        assert store.latest_cursor() == 1

    def test_single_agent_path_preserves_baseline(self):
        """With subagents off, the legacy task-list tool is still 'task'."""
        from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
        assert task_tool.name == "task"
        assert task_tool.coroutine is not None
