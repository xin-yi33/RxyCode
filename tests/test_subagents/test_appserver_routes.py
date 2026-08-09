"""B14 · AppServer JSON-RPC routes and capability discovery tests."""

from __future__ import annotations

import asyncio
import pytest

from RxyCode.RxyCode1_1_0.appserver.subagent_routes import (
    _result_to_dict,
    capability,
    invoke_agent,
    list_agents,
    start_task,
)
from RxyCode.RxyCode1_1_0.core.subagents.builtin_agents import load_builtin_agents
from RxyCode.RxyCode1_1_0.core.subagents.modes import (
    SubagentConfig,
    SubagentFeatureFlags,
)
from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import (
    init_manager,
    reset_manager,
)


@pytest.fixture
def manager_with_builtins():
    reset_manager()
    reg = load_builtin_agents()
    # Primary agent governs model-driven Task dispatch
    from protocol.subagents import AgentDefinition, AgentMode, PermissionVerdict, TaskPermissionSpec
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
        )
    )
    m = init_manager(registry=reg, config=config)
    yield m
    reset_manager()


class TestCapability:
    """Capability discovery reflects manager state."""

    def test_capability_uninitialized(self):
        reset_manager()
        try:
            cap = capability()
            assert cap["subagents_enabled"] is False
            assert cap["task"] is False
        finally:
            reset_manager()

    def test_capability_enabled(self, manager_with_builtins):
        cap = capability()
        assert cap["subagents_enabled"] is True
        assert cap["task"] is True
        assert cap["mention"] is True
        assert cap["protocol_version"] == 1

    def test_list_agents(self, manager_with_builtins):
        result = list_agents()
        agents = result["agents"]
        ids = {a["id"] for a in agents}
        assert "explore" in ids
        assert "reviewer" in ids


class TestRoutes:
    """agent/invoke and task/start delegate to the manager."""

    def test_invoke_agent_mention(self, manager_with_builtins):
        result = asyncio.run(invoke_agent({
            "agent_id": "explore",
            "prompt": "探索认证模块",
        }))
        assert result["child_session_id"] != ""
        assert result["status"] in ("completed", "failed")
        assert result["request_id"] != ""

    def test_start_task(self, manager_with_builtins):
        result = asyncio.run(start_task({
            "agent_id": "explore",
            "prompt": "探索 protocol/",
            "requested_budget": {"max_steps": 5},
            "requested_workspace": {"mode": "read_only"},
        }))
        assert result["child_session_id"] != ""
        assert result["usage"]["steps"] >= 0

    def test_result_to_dict_shape(self):
        from protocol.subagents import ChildStatus, TaskResult, UsageRecord
        result = TaskResult(
            request_id="req_1",
            child_session_id="ses_child_1",
            status=ChildStatus.COMPLETED,
            summary="done",
            usage=UsageRecord(steps=3, input_tokens=100),
        )
        d = _result_to_dict(result)
        assert d["status"] == "completed"
        assert d["summary"] == "done"
        assert d["usage"]["steps"] == 3
        assert d["error"] is None
