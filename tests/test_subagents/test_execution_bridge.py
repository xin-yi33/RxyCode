from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from protocol.subagents import (
    AgentDefinition, AgentMode, BudgetSpec, ChildStatus, EffectiveTaskPolicy,
    PermissionSpec, PermissionVerdict, TaskPermissionSpec, TaskRequest,
    ToolPermission, TriggerKind, WorkspaceMode, WorkspaceScope,
)
from core.subagents.runtime import create_child_runtime
from core.subagents.sessions import create_child_session
from core.subagents.workspace import LeaseManager, NoWorkspaceScopeError, OutsidePathError


@dataclass
class FakeAgent:
    answer: str = "real child answer"
    session_id: str = ""
    cancelled: bool = False
    received_prompt: str = ""

    def set_session(self, session_id: str) -> str:
        self.session_id = session_id
        return session_id

    async def run(self, prompt: str, *, mode: str = "build", effect: str = "auto") -> str:
        self.received_prompt = prompt
        assert mode == "build"
        assert effect == "search"
        return self.answer

    def cancel(self) -> bool:
        self.cancelled = True
        return True


def _runtime(*, permission: PermissionSpec | None = None):
    definition = AgentDefinition(
        id="general", description="test child", mode=AgentMode.SUBAGENT,
        prompt="You are an isolated read-only specialist.",
        permission=permission or PermissionSpec(
            read=ToolPermission.from_raw("allow"),
            edit=ToolPermission.from_raw("deny"),
            bash=ToolPermission.from_raw("deny"),
        ),
        task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
        workspace_scope=WorkspaceMode.READ_ONLY,
    )
    request = TaskRequest(
        parent_session_id="primary", agent_id="general", prompt="inspect only",
        trigger=TriggerKind.AUTOMATIC,
    )
    session = create_child_session(
        request,
        EffectiveTaskPolicy(
            permission=definition.permission,
            workspace=WorkspaceScope(mode=WorkspaceMode.READ_ONLY),
        ),
        definition=definition,
    )
    return create_child_runtime(definition, session)


def test_child_execution_bridge_runs_isolated_agent_and_returns_usage():
    fake = FakeAgent()
    runtime = _runtime()
    runtime.set_agent_factory(lambda _model: fake)

    result = asyncio.run(runtime.execute("inspect only"))

    assert result.status == ChildStatus.COMPLETED
    assert result.summary == "real child answer"
    assert fake.session_id == runtime.session_id
    assert fake.received_prompt.startswith("/fast\n")
    assert "You are an isolated read-only specialist." in fake.received_prompt
    assert "Task:\ninspect only" in fake.received_prompt
    assert result.usage.steps == 1


def test_child_execution_bridge_returns_stable_budget_error():
    runtime = _runtime()
    runtime._runtime.budget.budget = BudgetSpec(max_steps=0)
    runtime.set_agent_factory(lambda _model: FakeAgent())

    result = asyncio.run(runtime.execute("inspect only"))

    assert result.status == ChildStatus.FAILED
    assert result.error is not None
    assert result.error.code == "budget.steps"


def test_child_execution_bridge_denies_tool_before_agent_execution():
    fake = FakeAgent()
    runtime = _runtime()
    runtime.set_agent_factory(lambda _model: fake)

    assert runtime.check_tool("bash", {"command": "echo unsafe"}) is False
    assert runtime.check_tool("read", {"filePath": "core/agent_v2.py"}) is True


def test_child_runtime_enforces_authoritative_lease_and_workspace_root(tmp_path):
    definition = AgentDefinition(
        id="writer", description="leased writer", mode=AgentMode.SUBAGENT,
        permission=PermissionSpec(edit=ToolPermission.from_raw("allow")),
        workspace_scope=WorkspaceMode.LEASED_WRITE,
    )
    request = TaskRequest(
        parent_session_id="primary", agent_id="writer", prompt="write",
        trigger=TriggerKind.MENTION,
    )
    scope = WorkspaceScope(
        mode=WorkspaceMode.LEASED_WRITE,
        leased_paths=("src/owned.py",),
    )
    session = create_child_session(
        request,
        EffectiveTaskPolicy(permission=definition.permission, workspace=scope),
        definition=definition,
    )
    leases = LeaseManager()
    leases.acquire(session.session_id, ["src/owned.py"])
    runtime = create_child_runtime(definition, session, leases, tmp_path)

    assert runtime.check_tool("edit", {"filePath": "src/owned.py"}) is True
    with pytest.raises(NoWorkspaceScopeError):
        runtime.check_tool("edit", {"filePath": "src/not-owned.py"})
    with pytest.raises(OutsidePathError):
        runtime.check_tool("edit", {"filePath": str(tmp_path.parent / "outside.py")})


def test_child_cancel_propagates_to_active_agent():
    fake = FakeAgent()
    runtime = _runtime()
    runtime.set_agent_factory(lambda _model: fake)
    runtime._active_agent = fake

    runtime.cancel_token.cancel()
    runtime.shutdown()

    assert fake.cancelled is True


def test_manager_cancel_reaches_active_agent():
    fake = FakeAgent()
    runtime = _runtime()
    runtime.set_agent_factory(lambda _model: fake)
    runtime._active_agent = fake

    runtime.cancel()

    assert runtime.cancel_token.is_cancelled is True
    assert fake.cancelled is True


def test_child_final_answer_is_allowed_as_exit_signal():
    """2026-09-23 回归：子代理调 final_answer 不得被权限层拦截。

    现场：专家团子代理按系统提示词调 final_answer 收尾，但 PermissionSpec
    没有该类别（_rules_for 只映射 read/edit/bash/webfetch/websearch/task），
    默认 deny → 返回 [blocked: child permission denied final_answer] →
    decide_react_turn 只认成功调用 → 子代理空转继续调工具（最终答案之后
    又出现 ls）。final_answer 是纯退出信号、无副作用，子代理层直接放行。
    """
    runtime = _runtime()  # 默认权限：read allow / edit deny / bash deny
    assert runtime.check_tool("final_answer", {"result": "done"}) is True
    # 别名形态也放行（canonical_tool_name 折叠 final-answer → final_answer）
    assert runtime.check_tool("final-answer", {"result": "done"}) is True
    # 其余未声明类别仍然默认 deny（不被本次放行波及）
    assert runtime.check_tool("open_file", {"path": "x.txt"}) is False
