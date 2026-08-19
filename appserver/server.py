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
from .workspace import PathBoundaryError, assert_exists, canonicalize
from .sessions import SessionStore
from .task_store import DesktopTaskStore
from .watchdog import ActiveJob, WatchdogState, heartbeat_interval_seconds, stall_timeout_seconds

try:
    from ..core.safety.approval import set_approval_broker
    from ..protocol.errors import JSONRPC_STABLE_CODE, error_payload
    from ..protocol.handshake import (
        CapabilitySnapshot,
        InitializeResult,
        ModelProviderSummary,
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
        from config.model_catalog import ModelCatalog

        catalog = ModelCatalog.load()
    except Exception:
        return []
    seen: dict[str, ModelProviderSummary] = {}
    for record in catalog._exact.values():
        if record.provider_id in seen:
            continue
        seen[record.provider_id] = ModelProviderSummary(
            provider_id=record.provider_id,
            model_id=record.model_id,
            model_context_window=record.model_context_window,
            model_max_output_tokens=record.model_max_output_tokens,
            limit_source="model-metadata" if record.model_max_output_tokens else "fallback",
            is_fallback=record.model_max_output_tokens is None,
        )
    return list(seen.values())


def _permission_profiles() -> list[PermissionProfileSummary]:
    """Advertise modes the appserver already enforces. G names wait for B7."""
    return [
        PermissionProfileSummary(
            profile_id="confirm_all",
            selectable=True,
            description="Existing appserver mode: confirm risky actions",
        ),
        PermissionProfileSummary(
            profile_id="auto_edit",
            selectable=True,
            description="Existing appserver mode: auto-apply edits",
        ),
        PermissionProfileSummary(
            profile_id="full_auto",
            selectable=True,
            description="Existing appserver mode: auto",
        ),
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
    "event/token_usage",
    "event/final",
    "event/done",
    "event/recovery_started",
    "event/recovery_analyzing",
    "event/recovery_attempt",
    "event/recovery_resolved",
    "event/recovery_exhausted",
    "event/recovery_required",
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

    def _ensure_notification_writer(self) -> None:
        if self._notification_writer is None or self._notification_writer.done():
            self._notification_writer = asyncio.create_task(
                self._notification_writer_loop()
            )

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

    def _schedule_notification(self, message: dict[str, Any]) -> None:
        self._ensure_notification_writer()
        self._notification_queue.put_nowait(message)

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
        if method.startswith("child_session/") or method.startswith("approval/"):
            persist_event = True
        else:
            persist_event = method in _REPLAY_EVENT_METHODS
        if not persist_event:
            # Streaming deltas are intentionally not written one by one. The
            # final event and tool/recovery records are sufficient to rebuild
            # a completed task, while skipping deltas avoids both prompt-like
            # content in the durable task index and an fsync per token.
            return
        session_id = params.get("root_session_id") or params.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

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
        elif method in {"event/token_usage", "event/final"}:
            self._sessions.update_usage(
                session_id,
                {
                    "input_tokens": safe_params.get("input_tokens"),
                    "output_tokens": safe_params.get("output_tokens"),
                    "cache_hit_tokens": safe_params.get("cache_hit_tokens"),
                    "cache_write_tokens": safe_params.get("cache_write_tokens"),
                    "cache_hit_rate": safe_params.get("cache_hit_rate"),
                    "reporting_status": safe_params.get("reporting_status", "not_reported"),
                },
            )

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
        result = InitializeResult(
            capabilities={
                "sessions": True,
                "approval": True,
                "models": True,
                "credentials": True,
            },
            capability_snapshot=CapabilitySnapshot(),
            model_providers=_model_provider_summaries(),
            permission_profiles=_permission_profiles(),
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

                await self._respond(
                    request_id,
                    {
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
                    },
                )
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
        await self._run_prompt(
            session_id=session_id,
            text=text,
            request_id=request_id,
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            mode=mode,
            thinking_expanded=thinking_expanded,
            permission_mode=permission_mode,
        )

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

    @staticmethod
    def _session_summary(record: Any) -> dict[str, Any]:
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
            "child_count": 0,
            "usage": dict(record.usage),
        }

    async def _handle_sessions_list(self, params: dict[str, Any], request_id: Any) -> None:
        include_trashed = bool(params.get("include_trashed", False))
        await self._respond(
            request_id,
            {"sessions": [self._session_summary(record) for record in self._sessions.list(include_trashed=include_trashed)]},
        )

    async def _handle_session_events(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", ""))
        if self._sessions.get(session_id) is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        cursor = int(params.get("cursor", 0) or 0)
        events, next_cursor, gap = self._task_store.events(session_id, cursor)
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
