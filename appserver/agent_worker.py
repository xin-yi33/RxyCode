"""Isolated AgentV2 worker subprocess (T1): killable bootstrap + prompt execution."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .bootstrap import bootstrap_agent
from .emitter import model_to_notification
from .jsonrpc import StreamCoalescer, stream_coalesce_enabled, write_message
from .runtime import bind_prompt_context, install_tui_context_hook, get_bound_tui, reset_prompt_context
from .tui import ProtocolTui

try:
    from ..protocol.notifications import (
        MessageDelta,
        ProgressUpdate,
        ReasoningSnapshot,
    )
except ImportError:
    from protocol.notifications import (
        MessageDelta,
        ProgressUpdate,
        ReasoningSnapshot,
    )

try:
    from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
    from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker
    from RxyCode.RxyCode1_1_0.core.question import set_question_broker
    from RxyCode.RxyCode1_1_0.core.session import Session
    from .question import PipeQuestionBroker
except ImportError:
    try:
        from ..core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
        from ..core.safety.approval import set_approval_broker
        from ..core.question import set_question_broker
        from ..core.session import Session
        from .question import PipeQuestionBroker
    except ImportError:
        from core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
        from core.safety.approval import set_approval_broker
        from core.question import set_question_broker
        from core.session import Session
        from appserver.question import PipeQuestionBroker

_logger = logging.getLogger(__name__)


def configure_agent_workspace(
    agent: Any,
    *,
    session_id: str,
    workspace_root: Path,
) -> Any:
    """Bind an AgentV2 instance to the worker's session-local workspace.

    AgentV2 historically starts with the compatibility session id ``latest``.
    A Desktop worker, however, owns a concrete session and an isolated
    workspace.  Leaving the default in place makes session-scoped tools read
    the wrong persisted cwd (or fall back to the appserver source tree).
    Configure both the agent metadata and the session-runtime cwd before the
    first prompt; this does not mutate process-global cwd and is safe for
    concurrent workers.
    """
    resolved_session_id = str(session_id)
    resolved_workspace = Path(workspace_root).resolve()
    resolved_workspace.mkdir(parents=True, exist_ok=True)
    agent._session_id = resolved_session_id
    agent._workspace_root = resolved_workspace
    try:
        from ..core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )
    except ImportError:
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

    token = bind_session(resolved_session_id)
    try:
        set_working_directory(resolved_workspace)
    finally:
        reset_session_binding(token)
    return agent


def resolve_subagent_task_token_budget() -> int:
    """Resolve a child task's aggregate budget from active-model metadata.

    This is not the provider request's max output tokens: one child task may
    make several model calls, so its aggregate guard follows the model context
    window. Unknown models use the configured fallback across four turns.
    """
    fallback = 131072
    try:
        try:
            from ..config.model_limits import resolve_configured_max_tokens
            from ..config.settings import get_active_model_config, load_config
        except ImportError:
            from config.model_limits import resolve_configured_max_tokens
            from config.settings import get_active_model_config, load_config

        cfg = load_config()
        model_config = get_active_model_config(cfg)
        unknown_output = int(
            (cfg.get("model_limits") or {}).get("unknown_model_max_tokens", 32768)
            or 32768
        )
        fallback = max(32768, unknown_output * 4)
        resolution = resolve_configured_max_tokens(
            model_config=model_config,
            capability_max_output_tokens=None,
            configured_max_tokens=model_config.get("max_tokens"),
            model_limits_config=cfg.get("model_limits"),
        )
        if isinstance(resolution.context_window, int) and resolution.context_window > 0:
            return resolution.context_window
    except (KeyError, TypeError, ValueError, OSError):
        _logger.warning(
            "could not resolve active model context for subagent budget; using fallback=%d",
            fallback,
        )
    return fallback


def bootstrap_subagent_manager(
    *,
    session_id: str,
    workspace_root: Path,
    emit: Callable[[str, dict[str, Any]], None],
) -> tuple[Any, Any]:
    """Create the single ChildSessionManager owned by this Primary worker."""
    try:
        from ..config.settings import get_dated_data_dir
        from ..core.subagents.events import EventStore
        from ..core.subagents.modes import subagent_config_from_env
        from ..core.subagents.registry_provider import init_manager
        from ..memory.long_term import validate_session_id
    except ImportError:
        from RxyCode.RxyCode1_1_0.config.settings import get_dated_data_dir
        from RxyCode.RxyCode1_1_0.core.subagents.events import EventStore
        from RxyCode.RxyCode1_1_0.core.subagents.modes import subagent_config_from_env
        from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import init_manager
        from RxyCode.RxyCode1_1_0.memory.long_term import validate_session_id

    safe_session_id = validate_session_id(session_id)
    persist_dir = (
        get_dated_data_dir("sessions")
        / "subagents"
        / safe_session_id
    )
    store = EventStore(persist_dir=persist_dir)
    manager = init_manager(
        config=subagent_config_from_env(
            default_max_tokens=resolve_subagent_task_token_budget()
        ),
        workspace_root=workspace_root.resolve(),
    )
    manager.set_event_store(store)
    manager.set_event_emitter(emit)
    return manager, store


class _PipeApproval(ApprovalBroker):
    """Forward approval requests to the parent appserver over worker stdout."""

    def __init__(self, send_request: Callable[[str, dict[str, Any]], Any]) -> None:
        super().__init__()
        self._send_request = send_request

    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        try:
            from .runtime import get_bound_session_id
        except ImportError:
            from appserver.runtime import get_bound_session_id

        session_id = get_bound_session_id()
        try:
            payload = await asyncio.wait_for(
                self._send_request(
                    "approval/request",
                    {
                        "session_id": session_id,
                        "request_id": request.approval_id,
                        "risk_level": request.risk.name,
                        "action": request.tool_name,
                        "details": {"args": request.args_summary},
                    },
                ),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            return ApprovalDecision.REJECTED
        decision_name = str(payload.get("decision", "rejected"))
        try:
            return ApprovalDecision(decision_name)
        except ValueError:
            return ApprovalDecision.REJECTED


class AgentWorker:
    def __init__(self) -> None:
        install_tui_context_hook()
        self._agent: Any | None = None
        self._subagent_manager: Any | None = None
        self._subagent_event_store: Any | None = None
        self._subagent_tasks: set[asyncio.Task[Any]] = set()
        self._session_id = "worker"
        self._workspace_root = Path.cwd()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._approval = _PipeApproval(self._send_parent_request)
        self._question = PipeQuestionBroker(self._send_parent_request, timeout=120.0)
        self._thinking_expanded = False
        self._active_tui: Any | None = None
        self._steer_queue: list[str] = []
        self._write_failures: list[BaseException] = []
        self._run_task: asyncio.Task[Any] | None = None
        #: Request ids that already got a terminal response, so an early-cancel
        #: path never double-replies to the parent.
        self._answered_request_ids: set[int] = set()
        #: Single serialized stdout writer (C3 ordering): every notification —
        #: stream notifications from the coalescer sink AND regular emits — is
        #: submitted to this FIFO queue and drained by one writer task, so
        #: stdout order matches emit order and terminal responses can be
        #: ordered after all queued notifications.
        self._write_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._write_task: asyncio.Task[Any] | None = None
        #: Serializes the terminal-response hand-off: drain -> submit ->
        #: wait is atomic against concurrent emits/other responses, so a
        #: response can never overtake notifications submitted before it.
        self._write_order_lock = asyncio.Lock()

    def _mark_answered(self, request_id: int) -> None:
        self._answered_request_ids.add(request_id)
        # Bound the dedup set: it only needs to cover in-flight prompts plus a
        # short trailing window, so it cannot grow without bound on a long-lived
        # worker.
        if len(self._answered_request_ids) > 64:
            # Discard the oldest half (insertion order is preserved).
            for old in list(self._answered_request_ids)[:32]:
                self._answered_request_ids.discard(old)

    async def _write_interrupted_response(
        self, request_id: int, *, run_id: str | None = None
    ) -> None:
        """Send the 'cancelled' terminal result for a cancelled prompt request.

        A notification flush failure must not prevent the terminal response:
        it is logged, then the response is still written best-effort (shielded)
        so the parent's pending request resolves instead of hanging.
        """
        try:
            await self._flush_pending_writes()
        except BaseException as exc:
            _logger.error("flush failed before interrupted response: %r", exc)
        result = {
            "status": "cancelled",
            "text": "",
            "thinking": None,
            "input_tokens": None,
            "output_tokens": None,
            "cache_hit_tokens": None,
            "cache_write_tokens": None,
            "cache_hit_rate": None,
            "reporting_status": "not_reported",
        }
        if run_id is not None:
            result["run_id"] = run_id
        await asyncio.shield(
            self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            )
        )
        self._mark_answered(request_id)

    def _ensure_writer(self) -> None:
        """Idempotently start the single serialized stdout writer (C3)."""
        if self._write_task is None or self._write_task.done():
            self._write_task = asyncio.get_running_loop().create_task(
                self._writer_loop()
            )

    async def _writer_loop(self) -> None:
        while True:
            message = await self._write_queue.get()
            try:
                await write_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Persist the failure so _flush_pending_writes surfaces it.
                self._write_failures.append(exc)
            finally:
                self._write_queue.task_done()

    def _schedule_write(self, message: dict[str, Any]) -> None:
        """Queue a stdout write (sync emit callbacks; T3: no sync I/O on
        loop).  FIFO with the coalescer sink -> write order == emit order."""
        self._ensure_writer()
        self._write_queue.put_nowait(message)

    async def _prompt_heartbeat(self, session_id: str) -> None:
        """Keep the appserver watchdog alive while the provider is silent.

        A model request or a long-running local tool can legitimately produce
        no model event for a while.  The watchdog must distinguish that from a
        dead worker, while the renderer still needs an honest waiting state.
        ``event/heartbeat`` remains an internal liveness signal; the paired
        ``event/progress`` is persisted and rendered as a compact status line.
        """
        raw_interval = os.environ.get(
            "RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS", "10"
        )
        try:
            interval = float(raw_interval)
        except (TypeError, ValueError):
            interval = 10.0
        if interval <= 0:
            return
        interval = max(0.25, min(interval, 30.0))
        while True:
            await asyncio.sleep(interval)
            self._schedule_write(
                {
                    "jsonrpc": "2.0",
                    "method": "event/heartbeat",
                    "params": {"session_id": session_id},
                }
            )
            self._schedule_write(
                {
                    "jsonrpc": "2.0",
                    "method": "event/progress",
                    "params": {
                        "session_id": session_id,
                        "text": "正在等待模型响应…",
                    },
                }
            )

    async def _flush_pending_writes(self) -> None:
        """Wait for all queued notifications to hit stdout before a result.

        Write failures are surfaced instead of silently swallowed: a lost
        notification breaks event ordering/observability, and a failing stdout
        means the parent is unreachable, so the caller should stop rather than
        keep running RPCs that can never be answered.
        """
        await asyncio.wait_for(self._write_queue.join(), timeout=10.0)
        failures = self._write_failures
        self._write_failures = []
        for exc in failures:
            _logger.error("notification write failed: %r", exc)
            raise RuntimeError("worker stdout write failed") from exc

    async def _write_ordered(self, message: dict[str, Any]) -> None:
        """Write a terminal response strictly after all queued notifications.

        Drains the queue first (so the response never overtakes already
        emitted notifications), then submits and waits for the response write
        itself.  The whole drain->submit->wait window is serialized by
        ``_write_order_lock`` so a concurrent emit or another response cannot
        slip in between the drain check and the response submission.  The
        wait is shielded by the caller when cancellation must not interrupt
        the hand-off.
        """
        self._ensure_writer()
        async with self._write_order_lock:
            await self._flush_pending_writes()
            self._write_queue.put_nowait(message)
            await asyncio.wait_for(self._write_queue.join(), timeout=10.0)

    async def _send_parent_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write_ordered(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            return await future
        finally:
            # Never leave a parent-response Future dangling: resolve it on any
            # path (response received, exception, timeout, cancellation).
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def _fail_all_parent_pending(self, exc: BaseException) -> None:
        """Fail every outstanding parent-request Future on shutdown/EOF."""
        pending = list(self._pending.items())
        self._pending.clear()
        for _request_id, future in pending:
            if not future.done():
                future.set_exception(exc)

    def _resolve_parent_response(self, message: dict[str, Any]) -> bool:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return False
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        if "error" in message:
            error = message.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", "parent request failed"))
            else:
                detail = str(error or "parent request failed")
            future.set_exception(RuntimeError(detail))
            return True
        result = message.get("result")
        if not isinstance(result, dict):
            result = {}
        future.set_result(result)
        return True

    async def _handle_bootstrap(self, params: dict[str, Any], request_id: int) -> None:
        stub = bool(params.get("stub", False))
        workspace = Path(str(params.get("workspace_root", ".")))
        self._workspace_root = workspace.resolve()
        self._session_id = str(params.get("session_id", "worker"))
        model_id = str(params.get("model_id") or "").strip() or None
        self._subagent_manager, self._subagent_event_store = bootstrap_subagent_manager(
            session_id=self._session_id,
            workspace_root=self._workspace_root,
            emit=lambda method, payload: self._schedule_write(
                {"jsonrpc": "2.0", "method": method, "params": payload}
            ),
        )
        set_approval_broker(self._approval)
        set_question_broker(self._question)
        # RLI-1: this per-session worker subprocess owns the process, so
        # changing cwd here is allowed.  bootstrap_agent is a library
        # factory and must not call os.chdir — any in-process caller would
        # otherwise permanently relocate the interpreter.  mkdir+chdir
        # happen before to_thread so load_config still runs under the
        # workspace cwd, matching the previous bootstrap_agent order.
        if self._workspace_root is None:
            self._workspace_root = Path(__file__).resolve().parents[1]
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        os.chdir(self._workspace_root)
        heartbeat_task = asyncio.create_task(self._prompt_heartbeat(self._session_id))
        try:
            self._agent = await asyncio.to_thread(
                bootstrap_agent,
                stub=stub,
                workspace_root=self._workspace_root,
                model_name=model_id,
            )
            self._agent = configure_agent_workspace(
                self._agent,
                session_id=self._session_id,
                workspace_root=self._workspace_root,
            )
            # Warm chat+agent prefixes on open, never on the first user turn.
            # Scheduling from run() races the greeting LLM call (90s hang).
            schedule = getattr(self._agent, "_schedule_prewarm", None)
            if callable(schedule):
                schedule()
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        await self._flush_pending_writes()
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"ok": True, "workspace_root": str(self._workspace_root)},
            }
        )

    async def _handle_prompt(self, params: dict[str, Any], request_id: int) -> None:
        if self._agent is None:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32002, "message": "bootstrap first"},
                }
            )
            return
        text = str(params.get("text", ""))
        run_id = str(params.get("run_id") or uuid.uuid4().hex)
        session_id = str(params.get("session_id", self._session_id))

        def emit(notification: BaseModel) -> None:
            # Ordering barrier: any buffered stream content is submitted to
            # the FIFO writer BEFORE this plain notification, so stdout order
            # matches TUI callback order for ALL notification kinds (not just
            # tool begin/end).
            tui._flush_pending_stream()
            self._schedule_write(model_to_notification(notification))

        tui = ProtocolTui(session_id, emit, run_id=run_id)
        expanded = bool(params.get("thinking_expanded", self._thinking_expanded))
        self._thinking_expanded = expanded
        tui.set_thinking_expanded(expanded)
        tokens = bind_prompt_context(session_id, tui)
        self._active_tui = tui

        # C3: batch per-token notifications through a StreamCoalescer
        # (RXYCODE_STREAM_COALESCE=1).  The sink submits the merged protocol
        # notification to the SAME FIFO write queue as regular emits, so
        # stdout order == emit order across stream and non-stream
        # notifications; the final flush happens in stop() before the result
        # so trailing tokens are never lost.  The sink is SYNC (a fast FIFO
        # enqueue) so the TUI's synchronous ordering barrier can submit
        # buffered stream content before plain emits.
        def make_stream_sink(sid: str) -> Callable[[str, str], None]:
            def sink(kind: str, text: str) -> None:
                if kind == "token":
                    message = model_to_notification(
                        MessageDelta(session_id=sid, text=str(text))
                    )
                elif kind == "reasoning":
                    message = model_to_notification(
                        ReasoningSnapshot(
                            session_id=sid, text=str(text), snapshot=False
                        )
                    )
                else:
                    message = model_to_notification(
                        ProgressUpdate(session_id=sid, text=str(text))
                    )
                self._schedule_write(message)

            return sink

        coalescer: StreamCoalescer | None = None
        heartbeat_task: asyncio.Task[Any] | None = None
        try:
            heartbeat_task = asyncio.create_task(self._prompt_heartbeat(session_id))
            if stream_coalesce_enabled():
                coalescer = StreamCoalescer(make_stream_sink(session_id))
                tui.set_coalescer(coalescer)
                await coalescer.start()

            session = Session(
                session_id=session_id,
                workspace_root=self._workspace_root,
                emit=emit,
            )
            try:
                prompt_kwargs = {
                    "mode": str(params.get("mode", "build")),
                    "run_id": run_id,
                    "permission_mode": params.get("permission_mode"),
                }
                # Keep the worker compatible with lightweight Session doubles
                # and older integrations while passing the request-local TUI
                # to the production Session implementation.
                try:
                    prompt_signature = inspect.signature(session.prompt)
                    accepts_tui = "tui" in prompt_signature.parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in prompt_signature.parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_tui = True
                if accepts_tui:
                    prompt_kwargs["tui"] = tui
                accepts_permission_mode = "permission_mode" in prompt_signature.parameters or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in prompt_signature.parameters.values()
                )
                if not accepts_permission_mode:
                    prompt_kwargs.pop("permission_mode", None)
                result = await session.prompt(self._agent, text, **prompt_kwargs)
                while self._steer_queue:
                    extra = self._steer_queue.pop(0)
                    result = await session.prompt(self._agent, extra, **prompt_kwargs)
            except asyncio.CancelledError:
                # Interrupt RPC cancelled this prompt task (C1): report the
                # cancellation to the host so the pending request resolves
                # instead of hanging until timeout.  The stream teardown runs
                # first (trailing flush) so the interrupted response never
                # overtakes already-emitted stream events.  The response
                # write is shielded so an interrupt in the write window
                # cannot leave the parent hanging.
                await self._wind_down_stream(tui, coalescer)
                await self._write_interrupted_response(request_id, run_id=run_id)
                # A real task cancellation must continue propagating so the
                # interrupt lifecycle remains cancellable. A Session may also
                # return CancelledError as a terminal result without the
                # handler task itself being cancelled; in that case the
                # terminal response is sufficient and the direct caller must
                # not receive an unexpected exception.
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
                return
            except Exception as exc:
                await self._wind_down_stream(tui, coalescer)
                # Order the error response after all already-queued
                # notifications (same contract as the success path); a
                # failing flush is logged but never blocks the terminal
                # response.
                await self._write_ordered_error(request_id, exc)
                self._mark_answered(request_id)
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Unified exit for Session-construction / coalescer-start failures
            # that occurred before the prompt body: tear the stream down first
            # (trailing flush), then order the terminal error response after
            # all queued notifications.
            await self._wind_down_stream(tui, coalescer)
            await self._write_ordered_error(request_id, exc)
            self._mark_answered(request_id)
            return
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            # Unified teardown: covers Session construction failures and any
            # error between coalescer.start() and the prompt body.  Idempotent
            # when the except branches already wound down.
            await self._wind_down_stream(tui, coalescer)
            reset_prompt_context(tokens)
            self._active_tui = None

        # Ensure notifications (e.g. reasoning_snapshot) reach stdout before
        # the result, so the client never observes the result arrive first.
        # The terminal response write is shielded so an interrupt arriving in
        # the write window cannot cancel it mid-flight; we mark answered only
        # after it has been handed off to the transport.
        await asyncio.shield(
            self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "run_id": run_id,
                        "status": result.status,
                        "text": result.answer,
                        "thinking": result.thinking,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cache_hit_tokens": getattr(result, "cache_hit_tokens", None),
                        "cache_write_tokens": getattr(result, "cache_write_tokens", None),
                        "cache_hit_rate": getattr(result, "cache_hit_rate", None),
                        "reporting_status": getattr(result, "reporting_status", "not_reported"),
                    },
                }
            )
        )
        self._mark_answered(request_id)

    async def _write_ordered_error(self, request_id: int, exc: BaseException) -> None:
        """Terminal error response strictly after all queued notifications
        (unified exit for prompt-body, Session-construction and start
        failures); a failing flush is logged but never blocks the response."""
        try:
            await self._flush_pending_writes()
        except Exception as flush_exc:
            _logger.error("flush failed before error response: %r", flush_exc)
        await asyncio.shield(
            self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            )
        )

    async def _wind_down_stream(self, tui: ProtocolTui, coalescer: Any) -> None:
        """C3 teardown for every prompt exit path (success / cancel / error).

        The drain->stop sequence runs in an INDEPENDENT teardown task.
        ``_teardown_stream_inner`` consumes the first CancelledError it
        receives (a cancellation of the caller may be observed by tasks it
        created) and keeps executing, so BOTH drain and stop always run; it
        re-raises at the end so the cancellation still propagates.  The
        teardown's sink puts land in the FIFO writer queue, so a terminal
        response that follows can never overtake them.  Failures inside the
        teardown are logged and never prevent the caller from sending its
        terminal response.
        """
        if coalescer is None:
            return
        teardown = asyncio.create_task(self._teardown_stream_inner(tui, coalescer))
        try:
            await asyncio.shield(teardown)
        except asyncio.CancelledError:
            # External cancellation: WAIT for the teardown task to finish
            # (drain -> stop) before propagating.  The wait is
            # cancellation-proof: asyncio.wait does not propagate a repeated
            # cancellation into the teardown task, it only aborts the wait,
            # which we retry until the teardown is done.
            while not teardown.done():
                try:
                    await asyncio.wait({teardown}, timeout=10.0)
                    break
                except asyncio.CancelledError:
                    continue
            if teardown.cancelled():
                pass
            elif teardown.exception() is not None:
                _logger.error("stream teardown failed: %r", teardown.exception())
            raise
        except Exception as exc:
            _logger.error("stream teardown failed: %r", exc)

    async def _teardown_stream_inner(
        self, tui: ProtocolTui, coalescer: Any
    ) -> None:
        """drain -> stop, completing BOTH steps even when the teardown task
        itself receives a cancellation: the first CancelledError is consumed
        (the task keeps running), the remaining steps still execute, and the
        cancellation is re-raised at the end so it propagates to the caller.
        """
        cancelled = False
        try:
            await tui.drain_push_tasks()
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:
            _logger.error("coalescer drain failed: %r", exc)
        for exc in tui.push_failures:
            _logger.error("coalescer push failed: %r", exc)
        try:
            await coalescer.stop()
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:
            _logger.error("coalescer stop failed: %r", exc)
        if cancelled:
            raise asyncio.CancelledError

    async def _handle_steer(self, params: dict[str, Any], request_id: int) -> None:
        text = str(params.get("text") or "").strip()
        if not text:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "text is required"},
                }
            )
            return
        running = self._run_task is not None and not self._run_task.done()
        if not running:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32014, "message": "turn is not running"},
                }
            )
            return
        self._steer_queue.append(text)
        self._schedule_write(
            model_to_notification(
                ProgressUpdate(session_id=self._session_id, text=f"steer: {text}")
            )
        )
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "ok": True,
                    "queued": True,
                    "session_id": self._session_id,
                    "pending": len(self._steer_queue),
                },
            }
        )

    async def _handle_interrupt(self, request_id: int) -> None:
        """Cancel the running prompt task (C1: run_task.cancel()).

        The interrupt RPC handler runs in its own dispatch task, so cancelling
        ``self._run_task`` (the task awaiting ``session.prompt``) is safe — it
        does not cancel the interrupt handler itself.
        """
        cancelled = False
        manager = self._subagent_manager
        child_tasks = [task for task in self._subagent_tasks if not task.done()]
        if manager is not None:
            manager.cancel_root(self._session_id)
        if child_tasks:
            for task in child_tasks:
                task.cancel()
            await asyncio.gather(*child_tasks, return_exceptions=True)
            cancelled = True
        run_task = self._run_task
        if run_task is not None and not run_task.done():
            # We cancelled a running prompt task: report the cancel intent.
            # Even if the prompt's own cancellation cleanup (flush/write) fails
            # and replaces the CancelledError with a write exception, the task
            # was genuinely interrupted — so report cancelled, not "not
            # cancelled".  (A task that already finished before the cancel
            # never enters this branch.)
            run_task.cancel()
            with contextlib.suppress(BaseException):
                await run_task
            cancelled = True
        elif self._agent is not None:
            session = Session(
                session_id=self._session_id,
                workspace_root=self._workspace_root,
                emit=lambda _n: None,
            )
            cancelled = session.interrupt(self._agent)
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"cancelled": cancelled},
            }
        )

    async def _handle_set_thinking_expanded(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        expanded = bool(params.get("expanded", False))
        self._thinking_expanded = expanded
        tui = self._active_tui or get_bound_tui()
        if tui is not None and hasattr(tui, "set_thinking_expanded"):
            tui.set_thinking_expanded(expanded)
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"ok": True, "expanded": expanded},
            }
        )

    async def _handle_model_switch(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        """Switch this worker's model while preserving task isolation."""
        if self._agent is None:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32002, "message": "bootstrap first"},
                }
            )
            return
        if self._run_task is not None and not self._run_task.done():
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32001,
                        "message": "cannot switch model during an active run",
                    },
                }
            )
            return
        model_id = str(params.get("model_id", "")).strip()
        if not model_id:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "model_id is required"},
                }
            )
            return
        result = self._agent.switch_model(model_id)
        if not isinstance(result, dict):
            result = {"model_id": model_id}
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"ok": True, **result},
            }
        )

    async def _handle_subagent_capability(self, request_id: int) -> None:
        manager = self._subagent_manager
        if manager is None:
            result = {
                "protocol_version": 1,
                "subagents_enabled": False,
                "task": False,
                "mention": False,
                "child_tasks": False,
                "active_lease_count": 0,
            }
        else:
            capability = manager.capability
            result = {
                "protocol_version": capability.protocol_version,
                "subagents_enabled": capability.subagents_enabled,
                "task": capability.task,
                "mention": capability.mention,
                "child_tasks": capability.child_tasks,
                "active_lease_count": manager.active_lease_count,
            }
        await self._write_ordered(
            {"jsonrpc": "2.0", "id": request_id, "result": result}
        )

    def _require_subagent_manager(self) -> Any:
        if self._subagent_manager is None:
            raise RuntimeError("bootstrap first")
        return self._subagent_manager

    async def _handle_subagent_list(self, request_id: int) -> None:
        manager = self._require_subagent_manager()
        agents = [
            {
                "id": definition.id,
                "description": definition.description,
                "mode": definition.mode.value,
                "model": definition.model,
            }
            for definition in manager.registry.list_visible()
        ]
        await self._write_ordered(
            {"jsonrpc": "2.0", "id": request_id, "result": {"agents": agents}}
        )

    def _parse_subagent_request(self, params: dict[str, Any], *, mention: bool):
        try:
            from ..protocol.subagents import (
                BudgetSpec,
                TaskRequest,
                TriggerKind,
                WorkspaceMode,
                WorkspaceScope,
            )
        except ImportError:
            from protocol.subagents import (
                BudgetSpec,
                TaskRequest,
                TriggerKind,
                WorkspaceMode,
                WorkspaceScope,
            )

        agent_id = str(params.get("agent_id", "")).strip()
        prompt = str(params.get("prompt", "")).strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if not prompt:
            raise ValueError("prompt is required")

        budget = None
        raw_budget = params.get("requested_budget")
        if isinstance(raw_budget, dict):
            budget = BudgetSpec(
                max_steps=int(raw_budget.get("max_steps", 12)),
                max_tokens=int(raw_budget.get("max_tokens", 8000)),
                max_wall_time_seconds=int(
                    raw_budget.get("max_wall_time_seconds", 300)
                ),
                max_concurrent_children=int(
                    raw_budget.get("max_concurrent_children", 3)
                ),
            )

        workspace = None
        raw_workspace = params.get("requested_workspace")
        if isinstance(raw_workspace, dict):
            workspace = WorkspaceScope(
                mode=WorkspaceMode(str(raw_workspace.get("mode", "read_only"))),
                leased_paths=tuple(
                    str(path) for path in raw_workspace.get("leased_paths", [])
                ),
                lease_id=str(raw_workspace.get("lease_id", "")),
            )

        return TaskRequest(
            request_id=str(params.get("request_id") or uuid.uuid4()),
            parent_session_id=str(
                params.get("parent_session_id")
                or params.get("root_session_id")
                or self._session_id
            ),
            agent_id=agent_id,
            prompt=prompt,
            trigger=TriggerKind.MENTION if mention else TriggerKind.AUTOMATIC,
            output_schema=(
                str(params["output_schema"])
                if params.get("output_schema") is not None
                else None
            ),
            requested_budget=budget,
            requested_workspace=workspace,
        )

    async def _run_subagent_dispatch(self, request: Any) -> None:
        try:
            await self._require_subagent_manager().dispatch(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Pre-session validation failures still need an observable,
            # persisted terminal record correlated by request id.
            try:
                from ..core.subagents.events import build_event
            except ImportError:
                from RxyCode.RxyCode1_1_0.core.subagents.events import build_event

            event = build_event(
                "child_session/denied",
                f"request:{request.request_id}",
                request.parent_session_id,
                root_session_id=self._session_id,
                request_id=request.request_id,
                payload={
                    "agent_id": request.agent_id,
                    "status": "denied",
                    "error": str(exc),
                    "code": getattr(exc, "code", "dispatch_error"),
                },
            )
            if self._subagent_event_store is not None:
                event = self._subagent_event_store.append(event)
            self._schedule_write(
                {
                    "jsonrpc": "2.0",
                    "method": "child_session/denied",
                    "params": event.to_dict(),
                }
            )

    async def _handle_subagent_start(
        self, params: dict[str, Any], request_id: int, *, mention: bool
    ) -> None:
        request = self._parse_subagent_request(params, mention=mention)
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"accepted": True, "request_id": request.request_id},
            }
        )
        task = asyncio.create_task(self._run_subagent_dispatch(request))
        self._subagent_tasks.add(task)
        task.add_done_callback(self._subagent_tasks.discard)

    @staticmethod
    def _session_to_dict(session: Any) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "parent_session_id": session.parent_session_id,
            "root_session_id": session.root_session_id,
            "agent_id": session.agent_id,
            "trigger": session.trigger.value,
            "definition_version": session.definition_version,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "started_at": (
                session.started_at.isoformat() if session.started_at else None
            ),
            "terminal_at": (
                session.terminal_at.isoformat() if session.terminal_at else None
            ),
            "event_cursor": session.event_cursor,
        }

    async def _handle_child_sessions_list(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        manager = self._require_subagent_manager()
        root = str(params.get("root_session_id") or self._session_id)
        sessions = [
            self._session_to_dict(session)
            for session in manager.get_tree(root).list_all()
        ]
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"root_session_id": root, "sessions": sessions},
            }
        )

    async def _handle_child_session_events(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        store = self._subagent_event_store
        if store is None:
            raise RuntimeError("bootstrap first")
        root = str(params.get("root_session_id") or self._session_id)
        cursor = max(0, int(params.get("cursor", 0)))
        latest = store.latest_cursor()
        events = [
            event.to_dict()
            for event in store.events_from(cursor)
            if event.root_session_id == root
        ]
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "events": events,
                    "next_cursor": latest,
                    "gap_detected": bool(store.detect_gaps(cursor, latest)),
                },
            }
        )

    async def _handle_child_session_cancel(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        manager = self._require_subagent_manager()
        root = str(params.get("root_session_id") or self._session_id)
        session_id = str(params.get("session_id", ""))
        if session_id:
            manager.cancel_session(root, session_id)
        else:
            manager.cancel_root(root)
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"cancelled": True, "root_session_id": root, "session_id": session_id or None},
            }
        )

    async def _handle_child_session_retry(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        manager = self._require_subagent_manager()
        root = str(params.get("root_session_id") or self._session_id)
        session_id = str(params.get("session_id", ""))
        if not session_id:
            raise ValueError("session_id is required")
        retry_request_id = str(params.get("request_id") or uuid.uuid4())
        await self._write_ordered(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"accepted": True, "request_id": retry_request_id},
            }
        )
        task = asyncio.create_task(
            manager.retry_session(
                root, session_id, request_id=retry_request_id
            )
        )
        self._subagent_tasks.add(task)
        task.add_done_callback(self._subagent_tasks.discard)

    async def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            if self._resolve_parent_response(message):
                return
        if message.get("method") is None:
            return
        request_id = message.get("id")
        if not isinstance(request_id, int):
            # A request without a valid integer id cannot be answered; treat it
            # as a notification and drop it so callers do not hang waiting.
            return
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        method = str(message.get("method", ""))
        if method == "bootstrap":
            await self._handle_bootstrap(params, int(request_id))
        elif method == "model/switch":
            await self._handle_model_switch(params, int(request_id))
        elif method == "prompt":
            await self._handle_prompt(params, int(request_id))
        elif method == "interrupt":
            await self._handle_interrupt(int(request_id))
        elif method == "prompt/steer":
            await self._handle_steer(params, int(request_id))
        elif method == "thinking/set_expanded":
            await self._handle_set_thinking_expanded(params, int(request_id))
        elif method == "subagents/capability":
            await self._handle_subagent_capability(int(request_id))
        elif method == "subagents/list":
            await self._handle_subagent_list(int(request_id))
        elif method == "agent/invoke":
            await self._handle_subagent_start(params, int(request_id), mention=True)
        elif method == "task/start":
            await self._handle_subagent_start(params, int(request_id), mention=False)
        elif method == "child_sessions/list":
            await self._handle_child_sessions_list(params, int(request_id))
        elif method == "child_sessions/events":
            await self._handle_child_session_events(params, int(request_id))
        elif method == "child_sessions/cancel":
            await self._handle_child_session_cancel(params, int(request_id))
        elif method == "child_sessions/retry":
            await self._handle_child_session_retry(params, int(request_id))
        elif method == "shutdown":
            await self._write_ordered(
                {"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}
            )
            raise SystemExit(0)
        else:
            await self._write_ordered(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"unknown method: {method}"},
                }
            )

    async def _dispatch_safe(self, message: dict[str, Any]) -> None:
        try:
            await self._dispatch(message)
        except SystemExit:
            raise
        except asyncio.CancelledError:
            # If the prompt task was cancelled *before* its own handler could
            # send the interrupted response (e.g. interrupt arrived before the
            # task first ran), answer here so the parent's pending request does
            # not hang until timeout.  Idempotent via _answered_request_ids
            # (marked only after the response write succeeds, inside
            # _write_interrupted_response).
            request_id = message.get("id")
            if (
                message.get("method") == "prompt"
                and isinstance(request_id, int)
                and request_id not in self._answered_request_ids
            ):
                # The task is in a cancelled state, so a bare await here would
                # re-raise CancelledError immediately; shield the write.
                await asyncio.shield(
                    self._write_interrupted_response(request_id)
                )
            raise
        except Exception as exc:
            _logger.exception("worker dispatch failed for %s", message)
            # Reply with a JSON-RPC error so the parent's pending request does
            # not hang until timeout.
            request_id = message.get("id")
            if isinstance(request_id, int) and not (
                "result" in message or "error" in message
            ):
                await self._write_ordered(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        pending: set[asyncio.Task[Any]] = set()
        self._ensure_writer()
        try:
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    if self._resolve_parent_response(message):
                        continue
                if message.get("method") == "shutdown":
                    await self._write_ordered(
                        {
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "result": {"ok": True},
                        }
                    )
                    break
                if message.get("method") == "prompt":
                    self._run_task = loop.create_task(self._dispatch_safe(message))
                    task = self._run_task

                    def _clear_run(
                        _t: asyncio.Task[Any], _rid: int = int(message.get("id"))
                    ) -> None:
                        if self._run_task is _t:
                            self._run_task = None
                        if (
                            _t.cancelled()
                            and _rid not in self._answered_request_ids
                        ):
                            # The prompt task was cancelled before it could
                            # answer (e.g. interrupt before first step): send
                            # the interrupted result from a fresh task so the
                            # parent's pending request does not hang.  The
                            # answered marker is set inside the write.
                            loop.create_task(
                                self._write_interrupted_response(_rid)
                            )

                    task.add_done_callback(_clear_run)
                else:
                    task = loop.create_task(self._dispatch_safe(message))
                pending.add(task)
                task.add_done_callback(pending.discard)
        except Exception:
            raise
        finally:
            for task in list(self._subagent_tasks):
                task.cancel()
            await asyncio.gather(*self._subagent_tasks, return_exceptions=True)
            self._subagent_tasks.clear()
            for task in list(pending):
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            # Wind down the single serialized writer: try a bounded drain FIRST
            # so queued notifications (e.g. an interrupted response) are still
            # delivered; only on timeout cancel the writer and record what was
            # left behind.
            writer = self._write_task
            drained = True
            try:
                await asyncio.wait_for(self._write_queue.join(), timeout=2.0)
            except asyncio.TimeoutError:
                drained = False
                remaining = self._write_queue.qsize()
                _logger.warning(
                    "worker shutdown: %d queued write(s) not delivered within "
                    "the bounded drain",
                    remaining,
                )
            # Always stop the writer explicitly (also after a successful
            # drain) so no background task outlives the worker.
            if writer is not None and not writer.done():
                writer.cancel()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(writer, return_exceptions=True), timeout=2.0
                    )
            if not drained:
                _logger.warning("worker shutdown: writer cancelled with undelivered writes")
            for exc in self._write_failures:
                _logger.error("notification write failed during shutdown: %r", exc)
            # Worker is going down: fail any outstanding parent-request
            # Futures (e.g. an approval awaiting a parent response) instead of
            # leaving them pending forever.
            self._fail_all_parent_pending(RuntimeError("worker shutdown"))


def _configure_event_loop() -> None:
    """C5: prefer uvloop on non-Windows when RXYCODE_UVLOOP=1 (default).

    Windows is not supported by uvloop; a missing uvloop falls back to the
    default asyncio loop.  Must run before ``asyncio.run`` so the loop
    policy is installed before the loop is created.
    """
    if os.environ.get("RXYCODE_UVLOOP", "1") != "1":
        return
    if sys.platform == "win32":
        return
    try:
        import uvloop  # noqa: PLC0415

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass  # fall back to the default loop; unit-tested


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _configure_event_loop()
    asyncio.run(AgentWorker().run())


if __name__ == "__main__":
    main()
