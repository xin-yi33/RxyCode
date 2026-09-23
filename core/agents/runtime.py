"""AgentRuntime：Phase D ChildRuntime 的专家角色适配器。

每个角色通过 Phase D 的 ChildSession/ChildRuntime 获得：
  - ToolRegistry   只含 spec.tools 声明的工具
  - cache namespace
  - circuit breaker key
  - memory namespace（memory_scope="private" 时）
  - LLM（按 spec.model 解析，走 Phase A 的 provider 层）

约束（§3.2）：
  DC2 —— runtime 之间不持有对方引用，只通过 Coordinator 通信
  DC3 —— 默认全隔离，共享必须显式声明

本卡不复制 D5：ChildRuntime / ChildSession 生命周期只走
``create_child_session`` + ``create_child_runtime``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    BudgetSpec,
    EffectiveTaskPolicy,
    PermissionSpec,
    TaskRequest,
    TaskResult,
    ToolPermission,
    TriggerKind,
    WorkspaceMode,
    WorkspaceScope,
)

from RxyCode.RxyCode1_1_0.core.agents.spec import AgentSpecError
from RxyCode.RxyCode1_1_0.core.subagents.runtime import ChildRuntime, create_child_runtime
from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec
from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import get_breaker
from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry, default_registry

if TYPE_CHECKING:
    from RxyCode.RxyCode1_1_0.core.session import Session


_WRITE_TOOL_NAMES = frozenset({"write", "edit", "patch"})


def _role_can_write(spec: AgentSpec) -> bool:
    if spec.mechanical:
        return False
    if spec.tools is None:
        return True
    return bool(_WRITE_TOOL_NAMES.intersection(spec.tools))


_ALLOW_ALL = ToolPermission.from_raw("allow")


def _permission_for(spec: AgentSpec) -> PermissionSpec:
    if spec.mechanical:
        return PermissionSpec()
    if _role_can_write(spec):
        return PermissionSpec(
            read=_ALLOW_ALL,
            edit=_ALLOW_ALL,
            bash=_ALLOW_ALL,
            webfetch=_ALLOW_ALL,
            websearch=_ALLOW_ALL,
        )
    return PermissionSpec(read=_ALLOW_ALL)


def _definition_from_agent_spec(spec: AgentSpec) -> AgentDefinition:
    """Map F3 AgentSpec onto Phase D AgentDefinition. No second lifecycle."""
    parts = [spec.goal, spec.backstory, *spec.constraints]
    prompt = "\n".join(part for part in parts if part).strip() or spec.display_name
    writable = _role_can_write(spec)
    return AgentDefinition(
        id=spec.role,
        description=spec.goal or spec.display_name,
        mode=AgentMode.SUBAGENT,
        prompt=prompt,
        model=None if spec.mechanical else spec.model,
        permission=_permission_for(spec),
        workspace_scope=(
            WorkspaceMode.ISOLATED_WORKTREE if writable else WorkspaceMode.READ_ONLY
        ),
        extra=dict(spec.extra),
        subagent_depth=0,
    )


def _no_llm(_model: str | None) -> Any:
    raise RuntimeError("mechanical role has no LLM")


def _primary_model_name(primary: Any) -> str | None:
    cfg = getattr(primary, "model_config", None)
    if isinstance(cfg, dict):
        for key in ("id", "name", "model", "model_name"):
            value = str(cfg.get(key) or "").strip()
            if value:
                return value
    llm = getattr(primary, "_llm", None)
    for attr in ("model_name", "model"):
        value = str(getattr(llm, attr, None) or "").strip()
        if value:
            return value
    packed = getattr(primary, "_cfg", None)
    if isinstance(packed, dict):
        value = str(packed.get("active_model") or "").strip()
        if value:
            return value
    return None


def _inherited_model_config(primary: Any) -> dict[str, Any]:
    """Copy Primary credentials so Child never sends an empty model id."""
    cfg = dict(getattr(primary, "model_config", None) or {})
    name = _primary_model_name(primary)
    if name and not str(cfg.get("model_name") or "").strip():
        cfg["model_name"] = name
    return cfg


def _primary_tool_registry(primary: Any) -> ToolRegistry:
    orch = getattr(primary, "_tool_orchestrator", None)
    sourced = getattr(orch, "_registry", None) if orch is not None else None
    if sourced is not None and sourced.get_names():
        return sourced
    return default_registry


class _DelegatingRoleAgent:
    """Test-double adapter: unique object, Primary credentials stay on the spy.

    Live AgentV2 instances are always constructed in ``_new_role_agent``.
    """

    def __init__(self, primary: Any, spec: AgentSpec, namespace: str | None) -> None:
        self._primary = primary
        self._spec = spec
        self._agent_namespace = namespace
        self._role_tool_allowlist = (
            None if spec.tools is None else frozenset(spec.tools)
        )
        self._inner_execute = getattr(primary, "_execute_tool", None)

    async def _execute_tool(self, name: str, args: dict, **kwargs: Any) -> str:
        allowed = self._role_tool_allowlist
        if allowed is not None and name not in allowed:
            return f"[blocked: role {self._spec.role} may not use {name}]"
        if callable(self._inner_execute):
            return await self._inner_execute(name, args, **kwargs)
        return f"[blocked: no tool executor for {name}]"

    async def run(self, prompt: str, mode: str = "build", **kwargs: Any) -> Any:
        previous = getattr(self._primary, "_execute_tool", None)
        self._primary._execute_tool = self._execute_tool
        try:
            return await self._primary.run(prompt, mode=mode)
        finally:
            self._primary._execute_tool = previous


class AgentRuntime:
    """Expert-role adapter over a Phase D ChildRuntime."""

    def __init__(
        self,
        spec: AgentSpec,
        *,
        session: Session,
        primary: Any | None = None,
    ) -> None:
        self._spec = spec
        self._session = session
        self._primary = primary
        source = _primary_tool_registry(primary)
        self._registry = self._build_scoped_registry(spec.tools, source=source)
        self._breaker = get_breaker(f"team:{session.session_id}:{spec.role}")
        # role="default" keeps the F2 single-agent cache key (namespace None).
        self._agent_namespace: str | None = None
        self.resolved_model = spec.model
        self._llm: Any | None = None
        if spec.memory_scope == "shared":
            self._memory_store = session._shared_agent_memory
        else:
            self._memory_store = None

        definition = _definition_from_agent_spec(spec)
        child_session = create_child_session(
            TaskRequest(
                parent_session_id=session.session_id,
                agent_id=spec.role,
                prompt="",
                trigger=TriggerKind.TEAM,
            ),
            EffectiveTaskPolicy(
                budget=BudgetSpec(
                    max_steps=80 if _role_can_write(spec) else 40,
                    max_tokens=max(int(spec.token_budget or 0), 120_000),
                    max_wall_time_seconds=max(int(spec.timeout_s or 300), 300),
                ),
                workspace=WorkspaceScope(
                    mode=(
                        WorkspaceMode.ISOLATED_WORKTREE
                        if _role_can_write(spec)
                        else WorkspaceMode.READ_ONLY
                    )
                ),
            ),
            definition=definition,
        )
        self._child = create_child_runtime(
            definition,
            child_session,
            workspace_root=session.workspace_root,
        )
        # F14 shared path: team roles ride the frozen AgentPrefix and count
        # as Primary cache_rate. Isolated Phase D children leave this False.
        self._child._share_primary_prefix = True
        if spec.mechanical:
            self._child.set_agent_factory(_no_llm)
        else:
            self.spawn()
        session.agent_runtimes[spec.role] = self

    def spawn(self) -> "AgentRuntime":
        """Assign the team cache namespace. Solo role=default stays None (DC8)."""
        if self._spec.role == "default":
            self._agent_namespace = None
        else:
            self._agent_namespace = f"agent:{self._spec.role}"

        def factory(model: str | None) -> Any:
            return self._new_role_agent(model)

        self._child.set_agent_factory(factory)
        self.resolved_model = self._spec.model
        return self

    def _new_role_agent(self, model: str | None) -> Any:
        """Fresh AgentV2 per role. Copy credentials from Primary, never the instance."""
        primary = self._primary
        if primary is not None and not hasattr(primary, "model_config"):
            return _DelegatingRoleAgent(
                primary, self._spec, self._agent_namespace
            )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        inherited = _inherited_model_config(primary) if primary is not None else {}
        explicit = (self._spec.model or model or "").strip() or None
        model_id = (explicit or inherited.get("model_name") or _primary_model_name(primary) or "").strip() or None
        agent = AgentV2(model_name=model_id)
        if primary is not None:
            packed = getattr(primary, "_cfg", None)
            if isinstance(packed, dict):
                agent._cfg = packed
            if inherited or explicit:
                merged = dict(agent.model_config or {})
                merged.update({key: value for key, value in inherited.items() if value not in (None, "")})
                if explicit:
                    merged["model_name"] = explicit
                if not str(merged.get("model_name") or "").strip():
                    raise AgentSpecError(
                        "role agent inherited empty model_name from Primary"
                    )
                agent.model_config = merged
                agent._llm = agent._build_llm()
                provider = getattr(primary, "_provider", None)
                if provider is not None:
                    agent._provider = provider
        if self._agent_namespace is not None:
            agent._agent_namespace = self._agent_namespace
        if self._spec.tools is not None:
            agent._role_tool_allowlist = frozenset(self._spec.tools)
        return agent

    @property
    def spec(self) -> AgentSpec:
        return self._spec

    @property
    def role(self) -> str:
        return self._spec.role

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def cache_namespace(self) -> str | None:
        return self._agent_namespace

    @property
    def breaker(self):
        return self._breaker

    @property
    def llm(self) -> Any | None:
        return self._llm

    @property
    def child(self) -> ChildRuntime:
        return self._child

    async def run(self, task: TaskRequest) -> TaskResult:
        """只通过 Phase D ChildRuntime 执行，不持有 Primary 的可变状态。"""
        if self._spec.mechanical:
            raise RuntimeError("mechanical role has no LLM")
        return await self._child.execute(task.prompt)

    def memory_set(self, key: str, value: Any) -> None:
        if self._memory_store is not None:
            self._memory_store[key] = value
            return
        self._child.namespace.memory_set(key, value)

    def memory_get(self, key: str) -> Any | None:
        if self._memory_store is not None:
            return self._memory_store.get(key)
        return self._child.namespace.memory_get(key)

    @staticmethod
    def _build_scoped_registry(
        tool_names: list[str] | None,
        source: ToolRegistry | None = None,
    ) -> ToolRegistry:
        """按角色声明构造独立注册表。

        None  → 复制默认注册表全部工具（等同单 Agent 行为）
        []    → 空注册表（纯推理角色）
        [...] → 只放声明的工具

        角色 adapter 可以提供工具声明转换，但最终 registry 必须由 Phase D
        的 PermissionPolicy/WorkspaceScope 再次裁剪。声明了不存在的工具名必须
        抛异常，不能静默忽略。
        """
        origin = source if source is not None else default_registry
        scoped = ToolRegistry()
        if tool_names is None:
            for tool in origin.get_all():
                scoped.register(tool, risk=origin.get_risk(tool.name))
            return scoped
        if not tool_names:
            return scoped
        known = set(origin.get_names())
        for name in tool_names:
            if name not in known:
                raise AgentSpecError(f"unknown tool {name!r} in AgentSpec.tools")
            tool = origin.get(name)
            if tool is None:
                raise AgentSpecError(f"unknown tool {name!r} in AgentSpec.tools")
            scoped.register(tool, risk=origin.get_risk(name))
        return scoped
