"""B7 · Task Tool and automatic dispatch tests."""

from __future__ import annotations

import asyncio
import pytest

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    BudgetSpec,
    ChildStatus,
    EffectiveTaskPolicy,
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
    AgentNotFoundError,
    ChildSessionManager,
    DepthLimitExceededError,
    FeatureDisabledError,
    ModeMismatchError,
    TaskPermissionDeniedError,
)
from RxyCode.RxyCode1_1_0.core.subagents.events import EventStore
from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session, transition
from RxyCode.RxyCode1_1_0.core.subagents.modes import (
    SubagentConfig,
    SubagentFeatureFlags,
)
from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import (
    get_manager,
    get_manager_or_none,
    init_manager,
    reset_manager,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def registry() -> AgentDefinitionRegistry:
    """A registry with the default built-in agents."""
    reg = AgentDefinitionRegistry()
    reg.register_builtin(AgentDefinition(
        id="explore",
        description="只读代码探索",
        mode=AgentMode.SUBAGENT,
        steps=12,
        permission=PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            edit=ToolPermission.from_raw({"**": "deny"}),
            external_directory=PermissionVerdict.DENY,
        ),
        task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
    ))
    reg.register_builtin(AgentDefinition(
        id="general",
        description="通用子任务",
        mode=AgentMode.SUBAGENT,
        steps=12,
        task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
    ))
    reg.register_builtin(AgentDefinition(
        id="primary_agent",
        description="主入口",
        mode=AgentMode.PRIMARY,
    ))
    # The Primary agent (id="primary") governs model-driven Task dispatch.
    # Its permission.task allows the built-in subagents.
    reg.register_builtin(AgentDefinition(
        id="primary",
        description="默认主入口",
        mode=AgentMode.PRIMARY,
        task_permission=TaskPermissionSpec(
            allowed_agents=("explore", "general"),
            default_verdict=PermissionVerdict.DENY,
        ),
    ))
    return reg


@pytest.fixture
def enabled_config() -> SubagentConfig:
    """Config with all subagent features enabled."""
    return SubagentConfig(
        flags=SubagentFeatureFlags(
            subagents_enabled=True,
            subagents_task=True,
            subagents_mention=True,
            subagents_child_tasks=True,
        )
    )


@pytest.fixture
def manager(registry, enabled_config) -> ChildSessionManager:
    return ChildSessionManager(registry=registry, config=enabled_config)


def _task_request(
    agent_id: str = "explore",
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
# Feature gate
# ============================================================================

class TestFeatureGate:
    """When subagents are disabled, dispatch must fail cleanly."""

    def test_disabled_all_features(self, registry):
        disabled = SubagentConfig()  # all flags default False
        m = ChildSessionManager(registry=registry, config=disabled)

        with pytest.raises(FeatureDisabledError):
            asyncio.run(m.dispatch(_task_request()))

    def test_task_disabled_but_enabled_overall(self, registry):
        config = SubagentConfig(
            flags=SubagentFeatureFlags(
                subagents_enabled=True,
                subagents_task=False,
            )
        )
        m = ChildSessionManager(registry=registry, config=config)

        with pytest.raises(FeatureDisabledError, match="task"):
            asyncio.run(m.dispatch(_task_request(trigger=TriggerKind.AUTOMATIC)))


# ============================================================================
# Agent validation
# ============================================================================

class TestAgentValidation:
    """Unknown agents and mode mismatches must fail cleanly."""

    def test_unknown_agent(self, manager):
        with pytest.raises(AgentNotFoundError, match="not found"):
            asyncio.run(manager.dispatch(_task_request(agent_id="does_not_exist")))

    def test_primary_agent_not_dispatchable_as_child(self, manager):
        """Primary-mode agents cannot be dispatched via Task Tool."""
        with pytest.raises(ModeMismatchError, match="cannot be dispatched as a child"):
            asyncio.run(manager.dispatch(_task_request(agent_id="primary_agent")))


# ============================================================================
# Task permission
# ============================================================================

class TestTaskPermission:
    """permission.task controls which agents can be invoked via Task."""

    def test_task_denied_agent(self, registry, enabled_config):
        """An agent that denies 'general' in task permission fails."""
        reg = AgentDefinitionRegistry()
        # The Primary agent's task_permission governs model-driven Task dispatch
        reg.register_builtin(AgentDefinition(
            id="primary",
            description="primary agent",
            mode=AgentMode.PRIMARY,
            task_permission=TaskPermissionSpec(
                allowed_agents=("explore",),
                default_verdict=PermissionVerdict.DENY,
            ),
        ))
        reg.register_builtin(AgentDefinition(
            id="explore",
            description="explorer",
            mode=AgentMode.SUBAGENT,
        ))
        reg.register_builtin(AgentDefinition(
            id="general",
            description="general",
            mode=AgentMode.SUBAGENT,
        ))

        m = ChildSessionManager(registry=reg, config=enabled_config)

        # explore is allowed (allowed_agents in primary's task_permission)
        result = asyncio.run(m.dispatch(_task_request(agent_id="explore", parent="ses_parent_1")))
        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)

        # general is denied (task_permission deny)
        with pytest.raises(TaskPermissionDeniedError, match="general"):
            asyncio.run(m.dispatch(_task_request(agent_id="general", parent="ses_parent_1")))

    def test_mention_bypasses_task_permission(self, manager):
        """User @ mention is explicit delegation — not blocked by task permission."""
        # Even though explore's task_permission is deny-all, a user mention works
        result = asyncio.run(manager.dispatch(
            _task_request(trigger=TriggerKind.MENTION)
        ))
        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)


# ============================================================================
# Depth limit
# ============================================================================

class TestDepthLimit:
    """subagent_depth must enforce the nesting limit."""

    def test_depth_zero_blocks_all(self, registry, enabled_config):
        """subagent_depth=0 → Primary cannot create any child."""
        reg = AgentDefinitionRegistry()
        reg.register_builtin(AgentDefinition(
            id="primary",  # The Primary agent governs the depth limit
            description="parent",
            mode=AgentMode.PRIMARY,
            subagent_depth=0,
        ))
        reg.register_builtin(AgentDefinition(
            id="explore",
            description="explorer",
            mode=AgentMode.SUBAGENT,
        ))
        m = ChildSessionManager(registry=reg, config=enabled_config)

        with pytest.raises(DepthLimitExceededError):
            asyncio.run(m.dispatch(_task_request(agent_id="explore")))

    def test_depth_one_blocks_child_recursion(self, registry, enabled_config):
        """subagent_depth=1 → child cannot create a sub-child."""
        # First dispatch succeeds from Primary (depth 0)
        m = ChildSessionManager(registry=registry, config=enabled_config)
        result = asyncio.run(m.dispatch(_task_request(parent="ses_primary_1")))
        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)

        # A child session (depth 1) dispatching again → blocked
        # The child session must exist in the tree for depth computation
        child_session_id = result.child_session_id
        # Dispatch with child as parent
        with pytest.raises(DepthLimitExceededError):
            asyncio.run(m.dispatch(_task_request(parent=child_session_id)))


# ============================================================================
# Policy computation
# ============================================================================

class TestPolicyComputation:
    """EffectiveTaskPolicy caps requested budget/workspace, never widens."""

    def test_requested_budget_capped_by_definition(self, manager):
        """A request asking for more steps than definition allows is capped."""
        request = _task_request()
        definition = manager.registry.get("explore")  # steps=12

        policy = manager._compute_policy(request, definition)
        assert policy.budget.max_steps <= 12

    def test_default_token_budget_comes_from_server_model_policy(self, registry, enabled_config):
        enabled_config.default_max_tokens = 262144
        manager = ChildSessionManager(registry=registry, config=enabled_config)

        policy = manager._compute_policy(_task_request(), manager.registry.get("explore"))

        assert policy.budget.max_tokens == 262144

    def test_agent_definition_can_narrow_model_derived_token_budget(self, enabled_config):
        enabled_config.default_max_tokens = 262144
        registry = AgentDefinitionRegistry()
        registry.register_builtin(AgentDefinition(
            id="bounded",
            description="bounded",
            mode=AgentMode.SUBAGENT,
            extra={"max_tokens": 4096},
        ))
        manager = ChildSessionManager(registry=registry, config=enabled_config)

        policy = manager._compute_policy(
            TaskRequest(parent_session_id="p1", agent_id="bounded", prompt="test"),
            registry.get("bounded"),
        )

        assert policy.budget.max_tokens == 4096

    def test_requested_workspace_never_widens(self, registry, enabled_config):
        """Requesting leased_write on a read_only agent → capped to read_only."""
        reg = AgentDefinitionRegistry()
        reg.register_builtin(AgentDefinition(
            id="readonly_agent",
            description="read-only",
            mode=AgentMode.SUBAGENT,
            workspace_scope=WorkspaceMode.READ_ONLY,
        ))
        m = ChildSessionManager(registry=reg, config=enabled_config)

        request = TaskRequest(
            parent_session_id="p1",
            agent_id="readonly_agent",
            prompt="test",
            trigger=TriggerKind.AUTOMATIC,
            requested_workspace=WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE),
        )
        definition = reg.get("readonly_agent")
        policy = m._compute_policy(request, definition)
        assert policy.workspace.mode == WorkspaceMode.READ_ONLY

    def test_remaining_child_depth_computed(self, registry, enabled_config):
        """A child of depth 1 has remaining_child_depth = subagent_depth - 1."""
        m = ChildSessionManager(registry=registry, config=enabled_config)
        request = _task_request()
        definition = m.registry.get("explore")  # subagent_depth=1
        policy = m._compute_policy(request, definition)
        assert policy.remaining_child_depth == 0  # 1 - 1


# ============================================================================
# Successful dispatch
# ============================================================================

class TestSuccessfulDispatch:
    """A valid dispatch creates a session and returns a terminal result."""

    def test_dispatch_creates_session_in_tree(self, manager):
        events = []
        manager.set_event_emitter(lambda name, payload: events.append(name))

        result = asyncio.run(manager.dispatch(_task_request()))

        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)
        assert result.child_session_id != ""
        assert result.request_id != ""

        # Session exists in tree
        session = manager.get_session("ses_primary_1", result.child_session_id)
        assert session.is_terminal
        assert result.child_session_id == session.session_id

    def test_events_emitted(self, manager):
        events = []
        manager.set_event_emitter(lambda name, payload: events.append(name))

        asyncio.run(manager.dispatch(_task_request()))

        assert "child_session/created" in events
        assert "child_session/queued" in events
        assert "child_session/started" in events
        # Terminal event
        assert any("child_session/completed" == e or "child_session/failed" == e for e in events)

    def test_events_are_persisted_and_emitted_with_full_lineage(self, manager):
        store = EventStore()
        emitted = []
        manager.set_event_store(store)
        manager.set_event_emitter(lambda name, payload: emitted.append((name, payload)))

        result = asyncio.run(manager.dispatch(_task_request()))

        assert store.latest_cursor() >= 4
        created = store.events_for_session(result.child_session_id)[0]
        assert created.root_session_id == "ses_primary_1"
        assert created.parent_session_id == "ses_primary_1"
        assert created.request_id
        assert created.payload["agent_id"] == "explore"
        assert emitted[0][1]["event_id"] == created.event_id
        assert emitted[0][1]["seq"] == created.seq
        terminal = store.events_for_session(result.child_session_id)[-1]
        assert terminal.payload["usage"]["steps"] >= 1
        assert "input_tokens" in terminal.payload["usage"]
        assert terminal.payload["summary"] == result.summary
        assert terminal.payload["artifacts"] == list(result.artifacts)
        assert terminal.payload["evidence"] == list(result.evidence)

    def test_request_id_correlation(self, manager):
        from dataclasses import replace
        request = replace(_task_request(), request_id="req_custom_123")

        result = asyncio.run(manager.dispatch(request))
        assert result.request_id == "req_custom_123"

    def test_cancel_session(self, manager):
        result = asyncio.run(manager.dispatch(_task_request()))
        child_id = result.child_session_id

        # Session is terminal — cancelling is a no-op
        manager.cancel_session("ses_primary_1", child_id)
        session = manager.get_session("ses_primary_1", child_id)
        assert session.is_terminal

    def test_cancel_root(self, manager):
        asyncio.run(manager.dispatch(_task_request()))
        asyncio.run(manager.dispatch(_task_request()))
        manager.cancel_root("ses_primary_1")

        tree = manager.get_tree("ses_primary_1")
        assert len(tree.list_active()) == 0

    def test_leased_write_conflict_is_terminal_and_explainable(self, manager):
        manager.registry.register_user(AgentDefinition(
            id="writer",
            description="isolated writer",
            mode=AgentMode.SUBAGENT,
            workspace_scope=WorkspaceMode.LEASED_WRITE,
            permission=PermissionSpec(
                edit=ToolPermission.from_raw("allow"),
                read=ToolPermission.from_raw("allow"),
            ),
        ))
        manager._lease_manager.acquire("other-child", ["src/shared.py"])
        events = []
        manager.set_event_emitter(lambda name, payload: events.append((name, payload)))

        result = asyncio.run(manager.dispatch(TaskRequest(
            parent_session_id="ses_primary_1",
            agent_id="writer",
            prompt="update the shared module",
            trigger=TriggerKind.MENTION,
            requested_workspace=WorkspaceScope(
                mode=WorkspaceMode.LEASED_WRITE,
                leased_paths=("src/shared.py",),
            ),
        )))

        assert result.status == ChildStatus.FAILED
        assert result.error is not None
        assert result.error.code == "workspace.conflict"
        assert events[-1][0] == "child_session/failed"
        assert events[-1][1]["payload"]["error"]["code"] == "workspace.conflict"
        assert manager.active_lease_count == 1

    def test_concurrency_limit_is_enforced_by_the_manager(self, manager):
        definition = manager.registry.get("explore")
        assert definition is not None
        occupied_request = _task_request(parent="ses_primary_1")
        occupied = create_child_session(
            occupied_request,
            EffectiveTaskPolicy(
                budget=BudgetSpec(max_concurrent_children=1),
                permission=definition.permission,
            ),
            definition=definition,
        )
        occupied.root_session_id = "ses_primary_1"
        manager.get_tree("ses_primary_1").add(occupied)
        transition(occupied, ChildStatus.QUEUED)
        transition(occupied, ChildStatus.RUNNING)

        request = _task_request(parent="ses_primary_1")
        request = TaskRequest(
            parent_session_id=request.parent_session_id,
            agent_id=request.agent_id,
            prompt=request.prompt,
            trigger=request.trigger,
            requested_budget=BudgetSpec(max_concurrent_children=1),
        )
        result = asyncio.run(manager.dispatch(request))

        assert result.status == ChildStatus.FAILED
        assert result.error is not None
        assert result.error.code == "budget.concurrency"

    def test_retry_uses_original_request_and_creates_new_child(self, manager):
        first = asyncio.run(manager.dispatch(_task_request()))

        retried = asyncio.run(
            manager.retry_session(
                "ses_primary_1", first.child_session_id, request_id="req-retry-1"
            )
        )

        assert retried.request_id == "req-retry-1"
        assert retried.child_session_id != first.child_session_id

    def test_cancel_persists_terminal_event_before_returning(self, manager):
        request = _task_request()
        definition = manager.registry.get("explore")
        session = create_child_session(
            request, manager._compute_policy(request, definition), definition=definition
        )
        session.root_session_id = "ses_primary_1"
        manager.get_tree("ses_primary_1").add(session)
        store = EventStore()
        manager.set_event_store(store)

        manager.cancel_session("ses_primary_1", session.session_id)

        assert store.terminal_status_for(session.session_id) == "child_session/cancelled"


# ============================================================================
# Task tool adapter
# ============================================================================

class TestTaskToolAdapter:
    """The `task` tool thin adapter delegates to the manager."""

    def test_tool_name_is_task(self):
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
        assert subagent_task_tool.name == "task"

    def test_tool_has_coroutine(self):
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
        assert subagent_task_tool.coroutine is not None

    def test_parse_context_refs(self):
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import _parse_context_refs
        refs = _parse_context_refs(["file:core/auth.py", "dir:protocol", "item:turn_1.2"])
        assert len(refs) == 3
        assert refs[0].kind == "file"
        assert refs[0].path == "core/auth.py"
        assert refs[1].kind == "directory"
        assert refs[2].kind == "item"

    def test_parse_empty_refs(self):
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import _parse_context_refs
        assert _parse_context_refs([]) == ()
        assert _parse_context_refs(None) == ()

    def test_sync_dispatch_returns_string(self, registry, enabled_config):
        """The sync entry returns a string (not raising) when manager unset."""
        reset_manager()
        init_manager(registry=registry, config=enabled_config)

        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import dispatch_subagent_task_sync
        result = dispatch_subagent_task_sync(agent_id="explore", prompt="探索")
        assert isinstance(result, str)
        reset_manager()

    @pytest.mark.asyncio
    async def test_dispatch_envelope_task_prefers_prompt_over_description(
        self, monkeypatch
    ):
        captured: dict[str, str] = {}

        class _Mgr:
            def primary_session_id(self) -> str:
                return "p1"

            async def dispatch(self, request):
                captured["prompt"] = request.prompt
                captured["task"] = request.context.task if request.context else ""
                return type(
                    "R",
                    (),
                    {
                        "status": ChildStatus.COMPLETED,
                        "error": None,
                        "summary": "ok",
                    },
                )()

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.core.subagents.registry_provider.get_manager",
            lambda: _Mgr(),
        )
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import dispatch_subagent_task

        out = await dispatch_subagent_task(
            agent_id="explore",
            prompt="打开 notes.md 给我预览",
            description="explore codebase",
        )
        assert captured["prompt"] == "打开 notes.md 给我预览"
        assert captured["task"] == "打开 notes.md 给我预览"
        assert "[task completed]" in out

        captured.clear()
        out = await dispatch_subagent_task(
            agent_id="explore",
            prompt="",
            description="explore codebase",
        )
        assert captured["prompt"] == ""
        assert captured["task"] == ""


# ============================================================================
# Registry provider
# ============================================================================

class TestRegistryProvider:
    """The manager singleton provider works."""

    def test_get_manager_raises_if_uninitialized(self):
        reset_manager()
        with pytest.raises(RuntimeError, match="not initialized"):
            get_manager()

    def test_init_and_get(self, registry, enabled_config):
        reset_manager()
        m = init_manager(registry=registry, config=enabled_config)
        assert get_manager() is m
        reset_manager()

    def test_get_manager_or_none(self):
        reset_manager()
        assert get_manager_or_none() is None
        init_manager()
        assert get_manager_or_none() is not None
        reset_manager()
