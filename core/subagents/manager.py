"""ChildSessionManager — central dispatch and lifecycle controller.

B7 · The single entry point for ALL child session dispatch:
  - Task Tool (automatic, model-driven)
  - @ agent/invoke (mention, user-driven)
  - task/start (Desktop/CLI explicit)
  - Command subtask=true

All entries share the same fixed execution order:
  1. parse args
  2. validate AgentDefinition (exists, mode)
  3. validate permission.task (normalized TaskPermissionSpec)
  4. construct ContextEnvelope (workspace-scoped, redacted)
  5. compute EffectiveTaskPolicy (budget/workspace capped — never widened)
  6. compute remaining_child_depth from global depth and current session depth
  7. create Child Session
  8. emit child_session/created
  9. execute Child Runtime
  10. return TaskResult summary to Primary
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import RLock
from typing import Callable

from protocol.subagents import (
    AgentDefinition,
    BudgetSpec,
    ChildStatus,
    ContextEnvelope,
    EffectiveTaskPolicy,
    PermissionVerdict,
    TaskPermissionSpec,
    TaskRequest,
    TaskResult,
    TriggerKind,
    UsageRecord,
    WorkspaceMode,
    WorkspaceScope,
)

from .definitions import AgentDefinitionRegistry
from .modes import (
    SubagentConfig,
    validate_subagent_entry,
)
from .sessions import (
    ChildSession,
    SessionTree,
    create_child_session,
    transition,
)
from .runtime import (
    create_child_runtime,
)
from .context import ContextBuilder
from .events import EventStore, TERMINAL_EVENTS, build_event
from .workspace import LeaseManager, WorkspaceError


# ---------------------------------------------------------------------------
# Dispatch errors
# ---------------------------------------------------------------------------

class DispatchError(Exception):
    """Base class for dispatch failures."""

    def __init__(self, message: str, *, code: str = "dispatch_error"):
        super().__init__(message)
        self.code = code


class AgentNotFoundError(DispatchError):
    """Raised when the target agent is not registered."""

    def __init__(self, agent_id: str):
        super().__init__(
            f"Agent '{agent_id}' not found in registry",
            code="agent_not_found",
        )
        self.agent_id = agent_id


class ModeMismatchError(DispatchError):
    """Raised when the agent mode is incompatible with the trigger."""

    def __init__(self, agent_id: str, reason: str):
        super().__init__(f"Agent '{agent_id}' cannot be dispatched: {reason}", code="mode_mismatch")
        self.agent_id = agent_id


class TaskPermissionDeniedError(DispatchError):
    """Raised when permission.task denies invocation of the target agent."""

    def __init__(self, agent_id: str, parent_agent_id: str = ""):
        super().__init__(
            f"Task permission denied for agent '{agent_id}'"
            + (f" from '{parent_agent_id}'" if parent_agent_id else ""),
            code="task_permission_denied",
        )
        self.agent_id = agent_id


class DepthLimitExceededError(DispatchError):
    """Raised when the child depth limit would be exceeded."""

    def __init__(self, current_depth: int, max_depth: int):
        super().__init__(
            f"Subagent depth limit exceeded: depth {current_depth} >= max {max_depth}",
            code="depth_limit_exceeded",
        )
        self.current_depth = current_depth
        self.max_depth = max_depth


class FeatureDisabledError(DispatchError):
    """Raised when the subagent feature is disabled via feature flag."""

    def __init__(self, feature: str):
        super().__init__(
            f"Subagent feature '{feature}' is disabled",
            code="feature_disabled",
        )
        self.feature = feature


# ---------------------------------------------------------------------------
# Event emitter hook (B12 fills in the full event model)
# ---------------------------------------------------------------------------

EventEmitter = Callable[[str, dict], None]


# ---------------------------------------------------------------------------
# ChildSessionManager
# ---------------------------------------------------------------------------

@dataclass
class ChildSessionManager:
    """Central controller for child session lifecycle.

    One manager per process / Primary session tree.
    """

    registry: AgentDefinitionRegistry
    config: SubagentConfig = field(default_factory=SubagentConfig)
    primary_agent_id: str = "primary"  # AgentDefinition id governing Primary task_permission
    workspace_root: Path | None = None
    _trees: dict[str, SessionTree] = field(default_factory=dict)
    _event_emitter: EventEmitter | None = field(default=None, repr=False)
    _event_store: EventStore | None = field(default=None, repr=False)
    _request_ids_by_session: dict[str, str] = field(default_factory=dict, repr=False)
    _requests_by_session: dict[str, TaskRequest] = field(default_factory=dict, repr=False)
    _lease_manager: LeaseManager = field(default_factory=LeaseManager, repr=False)
    _book_lock: RLock = field(default_factory=RLock, repr=False)

    # -- event wiring --------------------------------------------------------

    def set_event_emitter(self, emitter: EventEmitter | None) -> None:
        """Attach an event emitter (B12 persists events)."""
        self._event_emitter = emitter

    def set_event_store(self, store: EventStore | None) -> None:
        """Attach the authoritative append-only event store for this tree."""
        self._event_store = store

    def _emit(self, event_name: str, payload: dict) -> None:
        session_id = str(payload.get("session_id", ""))
        if (
            self._event_store is not None
            and event_name in TERMINAL_EVENTS
            and self._event_store.has_terminal_event(session_id)
        ):
            return
        session = self._find_session(session_id)
        parent_session_id = (
            session.parent_session_id
            if session is not None
            else str(payload.get("parent_session_id", ""))
        )
        root_session_id = (
            session.root_session_id
            if session is not None
            else str(payload.get("root_session_id", parent_session_id))
        )
        request_id = self._request_ids_by_session.get(
            session_id, str(payload.get("request_id", ""))
        )
        event = build_event(
            event_name,
            session_id,
            parent_session_id,
            root_session_id=root_session_id,
            request_id=request_id,
            definition_version=(
                session.definition_version if session is not None else ""
            ),
            payload=dict(payload),
        )
        if self._event_store is not None:
            event = self._event_store.append(event)
        if self._event_emitter is not None:
            try:
                self._event_emitter(event_name, event.to_dict())
            except Exception:
                # Event emission must never block dispatch
                pass

    def _find_session(self, session_id: str) -> ChildSession | None:
        if not session_id:
            return None
        for tree in self._trees.values():
            try:
                return tree.get(session_id)
            except KeyError:
                continue
        return None

    def _root_for_parent(self, parent_session_id: str) -> str:
        parent = self._find_session(parent_session_id)
        return parent.root_session_id if parent is not None else parent_session_id

    # -- tree management -----------------------------------------------------

    def _tree_for(self, root_session_id: str) -> SessionTree:
        if root_session_id not in self._trees:
            self._trees[root_session_id] = SessionTree(root_session_id=root_session_id)
        return self._trees[root_session_id]

    def get_tree(self, root_session_id: str) -> SessionTree:
        """Return the session tree for a Primary session."""
        return self._tree_for(root_session_id)

    def get_session(self, root_session_id: str, session_id: str) -> ChildSession:
        """Look up a session in a Primary session tree."""
        return self._tree_for(root_session_id).get(session_id)

    def cancel_session(self, root_session_id: str, session_id: str) -> None:
        """Cancel a session and all its descendants."""
        tree = self._tree_for(root_session_id)
        active_before = {
            session.session_id for session in tree.list_active()
        }
        tree.cancel_session(session_id)
        for session in tree.list_all():
            if (
                session.session_id in active_before
                and session.status == ChildStatus.CANCELLED
            ):
                self._emit(
                    "child_session/cancelled",
                    {"session_id": session.session_id, "status": "cancelled"},
                )
                self._lease_manager.release_all_for_session(session.session_id)

    def cancel_root(self, root_session_id: str) -> None:
        """Cancel all children under a Primary session."""
        tree = self._tree_for(root_session_id)
        active_before = {
            session.session_id for session in tree.list_active()
        }
        tree.cancel_all()
        for session in tree.list_all():
            if (
                session.session_id in active_before
                and session.status == ChildStatus.CANCELLED
            ):
                self._emit(
                    "child_session/cancelled",
                    {"session_id": session.session_id, "status": "cancelled"},
                )
                self._lease_manager.release_all_for_session(session.session_id)

    @property
    def active_lease_count(self) -> int:
        """Return the unique active lease count without exposing paths."""
        return len({
            lease.lease_id
            for lease in self._lease_manager._leases.values()
            if lease.is_active
        })

    async def retry_session(
        self,
        root_session_id: str,
        session_id: str,
        *,
        request_id: str,
    ) -> TaskResult:
        """Retry a terminal child from its immutable original request."""
        session = self.get_session(root_session_id, session_id)
        if not session.is_terminal:
            raise DispatchError(
                f"Child session '{session_id}' is still active",
                code="retry_active_session",
            )
        original = self._requests_by_session.get(session_id)
        if original is None:
            raise DispatchError(
                f"Original request for child session '{session_id}' is unavailable",
                code="retry_request_unavailable",
            )
        return await self.dispatch(replace(original, request_id=request_id))

    # -- capability ----------------------------------------------------------

    @property
    def capability(self):
        """Return the capability report for this manager."""
        return self.config.capability

    # -- current session context ----------------------------------------------

    def primary_session_id(self) -> str:
        """Return the current Primary session id from session context.

        Falls back to "latest" when no session is bound (tests, bootstrap).
        """
        try:
            # Relative import so it stays within the same package tree
            # (bare `from core...` would create a second session_runtime instance).
            from ..session_runtime import current_session_id
            return current_session_id()
        except Exception:
            return "latest"

    # -- main dispatch -------------------------------------------------------

    async def dispatch(self, request: TaskRequest) -> TaskResult:
        """Dispatch a task to a child session.

        This is the single dispatch path used by ALL triggers.
        """
        # Feature gate
        if not self.config.flags.subagents_enabled:
            raise FeatureDisabledError("subagents")

        # Trigger-specific feature gates
        if request.trigger == TriggerKind.AUTOMATIC and not self.config.flags.subagents_task:
            raise FeatureDisabledError("task")
        if request.trigger == TriggerKind.MENTION and not self.config.flags.subagents_mention:
            raise FeatureDisabledError("mention")

        # 1. Validate AgentDefinition
        definition = self.registry.get(request.agent_id)
        if definition is None:
            raise AgentNotFoundError(request.agent_id)

        # 2. Validate mode against trigger
        is_subtask = request.trigger == TriggerKind.COMMAND
        try:
            validate_subagent_entry(definition.mode, is_subtask_command=is_subtask)
        except ValueError as exc:
            raise ModeMismatchError(request.agent_id, str(exc)) from exc

        # 3. Construct ContextEnvelope (workspace-scoped, redacted)
        context = self._build_context(request, definition)

        # 4. Compute EffectiveTaskPolicy (server-authoritative)
        policy = self._compute_policy(request, definition)

        # 5. Enforce structural depth limit (hard safety check — before
        #    policy gates so recursion is always rejected as depth error)
        #    The limit is set by the PARENT (or global config), never the target.
        current_depth = self._current_depth(request.parent_session_id)
        parent_limit = self._parent_depth_limit(request)
        if current_depth >= parent_limit:
            raise DepthLimitExceededError(current_depth, parent_limit)

        # 6. Validate permission.task (from the PARENT's normalized policy)
        #    For Primary → child, use the Primary agent's task_permission.
        #    If no Primary definition exists, the global default applies.
        self._check_task_permission(request, definition)

        # 7. Create Child Session
        session = create_child_session(request, policy, definition=definition)
        session.root_session_id = (
            self._root_for_parent(request.parent_session_id) or session.session_id
        )

        with self._book_lock:
            tree = self._tree_for(session.root_session_id)
            tree.add(session)
            self._request_ids_by_session[session.session_id] = request.request_id
            self._requests_by_session[session.session_id] = request

        self._emit("child_session/created", {
            "session_id": session.session_id,
            "parent_session_id": request.parent_session_id,
            "request_id": request.request_id,
            "agent_id": request.agent_id,
            "trigger": request.trigger.value,
            "status": session.status.value,
        })

        # 8. Transition to QUEUED
        transition(session, ChildStatus.QUEUED)
        self._emit("child_session/queued", {"session_id": session.session_id})

        # 9. Execute Child Runtime
        result = await self._run_child(request, session, definition, context)

        return result

    # -- internal validation steps -------------------------------------------

    def _check_task_permission(self, request: TaskRequest, definition: AgentDefinition) -> None:
        """Validate permission.task: may the caller invoke this target agent?"""

        # User-direct @ (mention) is explicit delegation — NOT blocked by
        # permission.task (per §4.3). Still passes hard-reject, mode, depth.
        if request.trigger == TriggerKind.MENTION:
            return

        # For model-driven Task dispatch, the parent's normalized
        # task_permission controls which targets may be invoked.
        parent_policy = self._parent_task_permission(request)
        if not parent_policy.allows(definition.id):
            raise TaskPermissionDeniedError(definition.id, request.parent_session_id)

    def _parent_task_permission(self, request: TaskRequest) -> TaskPermissionSpec:
        """Resolve the task permission of the requesting parent.

        If the parent session is a child, its EffectiveTaskPolicy snapshot
        holds the normalized permission (its own ``permission.task``).

        If the parent is the Primary session (not in any tree), use the
        Primary agent definition's ``task_permission``. This is the ONLY
        config source that governs model-driven Task dispatch from Primary.

        If no Primary definition exists, the global default applies.
        """
        # Look up parent session in any tree
        for tree in self._trees.values():
            try:
                parent = tree.get(request.parent_session_id)
            except KeyError:
                continue
            return parent.policy.task_permission

        # Parent is the Primary — use the Primary agent's task_permission
        primary_def = self.registry.get(self.primary_agent_id)
        if primary_def is not None:
            return primary_def.task_permission

        # Default: if config says task_permission default is deny
        if self.config.default_task_permission_deny:
            return TaskPermissionSpec(default_verdict=PermissionVerdict.DENY)
        return TaskPermissionSpec(default_verdict=PermissionVerdict.ALLOW)

    def _parent_depth_limit(self, request: TaskRequest) -> int:
        """Resolve the depth limit governing THIS dispatch.

        If the parent is a child session, its persisted
        ``remaining_child_depth`` is the hard limit (recursion guard).

        If the parent is the Primary session, the Primary agent's
        ``subagent_depth`` (or the global config default) applies.

        The target's own ``subagent_depth`` NEVER governs how deep the
        caller may recurse — only its own future children.
        """
        for tree in self._trees.values():
            try:
                parent = tree.get(request.parent_session_id)
            except KeyError:
                continue
            return parent.policy.remaining_child_depth

        primary_def = self.registry.get(self.primary_agent_id)
        if primary_def is not None:
            return primary_def.subagent_depth
        return self.config.default_subagent_depth

    def _build_context(self, request: TaskRequest, definition: AgentDefinition) -> ContextEnvelope:
        """Construct a workspace-scoped, redacted context envelope."""
        if request.context is not None:
            # Request already carries context (from agent/invoke or task/start)
            return request.context

        # Build minimal context from the task prompt
        builder = ContextBuilder(
            parent_session_id=request.parent_session_id,
            task=request.prompt,
            max_context_tokens=12000,
        )
        return builder.build()

    def _compute_policy(self, request: TaskRequest, definition: AgentDefinition) -> EffectiveTaskPolicy:
        """Compute the server-authoritative EffectiveTaskPolicy.

        The request's requested_budget/workspace are treated as upper-bound
        proposals ONLY. The server caps them at definition/global limits and
        NEVER widens permissions.
        """
        # Budget: cap requested budget at definition defaults
        max_steps = min(
            request.requested_budget.max_steps if request.requested_budget else 2**31,
            definition.steps if definition.steps else 12,
        )
        definition_max_tokens = definition.extra.get("max_tokens")
        server_max_tokens = (
            definition_max_tokens
            if isinstance(definition_max_tokens, int) and definition_max_tokens > 0
            else self.config.default_max_tokens
        )
        max_tokens = min(
            request.requested_budget.max_tokens if request.requested_budget else 2**31,
            server_max_tokens,
        )
        max_wall = request.requested_budget.max_wall_time_seconds if request.requested_budget else 300
        max_concurrent = request.requested_budget.max_concurrent_children if request.requested_budget else 3

        budget = BudgetSpec(
            max_steps=max_steps,
            max_tokens=max_tokens,
            max_wall_time_seconds=max_wall,
            max_concurrent_children=max_concurrent,
        )

        # Workspace: use requested workspace mode, capped at definition scope
        requested_mode = (
            request.requested_workspace.mode if request.requested_workspace else None
        )
        workspace_mode = self._resolve_workspace_mode(requested_mode, definition)

        workspace = WorkspaceScope(
            mode=workspace_mode,
            leased_paths=(
                request.requested_workspace.leased_paths
                if request.requested_workspace else ()
            ),
        )

        # remaining_child_depth: child starts at depth 1 (one below parent)
        remaining = max(0, definition.subagent_depth - 1)

        return EffectiveTaskPolicy(
            task_permission=definition.task_permission,
            subagent_depth=definition.subagent_depth,
            remaining_child_depth=remaining,
            budget=budget,
            workspace=workspace,
            permission=definition.permission,
        )

    def _resolve_workspace_mode(
        self,
        requested: WorkspaceMode | None,
        definition: AgentDefinition,
    ) -> WorkspaceMode:
        """Resolve the effective workspace mode, never widening the definition."""
        if requested is None:
            return definition.workspace_scope

        # Cap the requested mode at the definition's declared scope
        # Order: read_only < leased_write < isolated_worktree
        order = [WorkspaceMode.READ_ONLY, WorkspaceMode.LEASED_WRITE, WorkspaceMode.ISOLATED_WORKTREE]
        requested_level = order.index(requested)
        definition_level = order.index(definition.workspace_scope)
        return order[min(requested_level, definition_level)]

    def _current_depth(self, parent_session_id: str) -> int:
        """Compute the current child depth of a parent session.

        0 = Primary (no parent). Each child adds one level.
        """
        if not parent_session_id:
            return 0

        for tree in self._trees.values():
            try:
                parent = tree.get(parent_session_id)
            except KeyError:
                continue
            # Depth = depth of parent + 1 (children of a child are deeper)
            # We compute recursively by walking up the lineage
            return self._depth_of(parent) + 1

        return 0

    def _depth_of(self, session: ChildSession) -> int:
        """Recursively compute a session's depth in the lineage."""
        depth = 0
        current = session
        visited = set()
        while current.parent_session_id and current.session_id not in visited:
            visited.add(current.session_id)
            found = False
            for tree in self._trees.values():
                try:
                    parent = tree.get(current.parent_session_id)
                except KeyError:
                    continue
                current = parent
                depth += 1
                found = True
                break
            if not found:
                break
        return depth

    # -- child execution -----------------------------------------------------

    async def _run_child(
        self,
        request: TaskRequest,
        session: ChildSession,
        definition: AgentDefinition,
        context: ContextEnvelope,
    ) -> TaskResult:
        """Run a child session through its runtime to a terminal result."""
        from protocol.subagents import ErrorRecord

        with self._book_lock:
            try:
                transition(session, ChildStatus.RUNNING)
            except Exception:
                # Session was cancelled while queued
                return self._terminal_result(
                    request, session, ChildStatus.CANCELLED, "Cancelled before start"
                )
            # 废弃代码（2026-09-21）：
            # active_siblings = [child for child in tree.list_active() if child.session_id != session]
            # QUEUED 兄弟会被算进并发槽，两个 task 同时派发时第一个会误杀。
            # 只统计已经 RUNNING 的兄弟，并在同一把锁里升到 RUNNING。
            running_siblings = [
                child
                for child in self._tree_for(session.root_session_id).list_active()
                if child.session_id != session.session_id
                and child.status == ChildStatus.RUNNING
            ]
            concurrent_limit = session.policy.budget.max_concurrent_children
            if len(running_siblings) >= concurrent_limit:
                message = (
                    f"Concurrency limit exceeded: {len(running_siblings)}/"
                    f"{concurrent_limit} active"
                )
                transition(session, ChildStatus.FAILED)
                self._emit("child_session/failed", {
                    "session_id": session.session_id,
                    "status": "failed",
                    "error": {"code": "budget.concurrency", "message": message},
                })
                return self._terminal_result(
                    request,
                    session,
                    ChildStatus.FAILED,
                    message,
                    error=ErrorRecord(code="budget.concurrency", message=message),
                )

        self._emit("child_session/started", {"session_id": session.session_id})

        # The manager owns leases for its entire Primary tree.  A child never
        # self-asserts a lease id: requested paths are acquired atomically here
        # and the authoritative id is frozen into the policy snapshot.
        if session.policy.workspace.mode == WorkspaceMode.LEASED_WRITE:
            try:
                paths = session.policy.workspace.leased_paths
                if not paths:
                    raise WorkspaceError(
                        "leased_write requires at least one leased path",
                        code="workspace.no_scope",
                    )
                lease = self._lease_manager.acquire(session.session_id, paths)
                session.policy = replace(
                    session.policy,
                    workspace=replace(session.policy.workspace, lease_id=lease.lease_id),
                )
            except WorkspaceError as exc:
                from protocol.subagents import ErrorRecord

                transition(session, ChildStatus.FAILED)
                self._emit("child_session/failed", {
                    "session_id": session.session_id,
                    "status": "failed",
                    "error": {"code": exc.code, "message": str(exc)},
                })
                return self._terminal_result(
                    request,
                    session,
                    ChildStatus.FAILED,
                    str(exc),
                    error=ErrorRecord(code=exc.code, message=str(exc)),
                )

        # Build isolated runtime (via ChildRuntime facade for shutdown semantics)
        child_rt = create_child_runtime(
            definition,
            session,
            self._lease_manager,
            self.workspace_root,
        )

        try:
            # 废弃代码（2026-09-21）：task_prompt = context.task if context else ""
            # 废弃代码（2026-09-21）：
            # task_prompt = (request.prompt or "").strip() or (
            #     context.task if context else ""
            # )
            # 有 ContextEnvelope 时曾丢弃 request.prompt，或在 prompt 为空时
            # 回退到 description（explore codebase）。禁止再引用 context.task。
            task_prompt = (request.prompt or "").strip()

            # Execute (placeholder — B7 wires the real provider loop)
            result = await child_rt.execute(task_prompt)

            # Persist result and transition to terminal
            session.result = result
            terminal_status = self._status_from_result(result.status)
            try:
                transition(session, ChildStatus.FINALIZING)
                transition(session, terminal_status)
            except Exception:
                pass

            self._emit(f"child_session/{terminal_status.value}", {
                "session_id": session.session_id,
                "status": terminal_status.value,
                "summary": result.summary,
                "artifacts": [asdict(item) for item in result.artifacts],
                "evidence": [asdict(item) for item in result.evidence],
                "error": (
                    {
                        "code": result.error.code,
                        "message": result.error.message,
                        "details": dict(result.error.details),
                    }
                    if result.error is not None
                    else None
                ),
                "usage": {
                    "steps": result.usage.steps,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cache_hit_tokens": result.usage.cache_hit_tokens,
                    "wall_time_ms": result.usage.wall_time_ms,
                    "retry_count": result.usage.retry_count,
                    "reporting_status": result.usage.reporting_status,
                },
            })

            # Reconstruct TaskResult with correct request/session ids
            return TaskResult(
                request_id=request.request_id,
                child_session_id=session.session_id,
                status=terminal_status,
                summary=result.summary,
                artifacts=result.artifacts,
                evidence=result.evidence,
                usage=result.usage,
                error=result.error,
                telemetry=result.telemetry,
            )

        except asyncio.CancelledError:
            # Parent cancellation
            child_rt.shutdown()
            transition(session, ChildStatus.CANCELLED)
            return self._terminal_result(request, session, ChildStatus.CANCELLED, "Cancelled during execution")
        except Exception as exc:
            child_rt.shutdown()
            from protocol.subagents import ErrorRecord

            try:
                transition(session, ChildStatus.FAILED)
            except Exception:
                pass
            return self._terminal_result(
                request,
                session,
                ChildStatus.FAILED,
                f"Runtime failure: {exc}",
                error=ErrorRecord(code="internal_error", message=str(exc)),
            )
        finally:
            self._lease_manager.release_all_for_session(session.session_id)

    def _status_from_result(self, status: ChildStatus) -> ChildStatus:
        """Map a runtime status to a terminal session status."""
        if status in (ChildStatus.COMPLETED, ChildStatus.FAILED, ChildStatus.CANCELLED,
                      ChildStatus.DENIED, ChildStatus.TIMED_OUT):
            return status
        return ChildStatus.FAILED

    def _terminal_result(
        self,
        request: TaskRequest,
        session: ChildSession,
        status: ChildStatus,
        summary: str,
        *,
        error=None,
    ) -> TaskResult:
        """Build a terminal TaskResult for a session."""

        return TaskResult(
            request_id=request.request_id,
            child_session_id=session.session_id,
            status=status,
            summary=summary,
            usage=UsageRecord(),
            error=error,
        )
