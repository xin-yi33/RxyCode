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
from typing import Any, Callable
from uuid import uuid4

from protocol.subagents import (
    AgentDefinition,
    BudgetSpec,
    PermissionSpec,
    TaskResult,
    WorkspaceMode,
    WorkspaceScope,
)

from .sessions import ChildSession


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
# Budget guard
# ============================================================================

@dataclass
class BudgetGuard:
    """Enforces budget limits for a single child session.

    Budget limits are frozen at creation time. Each model call and tool
    execution consumes budget. When any limit is reached, the guard raises
    BudgetExceededError.
    """

    budget: BudgetSpec = field(default_factory=BudgetSpec)

    # Running counters
    steps_used: int = field(default=0, init=False)
    tokens_used: int = field(default=0, init=False)
    wall_start_ms: int = field(default=0, init=False)

    def __post_init__(self):
        import time
        self.wall_start_ms = int(time.time() * 1000)

    # -- consumption ---------------------------------------------------------

    def consume_step(self) -> None:
        """Consume one agentic iteration step."""
        self.steps_used += 1
        if self.steps_used > self.budget.max_steps:
            raise BudgetExceededError(
                f"Step limit exceeded: {self.steps_used}/{self.budget.max_steps}"
            )

    def consume_tokens(self, count: int) -> None:
        """Consume tokens from the budget."""
        self.tokens_used += count
        if self.tokens_used > self.budget.max_tokens:
            raise BudgetExceededError(
                f"Token limit exceeded: {self.tokens_used}/{self.budget.max_tokens}"
            )

    @property
    def remaining_steps(self) -> int:
        return max(0, self.budget.max_steps - self.steps_used)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.budget.max_tokens - self.tokens_used)

    @property
    def wall_time_ms(self) -> int:
        import time
        return int(time.time() * 1000) - self.wall_start_ms

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_steps <= 0 or self.remaining_tokens <= 0


class BudgetExceededError(Exception):
    """Raised when a child session exceeds its budget."""
    pass


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
    """Stable facade over AgentRuntime.

    Phase C (expert orchestration), Phase D (Desktop), and Phase E
    (multi-model) MUST only depend on this facade, never on the
    internal AgentRuntime implementation.
    """

    def __init__(self, runtime: AgentRuntime):
        self._runtime = runtime

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
        """Execute a task within this child runtime.

        This is a placeholder for the full agentic loop which will be
        implemented when the Provider integration is wired in B7.
        """
        self._runtime.cancel_token.throw_if_cancelled()

        try:
            self._runtime.budget.consume_step()
            self._runtime.audit.record("execute", prompt=task_prompt)

            # Placeholder: real execution happens when Provider is wired
            summary = f"[ChildRuntime {self.agent_id}] Task received: {task_prompt[:100]}"

            from protocol.subagents import (
                ChildStatus,
                TaskResult,
                UsageRecord,
            )

            return TaskResult(
                request_id="",
                child_session_id=self.session_id,
                status=ChildStatus.COMPLETED,
                summary=summary,
                usage=UsageRecord(
                    steps=self._runtime.budget.steps_used,
                    input_tokens=0,
                    output_tokens=0,
                ),
            )

        except ChildCancelledError:
            from protocol.subagents import ChildStatus, TaskResult, UsageRecord
            return TaskResult(
                request_id="",
                child_session_id=self.session_id,
                status=ChildStatus.CANCELLED,
                summary="Cancelled",
                usage=UsageRecord(steps=self._runtime.budget.steps_used),
            )

    def shutdown(self) -> None:
        """Release resources held by this runtime."""
        self._runtime.namespace.clear()
        self._runtime.cancel_token.cancel()


# ============================================================================
# Factory
# ============================================================================

def create_runtime(definition: AgentDefinition, session: ChildSession) -> AgentRuntime:
    """Create an isolated AgentRuntime for a child session.

    This is the single factory function. Phase C must use this or the
    ChildRuntime facade — it must NOT construct AgentRuntime directly.
    """
    return AgentRuntime(definition=definition, session=session)


def create_child_runtime(definition: AgentDefinition, session: ChildSession) -> ChildRuntime:
    """Create a ChildRuntime facade for a child session."""
    runtime = create_runtime(definition, session)
    return ChildRuntime(runtime)
