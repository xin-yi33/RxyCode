"""Stdio JSON-RPC appserver (Phase 2 P4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
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
from .runtime import install_tui_context_hook
from .sessions import SessionStore
from .watchdog import ActiveJob, WatchdogState, heartbeat_interval_seconds, stall_timeout_seconds

try:
    from ..core.safety.approval import set_approval_broker
    from ..protocol.notifications import JobStatusUpdate, ServerHeartbeat
    from ..protocol.version import PROTOCOL_VERSION
except ImportError:
    from core.safety.approval import set_approval_broker
    from protocol.notifications import JobStatusUpdate, ServerHeartbeat
    from protocol.version import PROTOCOL_VERSION

_logger = logging.getLogger(__name__)

_DEFAULT_PROMPT_TIMEOUT_SECONDS = 600.0
_SHUTDOWN_PROMPT_WAIT_SECONDS = 30.0


class AppServer:
    """Headless JSON-RPC server over stdin/stdout."""

    def __init__(self, *, stub: bool = False) -> None:
        install_tui_context_hook()
        self._stub = stub
        self._shutdown = False
        self._initialized = False
        self._sessions = SessionStore()
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
        self._job_tasks: dict[str, asyncio.Task[Any]] = {}
        self._resolved_jobs: set[str] = set()

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def _host_for_session(self, session_id: str) -> AgentHost:
        host = self._session_hosts.get(session_id)
        if host is not None and host.alive():
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
            stub=self._stub,
            project_root=project_root,
            forward_server_request=self._send_server_request,
            main_loop=asyncio.get_running_loop(),
        )
        self._session_hosts[session_id] = host
        return host

    async def _kill_session_host(self, session_id: str) -> None:
        host = self._session_hosts.pop(session_id, None)
        if host is not None:
            await host.kill_async()

    async def _emit_model(self, model: BaseModel) -> None:
        await write_message(model_to_notification(model))

    async def _emit_job_state(self, session_id: str, job_id: str, state: str) -> None:
        await self._emit_model(
            JobStatusUpdate(session_id=session_id, job_id=job_id, state=state)
        )

    async def _respond(self, request_id: Any, result: Any) -> None:
        await write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _respond_error(
        self, request_id: Any, code: int, message: str, data: Any = None
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        await write_message({"jsonrpc": "2.0", "id": request_id, "error": error})

    async def _send_server_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = self._next_server_id
        self._next_server_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_server[request_id] = future
        await write_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            return await future
        finally:
            self._pending_server.pop(request_id, None)

    def _resolve_server_response(self, message: dict[str, Any]) -> bool:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return False
        future = self._pending_server.get(request_id)
        if future is None or future.done():
            return False
        if "error" in message:
            error = message.get("error") or {}
            future.set_exception(
                RuntimeError(str(error.get("message", "server request failed")))
            )
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
        await self._fail_job(
            session_id=stalled.session_id,
            job_id=stalled.job_id,
            request_id=stalled.request_id,
            code=-32004,
            message=reason,
            kill_host=True,
            degrade_reason=reason,
        )
        task = self._job_tasks.get(stalled.job_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _handle_initialize(self, params: dict[str, Any], request_id: Any) -> None:
        client_version = str(params.get("protocol_version", ""))
        if client_version and client_version != PROTOCOL_VERSION:
            _logger.warning(
                "client protocol %s != server %s",
                client_version,
                PROTOCOL_VERSION,
            )
        self._initialized = True
        await self._respond(
            request_id,
            {
                "protocol_version": PROTOCOL_VERSION,
                "server_name": "rxycode-appserver",
                "capabilities": {"sessions": True, "approval": True},
            },
        )

    async def _handle_session_new(self, params: dict[str, Any], request_id: Any) -> None:
        workspace = params.get("workspace_root")
        if not isinstance(workspace, str) or not workspace.strip():
            await self._respond_error(request_id, -32602, "workspace_root is required")
            return
        record = self._sessions.create(Path(workspace))
        self._active_session_id = record.session_id
        await self._respond(
            request_id,
            {
                "session_id": record.session_id,
                "workspace_root": str(record.workspace_root),
            },
        )

    async def _run_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: Any,
        job_id: str,
        timeout_seconds: float | None,
        mode: str = "build",
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

        current = asyncio.current_task()
        if current is not None:
            self._job_tasks[job_id] = current

        try:
            async with self._session_lock(session_id):
                await self._emit_job_state(session_id, job_id, "submitted")
                await self._emit_job_state(session_id, job_id, "running")

                run_id = uuid.uuid4().hex
                self._watchdog.register_job(job_id, session_id, request_id)

                def emit_message(message: dict[str, Any]) -> None:
                    self._watchdog.touch_job(job_id)
                    write_message_sync(message)

                async def _execute_prompt() -> dict[str, Any]:
                    host = await self._host_for_session(session_id)
                    await host.ensure_bootstrapped(timeout=wall_timeout)
                    return await host.run_prompt(
                        text=text,
                        run_id=run_id,
                        timeout=wall_timeout,
                        emit=emit_message,
                        mode=mode,
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

                await self._respond(
                    request_id,
                    {
                        "run_id": payload.get("run_id", run_id),
                        "status": status,
                        "text": payload.get("text", ""),
                        "thinking": payload.get("thinking"),
                        "input_tokens": payload.get("input_tokens"),
                        "output_tokens": payload.get("output_tokens"),
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
        await self._run_prompt(
            session_id=session_id,
            text=text,
            request_id=request_id,
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            mode=mode,
        )

    async def _handle_interrupt(self, params: dict[str, Any], request_id: Any) -> None:
        session_id = str(params.get("session_id", self._active_session_id))
        record = self._sessions.get(session_id)
        if record is None:
            await self._respond_error(request_id, -32001, f"unknown session: {session_id}")
            return
        host = self._session_hosts.get(session_id)
        cancelled = False
        if host is not None and host.alive():
            try:
                result = await asyncio.to_thread(
                    host._request, "interrupt", {}, timeout=5.0
                )
                cancelled = bool(result.get("cancelled"))
            except Exception:
                await self._kill_session_host(session_id)
        await self._respond(request_id, {"cancelled": cancelled, "session_id": session_id})

    async def _heartbeat_loop(self) -> None:
        interval = heartbeat_interval_seconds()
        while not self._shutdown:
            await asyncio.sleep(interval)
            for stalled in list(self._watchdog.stalled_jobs()):
                await self._handle_stalled_job(stalled)
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
        await self._respond(request_id, {"ok": True})

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

        if method == "initialize":
            await self._handle_initialize(params, request_id)
            return
        if not self._initialized and method != "shutdown":
            await self._respond_error(request_id, -32002, "call initialize first")
            return

        if method == "session/new":
            await self._handle_session_new(params, request_id)
        elif method == "session/prompt":
            task = asyncio.create_task(self._handle_prompt(params, request_id))
            self._prompt_tasks.add(task)
            task.add_done_callback(self._prompt_tasks.discard)
        elif method == "session/interrupt":
            await self._handle_interrupt(params, request_id)
        elif method == "shutdown":
            await self._handle_shutdown(params, request_id)
        else:
            await self._respond_error(request_id, -32601, f"method not found: {method}")

    async def run(self) -> None:
        """Read JSON-RPC lines from stdin until EOF or shutdown."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
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
            for session_id in list(self._session_hosts):
                await self._kill_session_host(session_id)
