"""Stdio JSON-RPC appserver (Phase 2 P4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .agent_host import AgentHost
from .approval import JsonRpcApproval
from .emitter import model_to_notification
from .jsonrpc import (
    is_client_request,
    is_client_response,
    parse_line,
    write_message,
    write_message_sync,
)
from .lifecycle import InstanceLock, mark_incomplete_recovery_required
from .project_routes import handle_project_rpc
from .project_store import ProjectStore
from .runtime import install_tui_context_hook
from .workspace import PathBoundaryError, assert_exists, assert_inside_workspace, canonicalize
from .execution import ExecutionStore
from .approval_router import ApprovalRouter
from .permission import PermissionStore
from .preview import preview_file, list_tree, prepare_open_external
from .review import ReviewError, ReviewService
from .review_comments import ReviewCommentService
from .checkpoint_rewind import CheckpointRewindError, CheckpointRewindService, project_session_items
from .usage_tracker import UsageTracker
from .thread_fork import ThreadForkError, ThreadForkService
from .plan_files import PlanFileError, PlanFileService
from .needs_input import NeedsInputClassifier
from .tool_registry_capability import CapabilityDenied, ToolRegistryCapability
from .side_chat import SideChatError, SideChatService
from .followup_scanner import FollowupScanner
from .sessions import SessionStore
from .capabilities import CapabilityError, CapabilityService
from .recovery import RecoveryError, RecoveryService
from .release import ReleaseService
from .cli_hub_service import CliHubError, CliHubService
from .schedule_service import ScheduleError, ScheduleService
from .trash_service import TrashError, TrashService
from .plugin_service import PluginError, PluginService
from .settings import SettingsError, SettingsService, handshake_model_summaries, summarize_model
from .worktree_service import WorktreeError, WorktreeService
from .task_store import DesktopTaskStore
from .watchdog import ActiveJob, WatchdogState, heartbeat_interval_seconds, stall_timeout_seconds

try:
    from ..core.safety.approval import set_approval_broker
    from ..protocol.errors import JSONRPC_STABLE_CODE, error_payload
    from ..protocol.handshake import (
        CapabilitySnapshot,
        InitializeResult,
        ModelProviderSummary,
        PackageCompatibility,
        PermissionProfileSummary,
    )
    from ..protocol.notifications import (
        InitializedNotification,
        JobStatusUpdate,
        ProcessFailed,
        ProcessShutdown,
        ProcessStarted,
        ProgressUpdate,
        RecoveryRequired,
        ServerHeartbeat,
        WorkspaceChanged,
        ExecutionItem,
    )
    from ..protocol.version import (
        APPSERVER_VERSION,
        PROTOCOL_VERSION,
        PROTOCOL_VERSION_MAX,
        PROTOCOL_VERSION_MIN,
        protocol_version_compatible,
    )
except ImportError:
    from core.safety.approval import set_approval_broker
    from protocol.errors import JSONRPC_STABLE_CODE, error_payload
    from protocol.handshake import (
        CapabilitySnapshot,
        InitializeResult,
        ModelProviderSummary,
        PackageCompatibility,
        PermissionProfileSummary,
    )
    from protocol.notifications import (
        InitializedNotification,
        JobStatusUpdate,
        ProcessFailed,
        ProcessShutdown,
        ProcessStarted,
        ProgressUpdate,
        RecoveryRequired,
        ServerHeartbeat,
        WorkspaceChanged,
        ExecutionItem,
    )
    from protocol.version import (
        APPSERVER_VERSION,
        PROTOCOL_VERSION,
        PROTOCOL_VERSION_MAX,
        PROTOCOL_VERSION_MIN,
        protocol_version_compatible,
    )

_logger = logging.getLogger(__name__)

_DEFAULT_PROMPT_TIMEOUT_SECONDS = 600.0
_DEFAULT_WARM_TIMEOUT_SECONDS = 180.0
_MAX_CONCURRENT_PROMPTS = 256


def _model_provider_summaries() -> list[ModelProviderSummary]:
    try:
        rows = handshake_model_summaries()
    except Exception:
        return []
    return [
        ModelProviderSummary(
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            model_context_window=row.get("model_context_window"),
            model_max_output_tokens=row.get("resolved_max_tokens"),
            limit_source=row.get("limit_source"),
            is_fallback=bool(row.get("is_fallback")),
            warning=row.get("warning"),
        )
        for row in rows
    ]


def _permission_profiles() -> list[PermissionProfileSummary]:
    """Advertise PhaseG-B7 profiles. full_access is visible but not selectable."""
    return [
        PermissionProfileSummary(
            profile_id=row["profile_id"],
            selectable=bool(row["selectable"]),
            description=str(row["description"]),
        )
        for row in PermissionStore(persistent=False).snapshot()["profiles"]
    ]
_SHUTDOWN_PROMPT_WAIT_SECONDS = 30.0
_REPLAY_EVENT_METHODS = {
    "event/task_started",
    "event/task_complete",
    "event/error",
    "event/plan",
    "event/step",
    "event/progress",
    "event/job_status",
    "event/tool_begin",
    "event/tool_end",
    "event/execution",
    "event/token_usage",
    "event/final",
    "event/done",
    "event/recovery_started",
    "event/recovery_analyzing",
    "event/recovery_attempt",
    "event/recovery_resolved",
    "event/recovery_exhausted",
    "event/recovery_required",
    "review/started",
    "review/progress",
    "review/finding",
    "review/completed",
    "review/stale",
    "review/failed",
    "review/cancelled",
}
_MAX_REPLAY_TEXT = 24_000


class AppServer:
    """Headless JSON-RPC server over stdin/stdout."""

    def __init__(self, *, stub: bool = False) -> None:
        install_tui_context_hook()
        self._stub = stub
        self._shutdown = False
        self._initialized = False
        # Stub servers are used by contract tests and the local fake transport;
        # they must never read or mutate a user's persistent Desktop history.
        # The production appserver keeps the durable store across restarts.
        self._task_store = DesktopTaskStore(persistent=not stub)
        self._projects = ProjectStore(persistent=not stub)
        self._instance_lock = InstanceLock()
        self._instance_blocked: str | None = None
        self._recovered_sessions: list[tuple[str, str]] = []
        should_lock = (not stub) or bool(os.environ.get("RXYCODE_APPSERVER_LOCK"))
        if should_lock:
            ok, reason = self._instance_lock.acquire()
            if not ok and os.environ.get("RXYCODE_APPSERVER_PREEMPT") == "1":
                ok, reason = self._instance_lock.preempt_and_acquire()
            if not ok:
                self._instance_blocked = reason
            else:
                self._recovered_sessions = mark_incomplete_recovery_required(
                    self._task_store
                )
        elif self._task_store.persistent:
            self._recovered_sessions = mark_incomplete_recovery_required(
                self._task_store
            )
        self._sessions = SessionStore(task_store=self._task_store)
        self._execution = ExecutionStore(on_change=self._schedule_execution_event)
        self._permissions = PermissionStore(persistent=not stub)
        self._approval_router = ApprovalRouter()
        self._reviews = ReviewService()
        self._review_comments = ReviewCommentService(self._reviews)
        self._checkpoint_rewind = CheckpointRewindService(self._reviews, self._sessions)
        self._usage_tracker = UsageTracker(context_window_lookup=self._usage_context_window)
        self._thread_fork = ThreadForkService(self._sessions)
        self._plan_files = PlanFileService()
        self._needs_input = NeedsInputClassifier()
        self._tool_capability = ToolRegistryCapability()
        self._side_chat = SideChatService(self._sessions)
        self._followup = FollowupScanner()
        self._worktrees = WorktreeService()
        self._settings = SettingsService(persistent=not stub)
        self._cli_hub = CliHubService()
        self._capabilities = CapabilityService(
            persistent=not stub,
            execution_store=self._execution,
            review_service=self._reviews,
            cli_lister=self._cli_hub.tool_metadata,
        )
        self._recovery = RecoveryService(persistent=not stub, task_store=self._task_store)
        self._release = ReleaseService()
        self._schedule = ScheduleService(
            persistent=not stub,
            sessions=self._sessions,
            permissions=self._permissions,
            task_store=self._task_store,
        )
        self._schedule_task: asyncio.Task[Any] | None = None
        self._trash = TrashService(self._sessions)
        self._plugins = PluginService(
            persistent=not stub,
            capabilities=self._capabilities,
            permission_store=self._permissions,
        )
        self._plugins.attach_to_capabilities()
        self._session_hosts: dict[str, AgentHost] = {}
        self._watchdog = WatchdogState()
        self._started_at = time.monotonic()
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._next_server_id = 1
        self._pending_server: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._approval = JsonRpcApproval(self._send_server_request, timeout=120.0)
        set_approval_broker(self._approval)
        self._active_session_id = "latest"
        self._prompt_tasks: set[asyncio.Task[Any]] = set()
        # Worker notifications arrive synchronously from the AsyncRpcPipe
        # reader, but stdout writes are asynchronous. A single FIFO writer is
        # required so a slow tool_end cannot be overtaken by recovery/error.
        self._notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._notification_writer: asyncio.Task[Any] | None = None
        self._notification_write_failures: list[BaseException] = []
        self._job_tasks: dict[str, asyncio.Task[Any]] = {}
        self._resolved_jobs: set[str] = set()
        self._thinking_expanded = False
        self._inflight_turns: dict[str, str] = {}

    def _ensure_notification_writer(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._notification_writer is None or self._notification_writer.done():
            self._notification_writer = loop.create_task(self._notification_writer_loop())

    async def _notification_writer_loop(self) -> None:
        while True:
            message = await self._notification_queue.get()
            try:
                await write_message(message)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                self._notification_write_failures.append(exc)
            finally:
                self._notification_queue.task_done()

    def _schedule_execution_event(self, record: Any) -> None:
        self._schedule_notification(
            model_to_notification(
                ExecutionItem(
                    session_id=record.session_id,
                    task_id=record.task_id,
                    kind=record.kind,
                    origin=record.origin,
                    name=record.name,
                    status=record.status,
                    args_summary=record.args_summary,
                    risk=record.risk,
                    cwd=record.cwd,
                    env_summary=dict(record.env_summary),
                    exit_code=record.exit_code,
                    unread=record.unread,
                    truncated=record.truncated,
                )
            )
        )

    def route_approval(self, request_id: str, *, risk: str = "", action: str = "") -> str:
        """B7 event presentation: card vs modal. High-risk always modal."""
        return self._approval_router.route(
            request_id,
            risk=risk,
            preset=self._permissions.ui_preset,
            action=action,
        )

    def _schedule_notification(self, message: dict[str, Any]) -> None:
        self._ensure_notification_writer()
        self._notification_queue.put_nowait(message)

    def _usage_context_window(self, session_id: str) -> int | None:
        record = self._sessions.get(session_id)
        if record is None or not record.model_id:
            return None
        try:
            summary = summarize_model(
                provider_id=record.provider_id or "unknown",
                model_id=record.model_id,
            )
        except Exception:
            return None
        window = summary.get("model_context_window")
        return int(window) if isinstance(window, int) and window > 0 else None

    def _maybe_emit_needs_input(self, event: dict[str, Any]) -> dict[str, Any] | None:
        payload = self._needs_input.emit_payload(event)
        if payload is None or payload.get("kind") != "needs_input":
            return payload
        self._schedule_notification(
            {
                "jsonrpc": "2.0",
                "method": "event/agent_needs_input",
                "params": payload,
            }
        )
        return payload

    def _emit_agent_usage(
        self,
        session_id: str,
        usage: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        payload = self._usage_tracker.ingest(session_id, usage, reason=reason)
        self._schedule_notification(
            {
                "jsonrpc": "2.0",
                "method": "event/agent_usage",
                "params": payload,
            }
        )
        return payload

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def _host_for_session(self, session_id: str) -> AgentHost:
        host = self._session_hosts.get(session_id)
        if host is not None and host.alive() and not host.degraded:
            return host
        if host is not None:
            await host.kill_async()
        record = self._sessions.get(session_id)
        if record is None:
            raise RuntimeError(f"unknown session: {session_id}")
        project_root = Path(__file__).resolve().parents[1]
        _logger.info(
            "Starting agent worker for session %s (stub=%s, workspace=%s)",
            session_id,
            self._stub,
            record.workspace_root,
        )
        host = AgentHost(
            session_id=session_id,
            workspace_root=record.workspace_root,
            model_id=record.model_id,
            stub=self._stub,
            project_root=project_root,
            forward_server_request=self._send_server_request,
            main_loop=asyncio.get_running_loop(),
        )
        await host.start()
        self._session_hosts[session_id] = host
        return host

    async def _kill_session_host(self, session_id: str) -> None:
        host = self._session_hosts.pop(session_id, None)
        if host is not None:
            await host.kill_async()

    async def _emit_model(self, model: BaseModel) -> None:
        message = model_to_notification(model)
        self._persist_notification(message)
        self._schedule_notification(message)
        await self._drain_emit_writes()

    def _persist_notification(self, message: dict[str, Any]) -> None:
        """Persist replayable session events without coupling the renderer to Python.

        Host notifications and typed server notifications use two different
        transport paths, so both call this single synchronous adapter.  The
        store is outside the workspace and receives a redacted JSON-safe copy;
        credentials and authorization material never enter the replay log.
        """
        if not isinstance(message, dict):
            return
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        try:
            self._recovery.observe_event(method, params)
        except Exception:
            pass
        self._maybe_emit_needs_input({"method": method, "params": params})
        if method.startswith("child_session/") or method.startswith("approval/"):
            persist_event = True
        else:
            persist_event = method in _REPLAY_EVENT_METHODS
        if not persist_event:
            # Streaming deltas are intentionally not written one by one. The
            # final event and tool/recovery records are sufficient to rebuild
            # a completed task, while skipping deltas avoids both prompt-like
            # content in the durable task index and an fsync per token.
            try:
                self._recovery.observe_event(method, params)
            except Exception:
                pass
            return
        child_id = params.get("child_session_id")
        sid = params.get("session_id")
        parent_id = params.get("parent_session_id")
        root_id = params.get("root_session_id")
        if isinstance(child_id, str) and child_id:
            session_id = child_id
        elif (
            isinstance(sid, str)
            and sid
            and isinstance(parent_id, str)
            and parent_id
            and sid != parent_id
        ):
            session_id = sid
        elif isinstance(sid, str) and sid:
            session_id = sid
        elif isinstance(root_id, str) and root_id:
            session_id = root_id
        else:
            return
        if isinstance(parent_id, str) and parent_id and parent_id != session_id:
            parent = self._sessions.get(parent_id)
            expected_root = (
                (parent.root_session_id if parent is not None else None) or parent_id
            )
            claimed_root = params.get("root_session_id")
            if isinstance(claimed_root, str) and claimed_root and claimed_root != expected_root:
                claimed_root = expected_root
            budget = params.get("budget") if isinstance(params.get("budget"), dict) else None
            permission = (
                params.get("permission_snapshot")
                if isinstance(params.get("permission_snapshot"), dict)
                else params.get("permission")
            )
            if not isinstance(permission, dict):
                permission = None
            self._sessions.ensure_child(
                session_id=session_id,
                parent_session_id=parent_id,
                root_session_id=str(claimed_root or expected_root),
                workspace_root=parent.workspace_root if parent is not None else Path("."),
                agent_id=params.get("agent_id") if isinstance(params.get("agent_id"), str) else None,
                trigger=params.get("trigger") if isinstance(params.get("trigger"), str) else None,
                budget=budget,
                permission_snapshot=permission,
                lease_id=params.get("lease_id") if isinstance(params.get("lease_id"), str) else None,
            )

        def redact(value: Any, key: str = "") -> Any:
            lowered = key.lower()
            if any(secret in lowered for secret in ("api_key", "apikey", "authorization", "password", "secret")):
                return "[REDACTED]"
            if isinstance(value, dict):
                return {str(k): redact(v, str(k)) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(item, key) for item in value]
            if isinstance(value, str):
                safe = re.sub(
                    r"(?i)(authorization|api[_-]?key|password|secret|access[_-]?token)"
                    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
                    lambda match: f"{match.group(1)}=[REDACTED]",
                    value,
                )
                safe = re.sub(
                    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}",
                    "Bearer [REDACTED]",
                    safe,
                )
                safe = re.sub(
                    r"(?i)(--(?:api-key|token|password|secret))\s+[^\s]+",
                    r"\1 [REDACTED]",
                    safe,
                )
                if len(safe) > _MAX_REPLAY_TEXT:
                    safe = safe[:_MAX_REPLAY_TEXT] + "\n[replay text truncated]"
                return safe
            try:
                json.dumps(value)
                return value
            except (TypeError, ValueError):
                return str(value)

        safe_params = redact(params)
        try:
            self._task_store.append_event(
                session_id,
                {"method": method, "params": safe_params},
            )
        except Exception:
            _logger.exception("failed to persist session event for %s", session_id)

        if method.endswith("approval_required") or method.startswith("approval/"):
            target = (
                safe_params.get("task_id")
                or safe_params.get("call_id")
                or safe_params.get("approval_id")
            )
            if isinstance(target, str) and self._execution.get(target) is not None:
                self._execution.set_waiting(target)
            else:
                running = [
                    item
                    for item in self._execution.list(session_id)
                    if item.status == "running" and item.session_id == session_id
                ]
                if len(running) == 1:
                    self._execution.set_waiting(running[0].task_id)
        if method == "event/tool_begin":
            call_id = str(safe_params.get("call_id") or uuid.uuid4().hex)
            tool_name = str(safe_params.get("tool_name") or "tool")
            try:
                self._tool_capability.check(session_id, tool_name)
            except CapabilityDenied as exc:
                self._schedule_notification(
                    {
                        "jsonrpc": "2.0",
                        "method": "event/error",
                        "params": {
                            "session_id": session_id,
                            "message": exc.message,
                            "error_code": exc.code,
                            "tool_name": tool_name,
                            "call_id": call_id,
                        },
                    }
                )
                return
            from .execution import risk_for

            started = self._execution.start(
                session_id=session_id,
                name=tool_name,
                kind="tool",
                origin="agent",
                arguments=safe_params.get("arguments"),
                risk=risk_for(tool_name),
                parent_session_id=parent_id if isinstance(parent_id, str) else None,
                task_id=call_id,
            )
            self._schedule_execution_event(started)
        elif method == "event/tool_end":
            call_id = str(safe_params.get("call_id") or "")
            if call_id and self._execution.get(call_id) is not None:
                ok = bool(safe_params.get("ok", True))
                finished = self._execution.finish(
                    call_id,
                    "succeeded" if ok else "failed",
                    stdout=str(safe_params.get("summary") or ""),
                )
                self._schedule_execution_event(finished)
        if method == "event/job_status":
            state = safe_params.get("state")
            if isinstance(state, str):
                self._sessions.update_status(
                    session_id,
                    "queued" if state in {"submitted", "queued"} else state,
                )
        elif method == "event/done":
            state = safe_params.get("status")
            if isinstance(state, str):
                self._sessions.update_status(session_id, state)
            record = self._sessions.get(session_id)
            if record is not None:
                self._followup.scan(
                    record.workspace_root,
                    turn_id=str(safe_params.get("turn_id") or session_id),
                )
        elif method in {
            "child_session/failed",
            "child_session/cancelled",
            "child_session/orphaned",
            "child_session/completed",
        }:
            mapped = {
                "child_session/failed": "failed",
                "child_session/cancelled": "cancelled",
                "child_session/orphaned": "orphaned",
                "child_session/completed": "succeeded",
            }[method]
            self._sessions.update_status(session_id, mapped)
            if method == "child_session/orphaned" and isinstance(
                safe_params.get("reason"), str
            ):
                child = self._sessions.get(session_id)
                if child is not None:
                    child.orphan_reason = str(safe_params["reason"])
                    self._sessions._persist(child)
        elif method in {"event/token_usage", "event/final"}:
            usage = {
                "input_tokens": safe_params.get("input_tokens"),
                "output_tokens": safe_params.get("output_tokens"),
                "cache_hit_tokens": safe_params.get("cache_hit_tokens"),
                "cache_write_tokens": safe_params.get("cache_write_tokens"),
                "cache_hit_rate": safe_params.get("cache_hit_rate"),
                "reporting_status": safe_params.get("reporting_status", "not_reported"),
            }
            self._sessions.update_usage(session_id, usage)
            self._emit_agent_usage(session_id, usage, reason="token_usage")
        if method == "event/tool_end":
            self._emit_agent_usage(session_id, {}, reason="tool")

    async def _drain_emit_writes(self) -> list[BaseException]:
        """Wait for the notification FIFO, surfacing any write failures.

        Called before every
        terminal response (success, error, timeout, cancel) so the result never
        overtakes already-emitted notifications; the caller should degrade the
        watchdog when the returned list is non-empty.
        """
        await asyncio.wait_for(self._notification_queue.join(), timeout=10.0)
        failures = list(self._notification_write_failures)
        self._notification_write_failures.clear()
        if failures:
            _logger.error(
                "lost %d emit write(s): %s", len(failures), failures[0]
            )
        return failures

    async def _emit_job_state(self, session_id: str, job_id: str, state: str) -> None:
        self._sessions.update_status(
            session_id,
            "queued" if state in {"submitted", "queued"} else state,
        )
        await self._emit_model(
            JobStatusUpdate(session_id=session_id, job_id=job_id, state=state)
        )

    async def _drain_emit_and_degrades(self, job_id: str) -> None:
        """Drain pending emit writes and degrade the watchdog on failure.

        Used by every terminal job path so a lost stream event is reflected in
        /status regardless of how the job ends.
        """
        write_failures = await self._drain_emit_writes()
        if write_failures:
            self._watchdog.degrade(f"emit write failure during job {job_id}")

    async def _respond(self, request_id: Any, result: Any) -> None:
        await write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _respond_error(
        self, request_id: Any, code: int, message: str, data: Any = None
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        payload: dict[str, Any] = {}
        stable = JSONRPC_STABLE_CODE.get(code)
        if stable:
            payload.update(error_payload(stable, server_version=APPSERVER_VERSION))
        if isinstance(data, dict):
            payload.update(data)
        elif data is not None:
            payload["details"] = data
        if payload:
            error["data"] = payload
        await write_message({"jsonrpc": "2.0", "id": request_id, "error": error})

    async def _send_server_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = self._next_server_id
        self._next_server_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_server[request_id] = future
        try:
            await write_message(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            return await future
        finally:
            # Always drop the pending future, even if write_message raises
            # before the response arrives — otherwise it would leak.  Cancel an
            # unfinished future so no dangling await remains.
            self._pending_server.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _resolve_server_response(self, message: dict[str, Any]) -> bool:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return False
        future = self._pending_server.get(request_id)
        if future is None or future.done():
            return False
        if "error" in message:
            error = message.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", "server request failed"))
            else:
                detail = str(error or "server request failed")
            future.set_exception(RuntimeError(detail))
            return True
        result = message.get("result")
        if not isinstance(result, dict):
            result = {}
        future.set_result(result)
        return True

    async def _fail_job(
        self,
        *,
        session_id: str,
        job_id: str,
        request_id: Any,
        code: int,
        message: str,
        kill_host: bool = False,
        degrade_reason: str | None = None,
    ) -> None:
        if job_id in self._resolved_jobs:
            return
        # Drain any in-flight emit writes so a lost stream event surfaces in
        # /status regardless of how the job ends (stall, error, cancel, ...).
        await self._drain_emit_and_degrades(job_id)
        self._resolved_jobs.add(job_id)
        self._watchdog.finish_job(job_id)
        self._job_tasks.pop(job_id, None)
        if degrade_reason:
            self._watchdog.degrade(degrade_reason)
        await self._emit_job_state(session_id, job_id, "failed")
        turn_key = self._inflight_turns.get(session_id) or str(request_id or "")
        if turn_key:
            status = "cancelled" if "cancel" in message.lower() else "failed"
            if "timed out" in message.lower() or "timeout" in message.lower():
                status = "timeout"
            self._sessions.remember_turn(
                session_id,
                turn_key,
                {"status": status, "text": "", "error": message, "code": code},
            )
        if request_id is not None:
            await self._respond_error(request_id, code, message)
        if kill_host:
            await self._kill_session_host(session_id)

    async def _handle_stalled_job(self, stalled: ActiveJob) -> None:
        reason = (
            f"job stalled >{stall_timeout_seconds()}s (session {stalled.session_id})"
        )
        # Save the task *before* _fail_job (which pops it from _job_tasks).
        task = self._job_tasks.get(stalled.job_id)
        await self._fail_job(
            session_id=stalled.session_id,
            job_id=stalled.job_id,
            request_id=stalled.request_id,
            code=-32004,
            message=reason,
            kill_host=True,
            degrade_reason=reason,
        )
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _handle_initialize(self, params: dict[str, Any], request_id: Any) -> None:
        if self._shutdown:
            await self._respond_error(request_id, -32009, "appserver is closed")
            return
        if not str(params.get("client_name") or "").strip():
            await self._respond_error(
                request_id,
                -32007,
                "client_name is required",
                error_payload(
                    "CONFIGURATION_MISSING",
                    server_version=APPSERVER_VERSION,
                    details={"field": "client_name"},
                ),
            )
            return
        client_version = str(params.get("protocol_version", ""))
        if not protocol_version_compatible(client_version):
            await self._respond_error(
                request_id,
                -32006,
                "protocol version incompatible",
                error_payload(
                    "PROTOCOL_MISMATCH",
                    server_version=APPSERVER_VERSION,
                    details={
                        "client_protocol_version": client_version,
                        "protocol_min": PROTOCOL_VERSION_MIN,
                        "protocol_max": PROTOCOL_VERSION_MAX,
                    },
                ),
            )
            return
        self._initialized = True
        recovery_ok = True
        try:
            self._recovery.restore_after_restart(self._task_store)
            self._recovery.reclaim_orphans(set(self._sessions._sessions))
            self._schedule.reclaim_orphans()
            if self._schedule_task is None or self._schedule_task.done():
                from .schedule_service import schedule_loop

                self._schedule_task = asyncio.create_task(schedule_loop(self._schedule, asyncio.sleep, 30.0))
        except Exception as exc:
            recovery_ok = False
            _logger.error("recovery restore failed: %s", exc)
        result = InitializeResult(
            capabilities={
                "sessions": True,
                "approval": True,
                "models": True,
                "credentials": True,
                "settings": True,
                "capabilities": True,
                "recovery": True,
                "notifications": True,
                "recovery_restore_ok": recovery_ok,
            },
            capability_snapshot=CapabilitySnapshot(thread_fork=True),
            model_providers=_model_provider_summaries(),
            permission_profiles=_permission_profiles(),
            package=PackageCompatibility(**{
                key: self._release.compatibility()[key]
                for key in (
                    "platform",
                    "platforms",
                    "appserver_version",
                    "protocol_version",
                    "schema_digest",
                    "python",
                    "compatible",
                    "runtimes",
                )
            }),
        )
        await self._respond(request_id, result.model_dump(by_alias=True))
        await self._emit_model(
            InitializedNotification(
                protocol_version=PROTOCOL_VERSION,
                server_version=APPSERVER_VERSION,
            )
        )

    async def _handle_session_new(self, params: dict[str, Any], request_id: Any) -> None:
        workspace = params.get("workspace_root")
        if not isinstance(workspace, str) or not workspace.strip():
            await self._respond_error(request_id, -32602, "workspace_root is required")
            return
        try:
            workspace = str(assert_exists(canonicalize(workspace)))
            if self._projects.get(workspace) is None:
                self._projects.add(workspace)
        except PathBoundaryError as exc:
            await self._respond_error(
                request_id,
                -32011,
                exc.message,
                {"error_code": exc.code, "retryable": False},
            )
            return
        model_id = str(params.get("model") or "").strip() or None
        provider_value = str(params.get("provider_id") or "").strip()
        provider_id: str | None = provider_value or None
        # Do not synchronously discover every configured model while creating
        # a task.  Model discovery can load provider metadata and used to make
        # the ``+`` button look frozen before the session response was sent.
        # The renderer already has the shared model snapshot; callers that
        # need a task-specific model may pass ``model`` explicitly.  The
        # The background worker receives the task-scoped model when one was
        # selected, and falls back to the configured active model otherwise.
        record = self._sessions.create(
            Path(workspace), model_id=model_id, provider_id=provider_id
        )
        self._active_session_id = record.session_id
        await self._respond(
            request_id,
            {
                "session_id": record.session_id,
                "workspace_root": str(record.workspace_root),
                "model_id": record.model_id,
                "provider_id": record.provider_id,
            },
        )
        # The task response is already durable and immediate. Give the
        # renderer an explicit lifecycle signal before the background worker
        # warm starts, so a new task never looks like an unresponsive click.
        await self._emit_model(
            ProgressUpdate(
                session_id=record.session_id,
                text="Preparing Agent worker…",
            )
        )
        # Warm the first worker after the durable session response. The UI can
        # render the new task immediately while bootstrap happens in the
        # background, removing the cold-start cost from the first prompt.
        if not self._stub:
            warm = asyncio.create_task(self._warm_session_host(record.session_id))
            self._prompt_tasks.add(warm)
            warm.add_done_callback(self._prompt_tasks.discard)

    async def _warm_session_host(self, session_id: str) -> None:
        try:
            async with self._session_lock(session_id):
                host = await self._host_for_session(session_id)
            await host.ensure_bootstrapped(timeout=_DEFAULT_WARM_TIMEOUT_SECONDS)
            await self._emit_model(
                ProgressUpdate(
                    session_id=session_id,
                    text="Agent worker ready",
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Warming is an optimization. A later prompt still owns the
            # authoritative error path and can create a fresh worker.
            _logger.warning("background worker warm failed for %s", session_id, exc_info=True)

    async def _run_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: Any,
        job_id: str,
        timeout_seconds: float | None,
        mode: str = "build",
        thinking_expanded: bool | None = None,
        permission_mode: str | None = None,
        turn_key: str | None = None,
    ) -> None:
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return

        wall_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else _DEFAULT_PROMPT_TIMEOUT_SECONDS
        )
        expand = (
            self._thinking_expanded
            if thinking_expanded is None
            else bool(thinking_expanded)
        )
        self._thinking_expanded = expand

        current = asyncio.current_task()
        if current is not None:
            self._job_tasks[job_id] = current

        try:
            async with self._session_lock(session_id):
                await self._emit_job_state(session_id, job_id, "submitted")
                await self._emit_job_state(session_id, job_id, "running")

                run_id = uuid.uuid4().hex
                host = await self._host_for_session(session_id)
                if not getattr(host, "bootstrapped", False):
                    await self._emit_model(
                        ProgressUpdate(
                            session_id=session_id,
                            text="Starting Agent worker…",
                        )
                    )

                def emit_message(message: dict[str, Any]) -> None:
                    self._watchdog.touch_job(job_id)
                    if message.get("method") == "event/heartbeat":
                        # Worker liveness is an appserver concern, not a
                        # renderer event. Do not leak a synthetic activity row
                        # or append it to the replay log.
                        return
                    self._persist_notification(message)
                    try:
                        asyncio.get_running_loop()
                    except RuntimeError:
                        # Legacy path: called from the host's reader thread.
                        write_message_sync(message)
                    else:
                        # Async path: called from the AsyncRpcPipe reader task
                        # on the event loop — schedule the write via to_thread
                        # so stdout backpressure never blocks the loop.  Track
                        # the task so the result can be ordered after all
                        # already-emitted notifications.
                        self._schedule_notification(message)

                async def _execute_prompt() -> dict[str, Any]:
                    host._emit = emit_message
                    await host.ensure_bootstrapped(timeout=wall_timeout)
                    await self._emit_model(
                        ProgressUpdate(
                            session_id=session_id,
                            text="Waiting for model response…",
                        )
                    )
                    # Bootstrap is a separate cold-start phase. It has the
                    # outer prompt timeout, but must not be judged as a
                    # stalled *running* job before the worker can emit its
                    # liveness heartbeat.
                    self._watchdog.register_job(job_id, session_id, request_id)
                    return await host.run_prompt(
                        text=text,
                        run_id=run_id,
                        timeout=wall_timeout,
                        emit=emit_message,
                        mode=mode,
                        thinking_expanded=expand,
                        permission_mode=permission_mode,
                    )

                try:
                    payload = await asyncio.wait_for(
                        _execute_prompt(), timeout=wall_timeout
                    )
                except asyncio.TimeoutError:
                    await self._fail_job(
                        session_id=session_id,
                        job_id=job_id,
                        request_id=request_id,
                        code=-32000,
                        message=f"prompt timed out after {wall_timeout}s",
                        kill_host=True,
                        degrade_reason=(
                            f"prompt timed out after {wall_timeout}s "
                            f"(session {session_id})"
                        ),
                    )
                    return
                except asyncio.CancelledError:
                    # Stop the worker-side prompt so it cannot keep running
                    # (and emitting) after the job was cancelled.
                    host = self._session_hosts.get(session_id)
                    if host is not None and host.alive():
                        with contextlib.suppress(Exception):
                            await host.interrupt(timeout=2.0)
                    if job_id not in self._resolved_jobs:
                        await self._fail_job(
                            session_id=session_id,
                            job_id=job_id,
                            request_id=request_id,
                            code=-32004,
                            message="prompt cancelled",
                        )
                    raise
                except Exception as exc:
                    await self._fail_job(
                        session_id=session_id,
                        job_id=job_id,
                        request_id=request_id,
                        code=-32000,
                        message=str(exc),
                        kill_host=True,
                    )
                    return
                finally:
                    if job_id not in self._resolved_jobs:
                        self._watchdog.finish_job(job_id)

                if job_id in self._resolved_jobs:
                    return

                status = str(payload.get("status", "failed"))
                if status != "succeeded":
                    await self._emit_job_state(session_id, job_id, "failed")
                else:
                    self._sessions.update_status(session_id, "succeeded")

                # Order the result after all already-emitted notifications so
                # the client never observes the result arrive before them, and
                # degrade the watchdog if any stream event was lost.
                await self._drain_emit_and_degrades(job_id)

                result = {
                    "run_id": payload.get("run_id", run_id),
                    "status": status,
                    "text": payload.get("text", ""),
                    "thinking": payload.get("thinking"),
                    "input_tokens": payload.get("input_tokens"),
                    "output_tokens": payload.get("output_tokens"),
                    "cache_hit_tokens": payload.get("cache_hit_tokens"),
                    "cache_write_tokens": payload.get("cache_write_tokens"),
                    "cache_hit_rate": payload.get("cache_hit_rate"),
                    "reporting_status": payload.get("reporting_status", "not_reported"),
                }
                remembered = str(turn_key or request_id)
                self._sessions.remember_turn(session_id, remembered, result)
                await self._respond(request_id, result)
                self._resolved_jobs.add(job_id)
        finally:
            self._job_tasks.pop(job_id, None)

    async def _handle_prompt(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", self._active_session_id))
        text = str(params.get("text", ""))
        if not text.strip():
            await self._respond_error(request_id, -32602, "text is required")
            return
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if "capability" in params:
            try:
                self._tool_capability.set_session(session_id, params.get("capability"))
            except CapabilityDenied as exc:
                await self._respond_error(request_id, -32602, exc.message, {"error_code": exc.code})
                return
        session_record = self._sessions.get(session_id)
        if session_record is not None:
            session_record.last_user_prompt = text
        self._task_store.append_event(
            session_id,
            {
                "method": "session/prompt",
                "params": {"session_id": session_id, "text": text, "role": "user"},
            },
        )
        turn_key = str(params.get("request_id") or request_id)
        stored = self._sessions.turn_result(session_id, turn_key)
        if stored is not None:
            await self._respond(request_id, dict(stored))
            return
        if self._inflight_turns.get(session_id) == turn_key:
            await self._respond(
                request_id,
                {
                    "status": "running",
                    "session_id": session_id,
                    "request_id": turn_key,
                    "idempotent": True,
                },
            )
            return
        if (
            self._watchdog.degraded
            and self._watchdog.degrade_reason.startswith(
                ("job stalled", "transport degraded", "prompt timed out")
            )
        ):
            # Timeout/stall handling kills the affected worker before returning
            # the error. Admit the next prompt, even when another session still
            # has an active job, so one failed session cannot block unrelated
            # concurrent work. A fresh host is created by _host_for_session.
            self._watchdog.recover()
        if self._watchdog.degraded:
            await self._respond_error(
                request_id,
                -32004,
                f"appserver degraded: {self._watchdog.degrade_reason or 'watchdog'}",
            )
            return

        timeout_raw = params.get("timeout_seconds")
        timeout_seconds: float | None
        if timeout_raw is None:
            timeout_seconds = None
        else:
            try:
                timeout_seconds = float(timeout_raw)
            except (TypeError, ValueError):
                await self._respond_error(
                    request_id, -32602, "timeout_seconds must be a number"
                )
                return
            if timeout_seconds <= 0:
                await self._respond_error(
                    request_id, -32602, "timeout_seconds must be positive"
                )
                return

        job_id = uuid.uuid4().hex[:12]
        mode = str(params.get("mode", "build"))
        thinking_raw = params.get("thinking_expanded")
        thinking_expanded: bool | None
        if thinking_raw is None:
            thinking_expanded = None
        else:
            thinking_expanded = bool(thinking_raw)
        permission_mode_raw = params.get("permission_mode")
        permission_mode = (
            str(permission_mode_raw).strip().lower()
            if permission_mode_raw is not None
            else None
        )
        if permission_mode not in {None, "confirm_all", "auto_edit", "full_auto"}:
            await self._respond_error(request_id, -32602, "invalid permission_mode")
            return
        self._inflight_turns[session_id] = turn_key
        try:
            await self._run_prompt(
                session_id=session_id,
                text=text,
                request_id=request_id,
                job_id=job_id,
                timeout_seconds=timeout_seconds,
                mode=mode,
                thinking_expanded=thinking_expanded,
                permission_mode=permission_mode,
                turn_key=turn_key,
            )
        finally:
            if self._inflight_turns.get(session_id) == turn_key:
                self._inflight_turns.pop(session_id, None)

    async def _handle_set_thinking_expanded(
        self, params: dict[str, Any], request_id: Any
    ) -> None:
        session_id = str(params.get("session_id", self._active_session_id))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if "expanded" not in params:
            await self._respond_error(request_id, -32602, "expanded is required")
            return
        expanded = bool(params.get("expanded"))
        self._thinking_expanded = expanded
        host = self._session_hosts.get(session_id)
        if host is not None and host.alive():
            await host.set_thinking_expanded(expanded)
        await self._respond(
            request_id,
            {
                "ok": True,
                "expanded": expanded,
                "session_id": session_id,
                "action": "thinking_toggled",
                "message": "思考过程: " + ("展开" if expanded else "折叠"),
            },
        )

    async def _handle_warm(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", self._active_session_id))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        timeout_raw = params.get("timeout_seconds")
        timeout = float(timeout_raw) if timeout_raw is not None else 180.0
        if timeout <= 0:
            await self._respond_error(request_id, -32602, "timeout_seconds must be positive")
            return
        try:
            host = await self._host_for_session(session_id)
            await host.ensure_bootstrapped(timeout=timeout)
        except Exception as exc:
            await self._respond_error(request_id, -32000, str(exc))
            return
        await self._respond(
            request_id,
            {"ok": True, "session_id": session_id, "warmed": True},
        )

    async def _handle_interrupt(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", self._active_session_id))
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        host = self._session_hosts.get(session_id)
        outcome = {"cancelled": False, "failed": False, "killed": False}
        if host is not None and host.alive():
            try:
                result = await host.interrupt(timeout=5.0)
                outcome = {
                    "cancelled": bool(result.get("cancelled")),
                    "failed": bool(result.get("failed")),
                    "killed": bool(result.get("killed")),
                }
            except Exception as exc:
                _logger.warning("session/interrupt failed for %s: %s", session_id, exc)
                await self._kill_session_host(session_id)
                outcome = {"cancelled": False, "failed": True, "killed": True}
        outcome["session_id"] = session_id
        await self._respond(request_id, outcome)

    async def _heartbeat_loop(self) -> None:
        interval = heartbeat_interval_seconds()
        while not self._shutdown:
            await asyncio.sleep(interval)
            for stalled in list(self._watchdog.stalled_jobs()):
                await self._handle_stalled_job(stalled)
            for session_id, host in list(self._session_hosts.items()):
                if host.degraded and not self._watchdog.degraded:
                    self._watchdog.degrade(
                        f"transport degraded (session {session_id})"
                    )
            await self._emit_model(
                ServerHeartbeat(
                    uptime_seconds=time.monotonic() - self._started_at,
                    active_jobs=self._watchdog.active_jobs,
                    degraded=self._watchdog.degraded,
                )
            )

    async def _handle_shutdown(self, params: dict[str, Any], request_id: Any) -> None:
        reason = params.get("reason")
        if reason:
            _logger.info("shutdown requested: %s", reason)
        self._shutdown = True
        if self._schedule_task is not None:
            self._schedule_task.cancel()
        self._mark_inflight_recovery_required()
        await self._emit_model(
            ProcessShutdown(reason=str(reason or "shutdown"), graceful=True)
        )
        await self._respond(request_id, {"ok": True})

    def _mark_inflight_recovery_required(self) -> None:
        """Crash/EOF/shutdown: unfinished turns stay recoverable, never completed."""
        for session_id, record in list(self._sessions._sessions.items()):
            if record.status in {"succeeded", "failed", "cancelled", "timed_out", "recovery_required"}:
                continue
            if record.status in {"queued", "running", "approval", "submitted", "active"}:
                previous = record.status
                self._sessions.update_status(session_id, "recovery_required")
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                note = RecoveryRequired(session_id=session_id, previous_status=previous)
                if loop is None:
                    write_message_sync(model_to_notification(note))
                else:
                    self._schedule_notification(model_to_notification(note))

    def _touch_jobs_for_notification(self, message: dict[str, Any]) -> None:
        params = message.get("params")
        if not isinstance(params, dict):
            return
        session_id = str(
            params.get("session_id") or params.get("root_session_id") or ""
        )
        if not session_id:
            return
        for job in list(self._watchdog.jobs.values()):
            if job.session_id == session_id:
                self._watchdog.touch_job(job.job_id)

    def _emit_host_notification(self, message: dict[str, Any]) -> None:
        """Forward worker notifications without blocking the event loop."""
        self._touch_jobs_for_notification(message)
        if message.get("method") == "event/heartbeat":
            # Liveness only; same contract as the in-prompt emit path.
            return
        self._persist_notification(message)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            write_message_sync(message)
            return
        self._schedule_notification(message)

    async def _handle_subagent_rpc(
        self, method: str, params: dict[str, Any], request_id: Any
    ) -> None:
        root_session_id = str(
            params.get("root_session_id")
            or params.get("parent_session_id")
            or self._active_session_id
        )

        if self._sessions.get(root_session_id) is None:
            if method == "subagents/capability":
                await self._respond(
                    request_id,
                    {
                        "protocol_version": 1,
                        "subagents_enabled": False,
                        "task": False,
                        "mention": False,
                        "child_tasks": False,
                    },
                )
                return
            await self._respond_error(
                request_id, -32001, f"unknown session: {root_session_id}"
            )
            return

        forwarded = dict(params)
        forwarded["root_session_id"] = root_session_id
        if method in {"agent/invoke", "task/start"}:
            forwarded.setdefault("parent_session_id", root_session_id)
            if "capability" in params:
                try:
                    self._tool_capability.set_session(root_session_id, params.get("capability"))
                except CapabilityDenied as exc:
                    await self._respond_error(request_id, -32602, exc.message, {"error_code": exc.code})
                    return

        # Child replay is read-only. A cold desktop must not wait on AgentV2
        # bootstrap (30s+) just to learn there are no child sessions yet.
        if method in {"child_sessions/list", "child_sessions/events"}:
            host = self._session_hosts.get(root_session_id)
            if (
                host is None
                or not host.alive()
                or not getattr(host, "bootstrapped", False)
            ):
                if method == "child_sessions/list":
                    await self._respond(
                        request_id,
                        {"root_session_id": root_session_id, "sessions": []},
                    )
                else:
                    await self._respond(
                        request_id,
                        {
                            "root_session_id": root_session_id,
                            "events": [],
                            "next_cursor": 0,
                            "gap_detected": False,
                        },
                    )
                return

        try:
            host = await self._host_for_session(root_session_id)
            await host.ensure_bootstrapped(timeout=30.0)
            result = await host.run_subagent_rpc(
                method,
                forwarded,
                timeout=30.0,
                emit=self._emit_host_notification,
            )
        except Exception as exc:
            await self._respond_error(request_id, -32000, str(exc))
            return
        await self._respond(request_id, result)

    def _session_summary(self, record: Any) -> dict[str, Any]:
        return {
            "session_id": record.session_id,
            "title": record.title,
            "workspace_root": str(record.workspace_root),
            "model_id": record.model_id,
            "provider_id": record.provider_id,
            "status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "trashed_at": record.trashed_at,
            "archived_at": getattr(record, "archived_at", None),
            "pinned": bool(getattr(record, "pinned", False)),
            "forked_from": getattr(record, "forked_from", None),
            "parent_session_id": getattr(record, "parent_session_id", None),
            "root_session_id": getattr(record, "root_session_id", None) or record.session_id,
            "child_count": self._sessions.child_count(record.session_id),
            "agent_id": getattr(record, "agent_id", None),
            "trigger": getattr(record, "trigger", None),
            "lease_id": getattr(record, "lease_id", None),
            "orphan_reason": getattr(record, "orphan_reason", None),
            "last_turn_request_id": getattr(record, "last_turn_request_id", None),
            "usage": dict(record.usage),
        }

    async def _handle_sessions_list(self, params: dict[str, Any], request_id: Any) -> None:
        workspace_root = params.get("workspace_root")
        project_id = params.get("project_id")
        if isinstance(project_id, str) and project_id:
            project = self._projects.get(project_id)
            if project is None:
                await self._respond_error(request_id, -32001, f"unknown project: {project_id}")
                return
            workspace_root = project.get("path")
        records = self._sessions.list(
            include_trashed=bool(params.get("include_trashed", False)),
            include_archived=bool(params.get("include_archived", False)),
            workspace_root=workspace_root,
            status=params.get("status"),
            updated_after=params.get("updated_after"),
            updated_before=params.get("updated_before"),
            created_after=params.get("created_after"),
            created_before=params.get("created_before"),
            parent_session_id=params.get("parent_session_id"),
        )
        await self._respond(
            request_id,
            {"sessions": [self._session_summary(record) for record in records]},
        )

    async def _handle_session_events(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        cursor = int(params.get("cursor", 0) or 0)
        events, next_cursor, gap = self._task_store.events(session_id, cursor)
        events = self._project_session_items(session_id, events)
        await self._respond(
            request_id,
            {"events": events, "next_cursor": next_cursor, "gap_detected": gap},
        )

    async def _handle_session_rename(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        title = str(params.get("title", ""))
        try:
            record = self._sessions.rename(session_id, title)
        except KeyError:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        except ValueError as exc:
            await self._respond_error(request_id, -32602, str(exc))
            return
        await self._respond(request_id, self._session_summary(record))

    async def _handle_session_trash(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        try:
            record = self._sessions.trash(session_id)
        except KeyError:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        self._side_chat.close_for_parent(session_id)
        await self._respond(request_id, self._session_summary(record))
        # Do not make a reversible UI operation wait for process teardown.
        # The host is owned by this session and can be cleaned up in the
        # background after the client has received the durable trash result.
        cleanup = asyncio.create_task(self._kill_session_host(session_id))
        self._prompt_tasks.add(cleanup)
        cleanup.add_done_callback(self._prompt_tasks.discard)

    async def _handle_session_restore(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        try:
            record = self._sessions.restore(session_id)
        except KeyError:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        await self._respond(request_id, self._session_summary(record))

    async def _handle_session_purge(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if record.trashed_at is None:
            await self._respond_error(request_id, -32003, "trash the session before purging it")
            return
        await self._kill_session_host(session_id)
        self._sessions.purge(session_id)
        await self._respond(request_id, {"ok": True, "session_id": session_id})

    async def _handle_session_fork(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        parent_before = self._sessions.get(session_id)
        if parent_before is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        parent_status = parent_before.status
        parent_updated = parent_before.updated_at
        parent_title = parent_before.title
        parent_events, _, _ = self._task_store.events(session_id, 0)
        child = self._sessions.fork(session_id)
        parent_after = self._sessions.get(session_id)
        assert parent_after is not None
        if (
            parent_after.status != parent_status
            or parent_after.updated_at != parent_updated
            or parent_after.title != parent_title
        ):
            await self._respond_error(request_id, -32603, "fork mutated parent thread")
            return
        after_events, _, _ = self._task_store.events(session_id, 0)
        if len(after_events) != len(parent_events):
            await self._respond_error(request_id, -32603, "fork mutated parent events")
            return
        await self._respond(request_id, self._session_summary(child))

    async def _handle_session_tree(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        nodes = self._sessions.tree(session_id)
        root_id = nodes[0].root_session_id if nodes else session_id
        await self._respond(
            request_id,
            {
                "root_session_id": root_id,
                "sessions": [self._session_summary(item) for item in nodes],
            },
        )

    async def _handle_session_archive(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        try:
            record = self._sessions.archive(session_id)
        except KeyError:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        self._side_chat.close_for_parent(session_id)
        await self._respond(request_id, self._session_summary(record))

    async def _handle_session_unarchive(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        try:
            record = self._sessions.unarchive(session_id)
        except KeyError:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        await self._respond(request_id, self._session_summary(record))

    async def _handle_thread_fork(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._thread_fork.fork(
                thread_id=str(params.get("thread_id") or params.get("session_id") or ""),
                message_id=str(params.get("message_id") or ""),
                edited_text=params.get("edited_text"),
            )
        except ThreadForkError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_thread_pin(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._thread_fork.pin(
                str(params.get("thread_id") or params.get("session_id") or ""),
                pinned=bool(params.get("pinned", True)),
            )
        except ThreadForkError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_plan_persist(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._plan_files.persist(
                thread_id=str(params.get("thread_id") or ""),
                title=str(params.get("title") or "plan"),
                goal=str(params.get("goal") or ""),
                steps=[str(item) for item in (params.get("steps") or [])],
                acceptance=[str(item) for item in (params.get("acceptance") or [])],
            )
        except PlanFileError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_side_chat_create(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._side_chat.create(thread_id=str(params.get("thread_id") or ""))
        except SideChatError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_side_chat_close(self, params: dict[str, Any], request_id: Any) -> None:
        if params.get("promote") and params.get("confirm_promote") is not True:
            await self._respond_error(
                request_id,
                -32602,
                "promote requires confirm_promote=true",
                {"error_code": "confirm_required"},
            )
            return
        try:
            result = self._side_chat.close(side_thread_id=str(params.get("side_thread_id") or ""))
        except SideChatError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        result["promoted"] = bool(params.get("promote") and params.get("confirm_promote") is True)
        await self._respond(request_id, result)

    async def _handle_plan_implement(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._plan_files.implement(
                plan_id=str(params.get("plan_id") or ""),
                confirm=params.get("confirm"),
            )
        except PlanFileError as exc:
            code = -32602 if exc.code == "confirm_required" else -32001
            await self._respond_error(request_id, code, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    def _project_session_items(self, session_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return project_session_items(self._sessions.get(session_id), items)

    async def _handle_session_items(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        cursor = int(params.get("cursor", 0) or 0)
        limit = int(params.get("limit", 50) or 50)
        items, next_cursor, gap = self._task_store.events(session_id, cursor, limit=limit)
        items = self._project_session_items(session_id, items)
        await self._respond(
            request_id,
            {"items": items, "next_cursor": next_cursor, "gap_detected": gap},
        )

    async def _handle_turn_steer(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        text = str(params.get("text") or "").strip()
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if not text:
            await self._respond_error(request_id, -32602, "text is required")
            return
        host = self._session_hosts.get(session_id)
        running = any(job.session_id == session_id for job in self._watchdog.jobs.values())
        if not running or host is None or not host.alive():
            await self._respond_error(
                request_id,
                -32014,
                "turn is not running",
                {"error_code": "TURN_NOT_RUNNING", "retryable": False},
            )
            return
        try:
            steered = await host.steer(text)
        except Exception as exc:
            await self._respond_error(
                request_id,
                -32014,
                str(exc) or "turn is not running",
                {"error_code": "TURN_NOT_RUNNING", "retryable": False},
            )
            return
        self._task_store.append_event(
            session_id,
            {
                "method": "event/turn_steered",
                "params": {"session_id": session_id, "text": text, "queued": True},
            },
        )
        await self._respond(
            request_id,
            {"ok": True, "session_id": session_id, "queued": True, "worker": steered},
        )

    async def _handle_turn_retry(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        retry_id = str(params.get("request_id") or "")
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if not retry_id:
            await self._respond_error(request_id, -32602, "request_id is required")
            return
        stored = self._sessions.turn_result(session_id, retry_id)
        if stored is not None:
            await self._respond(request_id, dict(stored))
            return
        text = str(params.get("text") or "retry")
        await self._handle_prompt(
            {"session_id": session_id, "text": text, "request_id": retry_id},
            request_id,
        )

    async def _handle_command_start(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        command = str(params.get("command") or "").strip()
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if not command:
            await self._respond_error(request_id, -32602, "command is required")
            return
        actor = str(params.get("actor") or "user")
        cwd = params.get("cwd") or str(record.workspace_root)
        bound = self._projects.find_by_path(record.workspace_root)
        bound_project = None if bound is None else str(bound.get("project_id"))
        requested_project = params.get("project_id")
        if isinstance(requested_project, str) and requested_project.strip():
            project_id = requested_project.strip()
            known = self._projects.get(project_id)
            if known is None:
                await self._respond_error(
                    request_id,
                    -32003,
                    "permission denied",
                    {"error_code": "PERMISSION_DENIED", "reason": "unknown_project"},
                )
                return
            try:
                same = canonicalize(known.get("path") or "") == canonicalize(record.workspace_root)
            except PathBoundaryError:
                same = False
            if not same:
                await self._respond_error(
                    request_id,
                    -32003,
                    "permission denied",
                    {"error_code": "PERMISSION_DENIED", "reason": "project_mismatch"},
                )
                return
        else:
            project_id = bound_project
        roots = params.get("writable_roots")
        verdict = self._permissions.evaluate(
            action="command",
            actor=actor,
            approval_id=params.get("approval_id"),
            scope=str(cwd),
            project_id=project_id,
            workspace=str(record.workspace_root),
            session_id=session_id,
            turn_id=params.get("turn_id"),
            expand_sandbox=bool(params.get("expand_sandbox")),
            expand_writable_roots=bool(params.get("expand_writable_roots")),
            expand_network=bool(params.get("expand_network")),
            writable_roots=list(roots) if isinstance(roots, list) else None,
            network=params.get("network") if isinstance(params.get("network"), bool) else None,
        )
        if verdict != "allow":
            denied = self._permissions.last_decision() or self._permissions.decide(
                session_id=session_id,
                action="command",
                actor=actor,
                decision="reject",
                turn_id=record.last_turn_request_id,
                project_id=project_id,
                scope=str(cwd),
                consumed=True,
            )
            if denied.get("interrupt_turn"):
                self._sessions.update_status(session_id, "interrupted")
            await self._respond_error(
                request_id,
                -32003,
                "permission denied",
                {"error_code": "PERMISSION_DENIED", "approval": denied},
            )
            return
        try:
            assert_inside_workspace(record.workspace_root, cwd)
        except PathBoundaryError as exc:
            await self._respond_error(request_id, -32003, str(exc), {"error_code": exc.code})
            return
        timeout = float(params.get("timeout_seconds") or 30.0)
        item = await self._execution.run_command(
            session_id=session_id,
            command=command,
            cwd=str(canonicalize(cwd)),
            origin="user",
            background=bool(params.get("background")),
            timeout=timeout,
        )
        self._schedule_execution_event(item)
        await self._respond(request_id, item.to_dict())

    async def _handle_execution_list(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        items = self._execution.list(
            session_id, include_completed=bool(params.get("include_completed", False))
        )
        await self._respond(
            request_id,
            {"items": [item.to_dict(include_output=False) for item in items]},
        )

    async def _handle_execution_stop(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        task_id = str(params.get("task_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        item = self._execution.get(task_id)
        if item is None or item.session_id != session_id:
            await self._respond_error(request_id, -32001, f"unknown task: {task_id}")
            return
        try:
            self._execution.request_stop(task_id)
        except ValueError as exc:
            await self._respond_error(request_id, -32003, str(exc))
            return
        await self._respond(request_id, {"ok": True, "task_id": task_id})

    async def _handle_execution_output(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        task_id = str(params.get("task_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        item = self._execution.get(task_id)
        if item is None or item.session_id != session_id:
            await self._respond_error(request_id, -32001, f"unknown task: {task_id}")
            return
        self._execution.mark_read(task_id)
        await self._respond(request_id, item.to_dict())

    def _review_session(self, params: dict[str, Any]) -> Any:
        session_id = str(params.get("session_id") or params.get("thread_id") or "")
        return self._sessions.get(session_id), session_id

    async def _deny_write(self, params: dict[str, Any], request_id: Any, action: str, scope: str) -> bool:
        session_id = str(params.get("session_id") or params.get("thread_id") or "")
        record = self._sessions.get(session_id)
        workspace = str(record.workspace_root) if record is not None else scope
        verdict = self._permissions.evaluate(
            action=action,
            actor=str(params.get("actor") or "user"),
            approval_id=params.get("approval_id"),
            scope=scope or workspace,
            workspace=workspace,
            session_id=session_id or None,
            project_id=params.get("project_id"),
        )
        if verdict == "allow":
            return False
        denied = self._permissions.last_decision()
        await self._respond_error(
            request_id,
            -32003,
            "permission denied",
            {"error_code": "PERMISSION_DENIED", "approval": denied},
        )
        return True

    async def _handle_review_start(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        try:
            result, events = self._reviews.start(
                request_id=str(params.get("request_id") or ""),
                session_id=session_id,
                workspace=record.workspace_root,
                scope=str(params.get("scope") or "working_tree"),
                base_ref=params.get("base_ref"),
                head_ref=params.get("head_ref"),
                paths=list(params.get("paths") or []) or None,
                turn_id=params.get("turn_id"),
                thread_id=params.get("thread_id") or session_id,
                criteria=list(params.get("criteria") or []) or None,
                reviewer=params.get("reviewer") if isinstance(params.get("reviewer"), dict) else None,
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        for event in events:
            self._persist_notification(event)
            self._schedule_notification(event)
        await self._respond(request_id, result)

    async def _handle_review_read(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            after = params.get("after_sequence")
            review = self._reviews.read(
                str(params.get("review_id") or ""),
                after_sequence=int(after) if after is not None else None,
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, review)

    async def _handle_review_comment(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            comment = self._reviews.comment(
                review_id=str(params.get("review_id") or ""),
                finding_id=params.get("finding_id"),
                file=str(params.get("file") or ""),
                start_line=int(params.get("start_line") or 1),
                end_line=int(params.get("end_line") or 1),
                body=str(params.get("body") or ""),
                file_hash=params.get("file_hash"),
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, comment)

    async def _handle_review_comment_add(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            comment = self._review_comments.add(
                review_id=str(params.get("review_id") or ""),
                file=str(params.get("file") or ""),
                line=int(params.get("line") or 0),
                hunk_hash=str(params.get("hunk_hash") or ""),
                body=str(params.get("body") or ""),
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, comment)

    async def _handle_review_comment_resolve(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            comment = self._review_comments.resolve(str(params.get("comment_id") or ""))
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, comment)

    async def _handle_checkpoint_create(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        result = self._reviews.create_checkpoint(
            session_id=session_id,
            workspace=record.workspace_root,
            reason=str(params.get("reason") or "write"),
            turn_id=params.get("turn_id"),
        )
        await self._respond(request_id, result)

    async def _handle_checkpoint_list(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id") or "")
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        await self._respond(request_id, {"checkpoints": self._reviews.list_checkpoints(session_id)})

    async def _handle_checkpoint_read(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            item = self._reviews.read_checkpoint(
                str(params.get("checkpoint_id") or ""),
                session_id=str(params.get("session_id") or ""),
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, item)

    async def _handle_checkpoint_restore(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            item = self._reviews.read_checkpoint(
                str(params.get("checkpoint_id") or ""),
                session_id=str(params.get("session_id") or ""),
                include_files=False,
            )
        except ReviewError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        session_id = str(params.get("session_id") or item.get("session_id") or "")
        if await self._deny_write(params | {"session_id": session_id}, request_id, "checkpoint_restore", str(item.get("workspace") or "")):
            return
        try:
            result = self._reviews.restore_checkpoint(str(item["checkpoint_id"]), session_id=session_id or None)
        except (ReviewError, PathBoundaryError) as exc:
            code = getattr(exc, "code", "REVIEW_DIFF_UNAVAILABLE")
            await self._respond_error(request_id, -32003, str(exc), {"error_code": code})
            return
        for review_id in result.get("stale_reviews") or []:
            self._schedule_notification(
                {
                    "jsonrpc": "2.0",
                    "method": "review/stale",
                    "params": {"session_id": session_id, "review_id": review_id, "event_id": str(review_id)},
                }
            )
        await self._respond(request_id, result)

    async def _handle_checkpoint_snapshot_create(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._checkpoint_rewind.snapshot_create(
                session_id=str(params.get("session_id") or ""),
                name=str(params.get("name") or ""),
                user_prompt=params.get("user_prompt"),
            )
        except CheckpointRewindError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_checkpoint_rewind(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id") or "")
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if await self._deny_write(params | {"session_id": session_id}, request_id, "checkpoint_restore", str(record.workspace_root)):
            return
        try:
            result = self._checkpoint_rewind.rewind(
                checkpoint_id=str(params.get("checkpoint_id") or ""),
                confirm=params.get("confirm"),
                session_id=session_id,
            )
        except CheckpointRewindError as exc:
            code = -32602 if exc.code == "confirm_required" else -32001
            await self._respond_error(request_id, code, exc.message, {"error_code": exc.code})
            return
        except (ReviewError, PathBoundaryError) as exc:
            code = getattr(exc, "code", "REVIEW_DIFF_UNAVAILABLE")
            await self._respond_error(request_id, -32003, str(exc), {"error_code": code})
            return
        for review_id in result.get("stale_reviews") or []:
            self._schedule_notification(
                {
                    "jsonrpc": "2.0",
                    "method": "review/stale",
                    "params": {"session_id": session_id, "review_id": review_id, "event_id": str(review_id)},
                }
            )
        await self._respond(request_id, result)

    async def _handle_git_change(self, params: dict[str, Any], request_id: Any, action: str) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        paths = [str(item) for item in (params.get("paths") or [])]
        if await self._deny_write(params, request_id, f"git_{action}", str(record.workspace_root)):
            return
        try:
            result = self._reviews.git_change(
                record.workspace_root,
                action=action,
                paths=paths,
                hunk_index=params.get("hunk_index"),
                permission_store=self._permissions,
                actor=str(params.get("actor") or "user"),
                approval_id=params.get("approval_id"),
                session_id=session_id,
            )
        except (ReviewError, PathBoundaryError) as exc:
            code = getattr(exc, "code", "REVIEW_DIFF_UNAVAILABLE")
            await self._respond_error(request_id, -32003, str(exc), {"error_code": code})
            return
        await self._respond(request_id, result)

    async def _handle_file_preview(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        try:
            result = preview_file(record.workspace_root, str(params.get("path") or ""))
        except PathBoundaryError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_file_tree(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        try:
            rows = list_tree(record.workspace_root, params.get("path"))
        except PathBoundaryError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, {"entries": rows})

    async def _handle_file_open_external(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        try:
            result = prepare_open_external(
                record.workspace_root,
                str(params.get("path") or ""),
                confirm=bool(params.get("confirm")),
            )
        except PathBoundaryError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_worktree_list(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        await self._respond(
            request_id,
            {"worktrees": self._worktrees.list(record.workspace_root, session_id=session_id)},
        )

    async def _handle_worktree_open(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        try:
            result = self._worktrees.open(str(params.get("worktree_id") or ""), session_id=session_id)
        except WorktreeError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        self._sessions.set_workspace(session_id, result["path"])
        await self._respond(request_id, result)

    async def _handle_worktree_create(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if await self._deny_write(params, request_id, "worktree_create", str(record.workspace_root)):
            return
        try:
            result = self._worktrees.create(
                record.workspace_root,
                dest=str(params.get("dest") or ""),
                branch=params.get("branch"),
                session_id=session_id,
                permission_store=self._permissions,
                confirm=True,
            )
        except WorktreeError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_worktree_close(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if await self._deny_write(params, request_id, "worktree_close", str(record.workspace_root)):
            return
        try:
            result = self._worktrees.close(
                record.workspace_root,
                str(params.get("worktree_id") or ""),
                force=bool(params.get("force")),
                confirm=bool(params.get("confirm")),
                session_id=session_id,
                permission_store=self._permissions,
            )
        except WorktreeError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_worktree_prune(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if await self._deny_write(params, request_id, "worktree_prune", str(record.workspace_root)):
            return
        try:
            result = self._worktrees.prune(
                record.workspace_root,
                confirm=bool(params.get("confirm")),
                permission_store=self._permissions,
                session_id=session_id,
            )
        except WorktreeError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_worktree_handoff(self, params: dict[str, Any], request_id: Any) -> None:
        record, session_id = self._review_session(params)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if await self._deny_write(params, request_id, "worktree_handoff", str(record.workspace_root)):
            return
        target_session = str(params.get("target_session") or "")
        if self._sessions.get(target_session) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {target_session}")
            return
        try:
            result = self._worktrees.handoff(
                source_session=session_id,
                target_session=target_session,
                target_path=str(params.get("target_path") or ""),
                workspace=record.workspace_root,
                permission_store=self._permissions,
                confirm=bool(params.get("confirm")),
            )
        except WorktreeError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        self._sessions.set_workspace(target_session, result["target"])
        await self._respond(request_id, result)

    def _settings_scope(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "").strip() or None
        thread_id = str(params.get("thread_id") or "").strip() or session_id
        workspace = params.get("workspace")
        project_id = str(params.get("project_id") or "").strip() or None
        if session_id:
            record = self._sessions.get(session_id)
            if record is not None:
                if not workspace:
                    workspace = str(record.workspace_root)
                if not project_id:
                    found = self._projects.find_by_path(record.workspace_root)
                    if found:
                        project_id = str(found.get("project_id") or "") or None
        return {
            "session_id": session_id,
            "thread_id": thread_id,
            "turn_id": str(params.get("turn_id") or "").strip() or None,
            "workspace": workspace,
            "project_id": project_id,
        }

    async def _handle_settings_get(self, params: dict[str, Any], request_id: Any) -> None:
        scope = self._settings_scope(params)
        keys = params.get("keys")
        result = self._settings.get(
            project_id=scope["project_id"],
            workspace=scope["workspace"],
            thread_id=scope["thread_id"],
            turn_id=scope["turn_id"],
            keys=keys if isinstance(keys, list) else None,
        )
        await self._respond(request_id, result)

    async def _handle_settings_set(self, params: dict[str, Any], request_id: Any) -> None:
        scope = self._settings_scope(params)
        values = params.get("values")
        if not isinstance(values, dict):
            await self._respond_error(
                request_id, -32602, "values must be an object", {"error_code": "SETTINGS_KEY_INVALID"}
            )
            return
        try:
            result = self._settings.set(
                layer=str(params.get("layer") or ""),
                values=values,
                permission_store=self._permissions,
                project_id=scope["project_id"],
                workspace=scope["workspace"],
                thread_id=scope["thread_id"],
                turn_id=scope["turn_id"],
                session_id=scope["session_id"],
                actor=str(params.get("actor") or "user"),
                approval_id=params.get("approval_id"),
                project_store=self._projects,
            )
        except SettingsError as exc:
            await self._respond_error(
                request_id,
                -32003,
                exc.message,
                {"error_code": exc.code, "retryable": False},
            )
            return
        await self._respond(request_id, result)

    async def _handle_settings_models(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = summarize_model(
                provider_id=str(params.get("provider_id") or ""),
                model_id=str(params.get("model_id") or ""),
                configured_max_tokens=params.get("max_tokens"),
            )
        except SettingsError as exc:
            await self._respond_error(
                request_id,
                -32003,
                exc.message,
                {"error_code": exc.code, "retryable": False},
            )
            return
        await self._respond(request_id, result)

    async def _handle_settings_diagnose(self, params: dict[str, Any], request_id: Any) -> None:
        await self._respond(
            request_id,
            self._settings.diagnose(
                error_code=params.get("error_code"),
                message=params.get("message"),
                provider_id=params.get("provider_id"),
                model_id=params.get("model_id"),
            ),
        )

    async def _handle_capabilities_list(self, params: dict[str, Any], request_id: Any) -> None:
        await self._respond(
            request_id,
            self._capabilities.list(
                kind=params.get("kind"),
                available_only=bool(params.get("available_only")),
            ),
        )

    async def _handle_capabilities_get(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._capabilities.get(str(params.get("capability_id") or ""))
        except CapabilityError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_capabilities_set_enabled(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._capabilities.set_enabled(
                str(params.get("capability_id") or ""),
                bool(params.get("enabled")),
                authorize=params.get("authorize"),
                permission_store=self._permissions,
                actor=str(params.get("actor") or "user"),
                session_id=params.get("session_id"),
                approval_id=params.get("approval_id"),
                project_id=params.get("project_id"),
                workspace=params.get("workspace"),
            )
        except CapabilityError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_capabilities_invoke(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._capabilities.invoke(
                str(params.get("capability_id") or ""),
                permission_store=self._permissions,
                session_id=params.get("session_id"),
                turn_id=params.get("turn_id"),
                actor=str(params.get("actor") or "user"),
                approval_id=params.get("approval_id"),
                project_id=params.get("project_id"),
                workspace=params.get("workspace"),
                background=bool(params.get("background")),
            )
        except CapabilityError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_capabilities_cancel(self, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = self._capabilities.cancel(
                str(params.get("job_id") or ""),
                session_id=params.get("session_id"),
            )
        except CapabilityError as exc:
            await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
            return
        await self._respond(request_id, result)

    async def _handle_capabilities_audit(self, params: dict[str, Any], request_id: Any) -> None:
        await self._respond(
            request_id,
            {"records": self._capabilities.audit(params.get("capability_id"))},
        )

    async def _handle_settings_rollback(self, params: dict[str, Any], request_id: Any) -> None:
        scope = self._settings_scope(params)
        try:
            result = self._settings.rollback(
                str(params.get("snapshot_id") or ""),
                permission_store=self._permissions,
                actor=str(params.get("actor") or "user"),
                approval_id=params.get("approval_id"),
                project_id=scope["project_id"],
                workspace=scope["workspace"],
                session_id=scope["session_id"],
                turn_id=scope["turn_id"],
            )
        except SettingsError as exc:
            await self._respond_error(
                request_id,
                -32003,
                exc.message,
                {"error_code": exc.code, "retryable": False},
            )
            return
        await self._respond(request_id, result)

    async def _handle_worktree_rollback(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id") or "")
        if not session_id:
            await self._respond_error(request_id, -32602, "session_id is required")
            return
        record = self._sessions.get(session_id)
        workspace = record.workspace_root if record is not None else Path(".")
        if await self._deny_write(params, request_id, "worktree_handoff_rollback", str(workspace)):
            return
        try:
            result = self._worktrees.rollback_handoff(
                str(params.get("handoff_id") or ""),
                session_id=session_id,
                permission_store=self._permissions,
                confirm=bool(params.get("confirm", True)),
                workspace=workspace,
            )
        except WorktreeError as exc:
            await self._respond_error(request_id, -32001, exc.message, {"error_code": exc.code})
            return
        if result.get("source_session") and result.get("source"):
            self._sessions.set_workspace(str(result["source_session"]), str(result["source"]))
        target = result.get("target_session")
        previous = result.get("target_previous")
        if target and previous:
            self._sessions.set_workspace(str(target), str(previous))
        await self._respond(request_id, result)

    def _handle_cli(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        hub = self._cli_hub
        name = str(params.get("name") or "")
        args = params.get("args") if isinstance(params.get("args"), list) else None
        if method == "cli/list":
            return hub.list_software()
        if method == "cli/install":
            return hub.install(name, source=str(params.get("source") or "cli-hub"))
        if method == "cli/uninstall":
            return hub.uninstall(name)
        if method == "cli/launch":
            return hub.launch(name, args)
        if method == "cli/start":
            return hub.start(name, args)
        if method == "cli/stop":
            return hub.stop(name)
        if method == "cli/decide":
            return hub.decide(
                name,
                has_source=bool(params.get("has_source")),
                has_sdk=bool(params.get("has_sdk")),
            )
        if method == "cli/record_failure":
            return hub.record_generate_failure(
                name,
                str(params.get("stage") or ""),
                str(params.get("reason") or ""),
                params.get("next_step") if params.get("next_step") is not None else None,
            )
        if method == "cli/schema":
            return hub.schema(name)
        raise CliHubError("CLI_METHOD_UNKNOWN", f"unknown cli method: {method}")

    def _handle_schedule(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        sched = self._schedule
        if method == "schedule/list":
            return sched.list_jobs()
        if method == "schedule/create":
            return sched.create(
                rule=params.get("rule") if isinstance(params.get("rule"), dict) else {},
                action=params.get("action") if isinstance(params.get("action"), dict) else {},
                enabled=bool(params.get("enabled", True)),
            )
        if method == "schedule/update":
            return sched.update(
                str(params.get("job_id") or ""),
                rule=params.get("rule"),
                action=params.get("action"),
                enabled=params.get("enabled"),
            )
        if method == "schedule/delete":
            return sched.delete(str(params.get("job_id") or ""))
        if method == "schedule/toggle":
            return sched.toggle(str(params.get("job_id") or ""), params.get("enabled"))
        raise ScheduleError("SCHEDULE_METHOD_UNKNOWN", f"unknown schedule method: {method}")

    def _handle_plugin(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        hub = self._plugins
        if method == "plugin/list":
            return hub.list_plugins()
        if method == "plugin/install":
            return hub.install(
                source=str(params.get("source") or ""),
                path=params.get("path"),
                name=params.get("name"),
            )
        if method == "plugin/uninstall":
            from pydantic import ValidationError
            from protocol.requests import PluginUninstallRequest

            try:
                req = PluginUninstallRequest.model_validate({"name": params.get("name"), "keep_user_config": params.get("keep_user_config", False)})
            except ValidationError as exc:
                raise PluginError("PLUGIN_UNINSTALL_INVALID", "keep_user_config must be boolean") from exc
            return hub.uninstall(req.name, keep_user_config=req.keep_user_config)
        if method == "plugin/toggle":
            from pydantic import ValidationError
            from protocol.requests import PluginToggleRequest

            try:
                req = PluginToggleRequest.model_validate({"name": params.get("name"), "enabled": params.get("enabled")})
            except ValidationError as exc:
                raise PluginError("PLUGIN_TOGGLE_INVALID", "enabled must be boolean") from exc
            return hub.toggle(req.name, req.enabled)
        raise PluginError("PLUGIN_METHOD_UNKNOWN", f"unknown plugin method: {method}")

    def _handle_thread_trash(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "")
        if method == "thread/delete":
            return self._trash.delete(session_id)
        if method == "thread/restore":
            return self._trash.restore(session_id)
        if method == "thread/list_deleted":
            return self._trash.list_deleted()
        if method == "thread/purge":
            paths = params.get("paths") if isinstance(params.get("paths"), list) else None
            return self._trash.purge(
                session_id,
                confirm_purge=params.get("confirm_purge"),
                extra_paths=paths,
            )
        raise TrashError("THREAD_METHOD_UNKNOWN", f"unknown thread method: {method}")

    async def _handle_session_set_model(
        self, params: dict[str, Any], request_id: Any
    ) -> None:
        """Switch one task's worker model and persist the selection."""
        session_id = str(params.get("session_id", ""))
        model_id = str(params.get("model_id", "")).strip()
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        if not model_id:
            await self._respond_error(request_id, -32602, "model_id is required")
            return
        try:
            from .model_routes import set_active

            set_active({"id": model_id})
        except Exception:
            _logger.warning("could not persist active model %s", model_id, exc_info=True)
        host = self._session_hosts.get(session_id)
        result: dict[str, Any] = {"ok": True, "model_id": model_id}
        try:
            if (
                host is not None
                and host.alive()
            ):
                # ``session/new`` warms the worker in the background.  The
                # Desktop model picker can immediately send ``session/set_model``
                # while that single-flight bootstrap is still running.  Join
                # it before switching the task-local model; otherwise the
                # following prompt can race the same worker bootstrap and sit
                # at ``Starting Agent worker…`` until the appserver watchdog
                # reports a misleading 120s stall.
                if not getattr(host, "bootstrapped", False):
                    await host.ensure_bootstrapped(timeout=_DEFAULT_WARM_TIMEOUT_SECONDS)
                switched = await host.set_model(model_id, timeout=30.0)
                if isinstance(switched, dict):
                    result.update(switched)
                    result["ok"] = True
                    result["model_id"] = model_id
        except Exception as exc:
            await self._respond_error(request_id, -32000, str(exc))
            return
        provider_id = result.get("provider_id") if isinstance(result, dict) else None
        self._sessions.set_model(session_id, model_id, str(provider_id) if provider_id else None)
        await self._respond(
            request_id,
            {
                "ok": True,
                "session_id": session_id,
                "model_id": model_id,
                "provider_id": provider_id,
            },
        )

    async def _dispatch(self, message: dict[str, Any]) -> None:
        if is_client_response(message):
            self._resolve_server_response(message)
            return

        if not is_client_request(message):
            return

        method = str(message.get("method", ""))
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        request_id = message.get("id")

        if self._shutdown and method != "shutdown":
            await self._respond_error(request_id, -32009, "appserver is closed")
            return
        if method == "initialize":
            await self._handle_initialize(params, request_id)
            return
        if not self._initialized and method != "shutdown":
            await self._respond_error(request_id, -32002, "call initialize first")
            return
        if method == "session/prompt" and len(self._prompt_tasks) >= _MAX_CONCURRENT_PROMPTS:
            await self._respond_error(request_id, -32008, "too many in-flight prompts")
            return

        if method == "session/new":
            await self._handle_session_new(params, request_id)
        elif method == "sessions/list":
            await self._handle_sessions_list(params, request_id)
        elif method == "session/events":
            await self._handle_session_events(params, request_id)
        elif method == "session/rename":
            await self._handle_session_rename(params, request_id)
        elif method == "session/trash":
            await self._handle_session_trash(params, request_id)
        elif method == "session/restore":
            await self._handle_session_restore(params, request_id)
        elif method == "session/purge":
            await self._handle_session_purge(params, request_id)
        elif method == "thread/fork":
            await self._handle_thread_fork(params, request_id)
        elif method == "thread/pin":
            await self._handle_thread_pin(params, request_id)
        elif method == "plan/persist":
            await self._handle_plan_persist(params, request_id)
        elif method == "plan/implement":
            await self._handle_plan_implement(params, request_id)
        elif method == "thread/side_chat/create":
            await self._handle_side_chat_create(params, request_id)
        elif method == "thread/side_chat/close":
            await self._handle_side_chat_close(params, request_id)
        elif method.startswith("thread/"):
            try:
                result = self._handle_thread_trash(method, params or {})
            except TrashError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method == "session/fork":
            await self._handle_session_fork(params, request_id)
        elif method == "session/tree":
            await self._handle_session_tree(params, request_id)
        elif method == "session/archive":
            await self._handle_session_archive(params, request_id)
        elif method == "session/unarchive":
            await self._handle_session_unarchive(params, request_id)
        elif method == "session/items":
            await self._handle_session_items(params, request_id)
        elif method == "turn/start":
            task = asyncio.create_task(self._handle_prompt(params, request_id))
            self._prompt_tasks.add(task)
            task.add_done_callback(self._prompt_tasks.discard)
        elif method == "turn/steer":
            await self._handle_turn_steer(params, request_id)
        elif method == "turn/interrupt":
            await self._handle_interrupt(params, request_id)
        elif method == "turn/retry":
            await self._handle_turn_retry(params, request_id)
        elif method == "command/start":
            await self._handle_command_start(params, request_id)
        elif method == "execution/list":
            await self._handle_execution_list(params, request_id)
        elif method == "execution/stop":
            await self._handle_execution_stop(params, request_id)
        elif method == "execution/output":
            await self._handle_execution_output(params, request_id)
        elif method == "permission/get":
            await self._respond(request_id, self._permissions.snapshot())
        elif method == "permission/set":
            try:
                scopes = params.get("scopes")
                result = self._permissions.set_profile(
                    str(params.get("profile_id") or ""),
                    scopes=list(scopes) if isinstance(scopes, list) else None,
                )
            except PermissionError as exc:
                await self._respond_error(request_id, -32003, str(exc), {"error_code": "PROFILE_NOT_SELECTABLE"})
                return
            except ValueError as exc:
                await self._respond_error(request_id, -32602, str(exc))
                return
            await self._respond(request_id, result)
        elif method == "approval/decide":
            try:
                record = self._permissions.decide(
                    session_id=str(params.get("session_id") or ""),
                    action=str(params.get("action") or ""),
                    actor=str(params.get("actor") or "user"),
                    scope=params.get("scope"),
                    decision=str(params.get("decision") or "reject"),
                    expires_at=params.get("expires_at"),
                    turn_id=params.get("turn_id"),
                    project_id=params.get("project_id"),
                    reviewer_id=params.get("reviewer_id"),
                    reason=params.get("reason"),
                    original_approval_id=params.get("original_approval_id"),
                    expand_sandbox=bool(params.get("expand_sandbox")),
                    expand_writable_roots=bool(params.get("expand_writable_roots")),
                    expand_network=bool(params.get("expand_network")),
                )
            except ValueError as exc:
                await self._respond_error(request_id, -32602, str(exc))
                return
            if record.get("interrupt_turn") and record.get("session_id"):
                self._sessions.update_status(str(record["session_id"]), "interrupted")
                for item in self._execution.list(str(record["session_id"])):
                    if item.status == "running":
                        self._execution.request_stop(item.task_id)
            await self._respond(request_id, record)
        elif method == "approval/revoke":
            try:
                revoked = self._permissions.revoke(str(params.get("approval_id") or ""))
            except KeyError:
                await self._respond_error(request_id, -32001, "unknown approval")
                return
            await self._respond(request_id, revoked)
        elif method == "approval/audit":
            await self._respond(
                request_id,
                {"records": self._permissions.audit(params.get("session_id"))},
            )
        elif method == "approval/mode_set":
            try:
                result = self._permissions.apply_ui_preset(str(params.get("preset") or ""))
            except PermissionError as exc:
                await self._respond_error(
                    request_id,
                    -32003,
                    str(exc),
                    {"error_code": "full_access_not_enabled"},
                )
                return
            except ValueError as exc:
                await self._respond_error(request_id, -32602, str(exc))
                return
            await self._respond(request_id, result)
        elif method == "approval/full_access_enable":
            try:
                result = self._permissions.enable_full_access(
                    actor=str(params.get("actor") or ""),
                    source=str(params.get("source") or "settings"),
                )
            except ValueError as exc:
                await self._respond_error(request_id, -32602, str(exc))
                return
            await self._respond(request_id, result)
        elif method == "review/start":
            await self._handle_review_start(params, request_id)
        elif method == "review/read":
            await self._handle_review_read(params, request_id)
        elif method == "review/comment":
            await self._handle_review_comment(params, request_id)
        elif method == "review/comment/add":
            await self._handle_review_comment_add(params, request_id)
        elif method == "review/comment/resolve":
            await self._handle_review_comment_resolve(params, request_id)
        elif method == "checkpoint/create":
            await self._handle_checkpoint_create(params, request_id)
        elif method == "checkpoint/list":
            await self._handle_checkpoint_list(params, request_id)
        elif method == "checkpoint/read":
            await self._handle_checkpoint_read(params, request_id)
        elif method == "checkpoint/restore":
            await self._handle_checkpoint_restore(params, request_id)
        elif method == "checkpoint/snapshot/create":
            await self._handle_checkpoint_snapshot_create(params, request_id)
        elif method == "checkpoint/rewind":
            await self._handle_checkpoint_rewind(params, request_id)
        elif method == "git/stage":
            await self._handle_git_change(params, request_id, "stage")
        elif method == "git/unstage":
            await self._handle_git_change(params, request_id, "unstage")
        elif method == "git/revert":
            await self._handle_git_change(params, request_id, "revert")
        elif method == "file/preview":
            await self._handle_file_preview(params, request_id)
        elif method == "file/tree":
            await self._handle_file_tree(params, request_id)
        elif method == "file/open_external":
            await self._handle_file_open_external(params, request_id)
        elif method == "worktree/list":
            await self._handle_worktree_list(params, request_id)
        elif method == "worktree/open":
            await self._handle_worktree_open(params, request_id)
        elif method == "worktree/create":
            await self._handle_worktree_create(params, request_id)
        elif method == "worktree/close":
            await self._handle_worktree_close(params, request_id)
        elif method == "worktree/prune":
            await self._handle_worktree_prune(params, request_id)
        elif method == "worktree/handoff":
            await self._handle_worktree_handoff(params, request_id)
        elif method == "worktree/handoff/rollback":
            await self._handle_worktree_rollback(params, request_id)
        elif method == "settings/get":
            await self._handle_settings_get(params, request_id)
        elif method == "settings/set":
            await self._handle_settings_set(params, request_id)
        elif method == "settings/models":
            await self._handle_settings_models(params, request_id)
        elif method == "settings/diagnose":
            await self._handle_settings_diagnose(params, request_id)
        elif method == "settings/rollback":
            await self._handle_settings_rollback(params, request_id)
        elif method == "capabilities/list":
            await self._handle_capabilities_list(params, request_id)
        elif method == "capabilities/get":
            await self._handle_capabilities_get(params, request_id)
        elif method == "capabilities/set_enabled":
            await self._handle_capabilities_set_enabled(params, request_id)
        elif method == "capabilities/invoke":
            await self._handle_capabilities_invoke(params, request_id)
        elif method == "capabilities/cancel":
            await self._handle_capabilities_cancel(params, request_id)
        elif method == "capabilities/audit":
            await self._handle_capabilities_audit(params, request_id)
        elif method == "recovery/status":
            await self._respond(request_id, self._recovery.status(params.get("session_id")))
        elif method == "recovery/replay":
            await self._respond(
                request_id,
                self._recovery.replay(
                    str(params.get("session_id") or ""),
                    params.get("cursor"),
                    limit=int(params.get("limit") or 100),
                ),
            )
        elif method == "recovery/reclaim":
            live = set(self._sessions._sessions)
            await self._respond(request_id, {"orphans": self._recovery.reclaim_orphans(live)})
        elif method == "notifications/list":
            await self._respond(
                request_id,
                {
                    "notifications": self._recovery.list_notifications(
                        params.get("session_id"),
                        include_acked=bool(params.get("include_acked")),
                    )
                },
            )
        elif method == "notifications/ack":
            try:
                result = self._recovery.ack(str(params.get("notification_id") or ""))
            except RecoveryError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method == "release/status":
            await self._respond(request_id, self._release.compatibility())
        elif method == "release/diagnose":
            await self._respond(request_id, self._release.diagnose_mismatch(params or {}))
        elif method.startswith("cli/"):
            try:
                result = self._handle_cli(method, params or {})
            except CliHubError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method.startswith("schedule/"):
            try:
                result = self._handle_schedule(method, params or {})
            except ScheduleError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method.startswith("plugin/"):
            try:
                result = self._handle_plugin(method, params or {})
            except PluginError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method == "notifications/cursor":
            try:
                result = self._recovery.save_cursor(
                    str(params.get("session_id") or ""),
                    int(params.get("cursor") or 0),
                )
            except RecoveryError as exc:
                await self._respond_error(request_id, -32003, exc.message, {"error_code": exc.code})
                return
            await self._respond(request_id, result)
        elif method == "session/set_model":
            await self._handle_session_set_model(params, request_id)
        elif method == "session/prompt":
            task = asyncio.create_task(self._handle_prompt(params, request_id))
            self._prompt_tasks.add(task)
            task.add_done_callback(self._prompt_tasks.discard)
        elif method == "session/interrupt":
            await self._handle_interrupt(params, request_id)
        elif method == "session/set_thinking_expanded":
            await self._handle_set_thinking_expanded(params, request_id)
        elif method == "session/warm":
            task = asyncio.create_task(self._handle_warm(params, request_id))
            self._prompt_tasks.add(task)
            task.add_done_callback(self._prompt_tasks.discard)
        elif method == "shutdown":
            await self._handle_shutdown(params, request_id)

        # ── Phase B: subagent JSON-RPC methods ──────────────────────
        elif method in {
            "agent/invoke",
            "task/start",
            "subagents/list",
            "subagents/capability",
            "child_sessions/list",
            "child_sessions/events",
            "child_sessions/cancel",
            "child_sessions/retry",
        }:
            await self._handle_subagent_rpc(method, params, request_id)

        # ── Phase 4 D5: model / credential JSON-RPC methods ──────────
        elif method == "models/list":
            from .model_routes import list_models

            await self._respond(request_id, list_models())
        elif method == "models/presets":
            from .model_routes import list_presets

            await self._respond(request_id, list_presets())
        elif method == "models/discover":
            from .model_routes import discover

            await self._respond(request_id, await discover(params))
        elif method == "models/onboard":
            from .model_routes import onboard

            await self._respond(request_id, await onboard(params))
        elif method == "models/onboard_batch":
            from .model_routes import onboard_batch

            await self._respond(request_id, await onboard_batch(params))
        elif method == "models/remove":
            from .model_routes import remove

            await self._respond(request_id, remove(params))
        elif method == "models/set_active":
            from .model_routes import set_active

            await self._respond(request_id, set_active(params))
        elif method == "models/test_connection":
            from .model_routes import test_connection

            await self._respond(request_id, await test_connection(params))
        elif method == "credentials/upsert":
            from .model_routes import upsert_credential

            await self._respond(request_id, upsert_credential(params))
        elif method == "credentials/delete":
            from .model_routes import delete_credential

            await self._respond(request_id, delete_credential(params))
        elif method == "team/list":
            from .team_routes import team_list

            await self._respond(request_id, team_list())
        elif method == "team/groups":
            from .team_routes import team_groups

            await self._respond(request_id, team_groups())
        elif method == "team/group_rename":
            from .team_routes import team_group_rename

            await self._respond(request_id, team_group_rename(params))
        elif method == "team/install":
            from .team_routes import team_install_rpc

            await self._respond(request_id, team_install_rpc(params))
        elif method == "team/set_active":
            from .team_routes import team_set_active

            await self._respond(request_id, team_set_active(params))
        elif method in {
            "project/list",
            "project/add",
            "project/remove",
            "project/set_active",
            "workspace/status",
            "workspace/resolve",
        }:
            await self._handle_project_method(method, params, request_id)

        else:
            await self._respond_error(request_id, -32601, f"method not found: {method}")

    async def _handle_project_method(
        self, method: str, params: dict[str, Any], request_id: Any
    ) -> None:
        before = self._projects.active()
        before_id = None if before is None else before.get("project_id")
        try:
            result = handle_project_rpc(self._projects, method, params)
        except PathBoundaryError as exc:
            await self._respond_error(
                request_id,
                -32011,
                exc.message,
                {"error_code": exc.code, "retryable": False},
            )
            return
        after = self._projects.active()
        after_id = None if after is None else after.get("project_id")
        if method in {"project/add", "project/set_active", "project/remove"} and before_id != after_id:
            await self._emit_model(
                WorkspaceChanged(
                    project_id=str((after or {}).get("project_id") or ""),
                    workspace_root=str((after or {}).get("path") or ""),
                    display_name=str((after or {}).get("display_name") or ""),
                )
            )
        await self._respond(request_id, result)

    async def run(self) -> None:
        """Read JSON-RPC lines from stdin until EOF or shutdown."""
        if self._instance_blocked:
            await write_message(
                model_to_notification(
                    ProcessFailed(
                        reason=self._instance_blocked,
                        error_code="INSTANCE_IN_USE",
                    )
                )
            )
            return
        if os.environ.get("RXYCODE_APPSERVER_FAIL_BOOT") == "1":
            await write_message(
                model_to_notification(
                    ProcessFailed(reason="boot probe failed", error_code="BOOT_FAILED")
                )
            )
            self._instance_lock.release()
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        await self._emit_model(
            ProcessStarted(
                pid=os.getpid(),
                started_at=self._started_at,
            )
        )
        for session_id, previous in self._recovered_sessions:
            await self._emit_model(
                RecoveryRequired(session_id=session_id, previous_status=previous)
            )
        try:
            while not self._shutdown:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    break
                try:
                    message = parse_line(line)
                except (json.JSONDecodeError, ValueError):
                    await self._respond_error(None, -32700, "parse error")
                    continue
                if message is None:
                    continue
                try:
                    await self._dispatch(message)
                except Exception:
                    _logger.exception("dispatch failed for %s", message)
                    if "id" in message:
                        await self._respond_error(
                            message.get("id"), -32603, "internal error"
                        )

            if self._prompt_tasks:
                _done, pending = await asyncio.wait(
                    self._prompt_tasks,
                    timeout=_SHUTDOWN_PROMPT_WAIT_SECONDS,
                )
                if pending:
                    _logger.warning(
                        "shutdown: %d prompt task(s) still running after %.0fs; cancelling",
                        len(pending),
                        _SHUTDOWN_PROMPT_WAIT_SECONDS,
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            # Cancel in-flight emit writes with a bounded wait so blocked
            # to_thread writes cannot drag the server shutdown out.
            writer = self._notification_writer
            if writer is not None:
                writer.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(writer, timeout=2.0)
            for exc in self._notification_write_failures:
                _logger.error("emit write failed during shutdown: %r", exc)
            if not self._shutdown:
                self._mark_inflight_recovery_required()
                await self._emit_model(
                    ProcessShutdown(reason="eof-or-crash", graceful=False)
                )
            for session_id in list(self._session_hosts):
                await self._kill_session_host(session_id)
            self._instance_lock.release()
