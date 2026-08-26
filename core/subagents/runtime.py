"""Isolated AgentRuntime and ChildRuntime facade.

B5 · Each child session gets its own:
  - AgentDefinition snapshot (immutable)
  - ToolRegistry (constructed per permission + workspace scope)
  - PermissionPolicy (allow/ask/deny evaluation)
  - Memory namespace (prefix-isolated)
  - Cache namespace (prefix-isolated)
  - BudgetGuard (steps/token/time)
  - CancellationToken (per-child cancellation)
  - Trace/Audit scope
  - Provider handle (inherits Primary model until Phase E)

Hard constraints:
  - Child MUST NOT hold a reference to the Primary AgentV2 instance.
  - Child MUST NOT access Primary conversation history directly.
  - Multiple children MUST NOT share mutable singletons.
  - Rendering layers MUST NOT create Runtime instances directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from protocol.subagents import (
    AgentDefinition,
    ChildStatus,
    ErrorRecord,
    PermissionSpec,
    TaskResult,
    UsageRecord,
    WorkspaceMode,
    WorkspaceScope,
)

from .permissions import DecisionKind, PermissionPolicy
try:
    from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats
except ImportError:
    from ..session_runtime import bind_session, reset_session_binding
    from ..utils.streaming import token_stats
from .sessions import ChildSession
from .workspace import LeaseManager, WorkspaceValidator


# ============================================================================
# Namespace isolation
# ============================================================================

@dataclass
class NamespaceIsolator:
    """Provides isolated namespaces for memory and cache.

    Each child session gets a unique namespace derived from its session_id,
    preventing cross-contamination between children and from Primary.
    """

    session_id: str
    _memory_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    _cache_store: dict[str, Any] = field(default_factory=dict)

    def memory_key(self, key: str) -> str:
        """Prefix a memory key with the session namespace."""
        return f"child:{self.session_id}:mem:{key}"

    def cache_key(self, key: str) -> str:
        """Prefix a cache key with the session namespace."""
        return f"child:{self.session_id}:cache:{key}"

    # -- local in-process stores (for testing) -------------------------------

    def memory_get(self, key: str) -> Any | None:
        return self._memory_store.get(key)

    def memory_set(self, key: str, value: Any) -> None:
        self._memory_store[key] = value

    def cache_get(self, key: str) -> Any | None:
        return self._cache_store.get(key)

    def cache_set(self, key: str, value: Any) -> None:
        self._cache_store[key] = value

    def clear(self) -> None:
        """Clear all local memory and cache for this namespace."""
        self._memory_store.clear()
        self._cache_store.clear()


# ============================================================================
# Cancellation token
# ============================================================================

@dataclass
class CancellationToken:
    """Per-child cancellation token.

    Checked before each model call and tool execution. When cancelled,
    the runtime must stop processing and transition to CANCELLED state.
    """

    _cancelled: bool = field(default=False, init=False)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Mark this token as cancelled."""
        self._cancelled = True

    def throw_if_cancelled(self) -> None:
        """Raise CancelledError if this token is cancelled."""
        if self._cancelled:
            raise ChildCancelledError("Child session was cancelled")

    def reset(self) -> None:
        """Reset the token (for test reuse only)."""
        self._cancelled = False


class ChildCancelledError(Exception):
    """Raised when a child session is cancelled mid-execution."""
    pass


# ============================================================================
# Budget guard — canonical implementation lives in budget.py
# ============================================================================

from .budget import (
    BudgetError,
    BudgetGuard,
    TimeLimitExceeded,
    terminate_for_budget_error,
)

# Backward-compatible alias: B5 exposed BudgetExceededError; budget.py's
# BudgetError and its subclasses (StepLimitExceeded, TokenLimitExceeded)
# cover the same contract.
BudgetExceededError = BudgetError


# ============================================================================
# Tool registry (scoped)
# ============================================================================

@dataclass
class ScopedToolRegistry:
    """A tool registry scoped to a child session's permissions and workspace.

    Built from the AgentDefinition's PermissionSpec and WorkspaceScope.
    Tools that are denied by permission are excluded entirely.
    """

    agent_id: str
    workspace: WorkspaceScope
    permission: PermissionSpec

    # Registered tool schemas (name → schema dict)
    _tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Registered tool callables (name → async callable)
    _callables: dict[str, Callable[..., Any]] = field(default_factory=dict)

    def register(self, name: str, schema: dict[str, Any], callable_: Callable[..., Any]) -> None:
        """Register a tool in this scoped registry."""
        self._tools[name] = schema
        self._callables[name] = callable_

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of available tool schemas."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> dict[str, Any] | None:
        """Get a tool schema by name."""
        return self._tools.get(name)

    async def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered tool."""
        if name not in self._callables:
            raise ValueError(f"Tool '{name}' is not available in this registry")
        callable_ = self._callables[name]
        result = callable_(**kwargs)
        # Support both sync and async callables
        import inspect
        if inspect.iscoroutine(result):
            return await result
        return result

    def is_empty(self) -> bool:
        return len(self._tools) == 0


# ============================================================================
# Trace / Audit scope
# ============================================================================

@dataclass
class AuditScope:
    """Per-child audit trail.

    Records tool calls, permission decisions, and terminal state for
    post-hoc audit and Desktop display.
    """

    child_session_id: str
    agent_id: str
    trace_id: str = field(default_factory=lambda: str(uuid4()))

    # Audit entries
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event_type: str, **kwargs: Any) -> None:
        """Record an audit entry."""
        import time
        self.entries.append({
            "event": event_type,
            "timestamp": time.time(),
            "session_id": self.child_session_id,
            "agent_id": self.agent_id,
            "trace_id": self.trace_id,
            **kwargs,
        })

    def tool_call(self, tool_name: str, args_summary: str) -> None:
        self.record("tool_call", tool=tool_name, args=args_summary)

    def permission_decision(self, tool_name: str, verdict: str, rule: str) -> None:
        self.record("permission", tool=tool_name, verdict=verdict, rule=rule)

    def terminal(self, status: str, reason: str = "") -> None:
        self.record("terminal", status=status, reason=reason)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of the audit trail."""
        return list(self.entries)


# ============================================================================
# AgentRuntime — the isolated runtime
# ============================================================================

@dataclass
class AgentRuntime:
    """Isolated runtime for a single child agent.

    This is the internal implementation. External consumers (Phase C, D, E)
    must use the ChildRuntime facade, not this class directly.
    """

    definition: AgentDefinition
    session: ChildSession
    lease_manager: LeaseManager | None = field(default=None, repr=False)
    workspace_root: Path | None = field(default=None, repr=False)

    # Isolated namespaces
    namespace: NamespaceIsolator = field(init=False)
    tools: ScopedToolRegistry = field(init=False)
    budget: BudgetGuard = field(init=False)
    cancel_token: CancellationToken = field(init=False)
    audit: AuditScope = field(init=False)

    # Provider (inherits Primary model until Phase E)
    _provider: Any = field(default=None, repr=False)

    def __post_init__(self):
        """Construct isolated namespaces from the session and definition."""
        self.namespace = NamespaceIsolator(session_id=self.session.session_id)

        self.tools = ScopedToolRegistry(
            agent_id=self.definition.id,
            workspace=self.session.policy.workspace,
            permission=self.definition.permission,
        )

        self.budget = BudgetGuard(budget=self.session.policy.budget)

        self.cancel_token = CancellationToken()
        # Wire cancel callback on the session
        self.session._cancel_callback = self.cancel_token.cancel

        self.audit = AuditScope(
            child_session_id=self.session.session_id,
            agent_id=self.definition.id,
        )

    # -- convenience properties -----------------------------------------------

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def agent_id(self) -> str:
        return self.definition.id

    @property
    def is_read_only(self) -> bool:
        return self.session.policy.workspace.mode == WorkspaceMode.READ_ONLY


# ============================================================================
# ChildRuntime facade — the stable public API for Phase C/D/E
# ============================================================================

class ChildRuntime:
    """Stable facade over AgentRuntime with a single real execution bridge.

    Isolated Phase D children own a fresh AgentV2 per execute(). Team roles
    with ``_share_primary_prefix`` reuse one AgentV2 so warmup stays on the
    frozen prefix. The facade never receives a Primary AgentV2 instance.
    """

    def __init__(self, runtime: AgentRuntime):
        self._runtime = runtime
        self._agent_factory: Callable[[str | None], Any] | None = None
        self._active_agent: Any = None
        self._persistent_agent: Any = None
        self._share_primary_prefix: bool = False

    def set_agent_factory(self, factory: Callable[[str | None], Any]) -> None:
        """Inject a child-local AgentV2 factory (tests/bootstrap only)."""
        self._agent_factory = factory

    def cancel(self) -> bool:
        """Propagate parent cancellation into token and active AgentV2."""
        self._runtime.cancel_token.cancel()
        active = self._active_agent
        cancel = getattr(active, "cancel", None)
        if callable(cancel):
            try:
                return bool(cancel())
            except Exception:
                return False
        return True

    def _build_agent(self) -> Any:
        if self._agent_factory is not None:
            return self._agent_factory(self.definition.model)
        from ..agent_v2 import AgentV2
        return AgentV2(model_name=self.definition.model)

    def check_tool(self, name: str, args: dict[str, Any] | None = None) -> bool:
        """Apply the child policy before a tool reaches AgentV2's gate."""

        value = ""
        args = args or {}
        if name in {"read", "edit", "open_file", "write", "patch"}:
            value = str(args.get("filePath") or args.get("path") or "")
        elif name == "bash":
            value = str(args.get("command") or "")
        elif name in {"websearch", "webfetch"}:
            value = str(args.get("url") or args.get("query") or "")
        policy = PermissionPolicy.from_definition(self.definition.permission)
        if name in {"write", "edit", "patch", "open_file"}:
            category = "edit"
        elif name in {"read", "grep", "ls", "glob"}:
            category = "read"
        else:
            category = name
        decision = policy.evaluate(category, value)
        self.audit.permission_decision(name, decision.kind.value, decision.matched_rule)
        if decision.kind != DecisionKind.ALLOW:
            return False

        validator = WorkspaceValidator(
            self._runtime.session.policy.workspace,
            root=self._runtime.workspace_root,
        )
        if category == "edit":
            validator.check_edit(self.session_id, value, self._runtime.lease_manager)
        elif name == "bash":
            validator.check_bash(self.session_id, value)
        return True

    # -- read-only accessors --------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._runtime.session_id

    @property
    def agent_id(self) -> str:
        return self._runtime.agent_id

    @property
    def definition(self) -> AgentDefinition:
        return self._runtime.definition

    @property
    def budget(self) -> BudgetGuard:
        return self._runtime.budget

    @property
    def cancel_token(self) -> CancellationToken:
        return self._runtime.cancel_token

    @property
    def audit(self) -> AuditScope:
        return self._runtime.audit

    @property
    def namespace(self) -> NamespaceIsolator:
        return self._runtime.namespace

    @property
    def tools(self) -> ScopedToolRegistry:
        return self._runtime.tools

    # -- lifecycle -----------------------------------------------------------

    async def execute(self, task_prompt: str) -> TaskResult:
        """Run the child through a fresh AgentV2 under child policy/context."""
        self._runtime.cancel_token.throw_if_cancelled()
        started = __import__("time").monotonic()
        usage_scope_token, scoped_usage = token_stats.begin_usage_scope(
            count_as_primary=bool(self._share_primary_prefix),
        )
        input_tokens = 0
        output_tokens = 0
        cache_hit_tokens = 0
        try:
            self._runtime.budget.consume_step()
            self.audit.record("execute", prompt=task_prompt)
            reused_agent = (
                self._share_primary_prefix and self._persistent_agent is not None
            )
            if reused_agent:
                agent = self._persistent_agent
            else:
                agent = self._build_agent()
                if self._share_primary_prefix:
                    self._persistent_agent = agent
            self._active_agent = agent
            if callable(getattr(agent, "set_session", None)):
                agent.set_session(self.session_id)

            # Keep the AgentV2 instance child-local and deny disallowed calls
            # before its own safety gate.  Existing AgentV2 remains the sole
            # provider/tool loop; this bridge adds child policy, not a second loop.
            original_execute = getattr(agent, "_execute_tool", None)
            if callable(original_execute):
                async def guarded_execute(name: str, args: dict, **kwargs: Any) -> str:
                    if not self.check_tool(name, args):
                        return f"[blocked: child permission denied {name}]"
                    self.audit.tool_call(name, str(args)[:500])
                    return await original_execute(name, args, **kwargs)
                agent._execute_tool = guarded_execute

            binding = bind_session(self.session_id)
            try:
                wall_limit = self._runtime.budget.budget.max_wall_time_seconds
                role_prompt = (self.definition.prompt or self.definition.description).strip()
                # F14 shared path: reused AgentV2 already has the role suffix
                # in history. Re-sending it every execute inflates the unique
                # suffix and misses Primary 97%.
                if reused_agent:
                    execution_prompt = "/fast\nTask:\n" + task_prompt
                else:
                    execution_prompt = (
                        "/fast\n"
                        f"Child role and constraints:\n{role_prompt}\n\n"
                        f"Task:\n{task_prompt}"
                    )
                if wall_limit > 0:
                    try:
                        answer = await __import__("asyncio").wait_for(
                            agent.run(
                                execution_prompt,
                                mode="build",
                                effect="search" if self._runtime.is_read_only else "write",
                            ),
                            timeout=wall_limit,
                        )
                    except __import__("asyncio").TimeoutError as exc:
                        raise TimeLimitExceeded(
                            f"Wall-clock limit exceeded: {wall_limit}s/{wall_limit}s",
                            code=TimeLimitExceeded.CODE,
                        ) from exc
                else:
                    answer = await agent.run(
                        execution_prompt,
                        mode="build",
                        effect="search" if self._runtime.is_read_only else "write",
                    )
            finally:
                reset_session_binding(binding)

            self._runtime.cancel_token.throw_if_cancelled()
            input_tokens = max(0, scoped_usage["input_tokens"])
            output_tokens = max(0, scoped_usage["output_tokens"])
            cache_hit_tokens = max(0, scoped_usage["cache_hit_tokens"])
            reported = bool(input_tokens or output_tokens or cache_hit_tokens)
            self._runtime.budget.consume_tokens(input_tokens + output_tokens)
            self._runtime.budget.check_wall_clock()
            wall_time_ms = int((__import__("time").monotonic() - started) * 1000)
            evidence = list(getattr(agent, "_last_evidence", []) or [])
            tool_calls = []
            artifacts = []
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                tool = str(item.get("tool") or "")
                if tool and tool not in tool_calls:
                    tool_calls.append(tool)
                for artifact in item.get("artifacts", []) or []:
                    if isinstance(artifact, dict) and artifact.get("exists"):
                        path = str(artifact.get("path") or "")
                        if path and path not in artifacts:
                            artifacts.append(path)
            mcp_calls = [t for t in tool_calls if "mcp" in t.lower()]
            skill_calls = [t for t in tool_calls if "skill" in t.lower()]
            telemetry = {
                "tool_calls": tool_calls,
                "evidence": evidence,
                "artifacts": artifacts,
                "mcp_calls": mcp_calls,
                "skill_calls": skill_calls,
                "cache_usage": {"source": "not_reported", "reason": "global token stats cannot be split safely under concurrency"},
            }
            self.audit.terminal("completed")
            return TaskResult(
                request_id="",
                child_session_id=self.session_id,
                status=ChildStatus.COMPLETED,
                summary=str(answer),
                usage=UsageRecord(
                    steps=self._runtime.budget.steps_used,
                    input_tokens=input_tokens if reported else None,
                    output_tokens=output_tokens if reported else None,
                    cache_hit_tokens=cache_hit_tokens if reported else None,
                    wall_time_ms=wall_time_ms,
                    reporting_status="reported" if reported else "not_reported",
                ),
                telemetry=telemetry,
            )
        except BudgetError as exc:
            status = ChildStatus(terminate_for_budget_error(exc))
            self.audit.terminal(status.value, exc.code)
            return TaskResult(
                request_id="", child_session_id=self.session_id,
                status=status, summary=str(exc),
                error=ErrorRecord(code=exc.code, message=str(exc)),
                usage=UsageRecord(
                    steps=self._runtime.budget.steps_used,
                    input_tokens=(max(0, scoped_usage["input_tokens"])
                                  if any(scoped_usage.values()) else None),
                    output_tokens=(max(0, scoped_usage["output_tokens"])
                                   if any(scoped_usage.values()) else None),
                    cache_hit_tokens=(max(0, scoped_usage["cache_hit_tokens"])
                                      if any(scoped_usage.values()) else None),
                    wall_time_ms=self._runtime.budget.elapsed_wall_ms,
                    reporting_status="reported" if any(scoped_usage.values()) else "not_reported",
                ),
            )
        except ChildCancelledError:
            self.audit.terminal("cancelled")
            return TaskResult(
                request_id="", child_session_id=self.session_id,
                status=ChildStatus.CANCELLED, summary="Cancelled",
                usage=UsageRecord(steps=self._runtime.budget.steps_used),
            )
        except __import__("asyncio").CancelledError:
            self.audit.terminal("cancelled")
            return TaskResult(
                request_id="", child_session_id=self.session_id,
                status=ChildStatus.CANCELLED, summary="Cancelled during execution",
                usage=UsageRecord(steps=self._runtime.budget.steps_used),
            )
        except Exception as exc:
            self.audit.terminal("failed", type(exc).__name__)
            return TaskResult(
                request_id="", child_session_id=self.session_id,
                status=ChildStatus.FAILED, summary="Child execution failed",
                error=ErrorRecord(code="child_execution_failed", message=str(exc)),
                usage=UsageRecord(steps=self._runtime.budget.steps_used),
            )
        finally:
            self._active_agent = None
            token_stats.end_usage_scope(usage_scope_token)

    def shutdown(self) -> None:
        """Cancel active child execution and release child-local state."""
        self._runtime.cancel_token.cancel()
        active = self._active_agent
        cancel = getattr(active, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        self._runtime.namespace.clear()


# ============================================================================
# Factory
# ============================================================================

def create_runtime(
    definition: AgentDefinition,
    session: ChildSession,
    lease_manager: LeaseManager | None = None,
    workspace_root: Path | None = None,
) -> AgentRuntime:
    """Create an isolated AgentRuntime for a child session.

    This is the single factory function. Phase C must use this or the
    ChildRuntime facade — it must NOT construct AgentRuntime directly.
    """
    return AgentRuntime(
        definition=definition,
        session=session,
        lease_manager=lease_manager,
        workspace_root=workspace_root,
    )


def create_child_runtime(
    definition: AgentDefinition,
    session: ChildSession,
    lease_manager: LeaseManager | None = None,
    workspace_root: Path | None = None,
) -> ChildRuntime:
    """Create a ChildRuntime facade for a child session."""
    runtime = create_runtime(definition, session, lease_manager, workspace_root)
    child = ChildRuntime(runtime)
    session._cancel_callback = child.cancel
    return child
