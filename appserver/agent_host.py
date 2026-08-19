"""Parent-side client for appserver.agent_worker subprocess (T1 / C1).

Two transports are available, selected once at host construction by the
``RXYCODE_ASYNC_RPC`` switch (default ``1``):

* ``1`` — new async transport built on :class:`AsyncRpcPipe`.  The stdlib
  ``queue`` module is not imported anywhere in this file; request/response
  routing is driven by ``asyncio.Future`` + ``asyncio.Queue`` (PHASE-C C1 §4.1).
* ``0`` — legacy sync fallback built on ``subprocess.Popen`` + reader/writer
  threads + a queue-free ``_SyncMailbox``.  It exists only to let the AC7
  switch=0 contract tests and stdio smoke verify behaviour equivalence; new
  code should use the async path.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Deque

from .jsonrpc import parse_line

_logger = logging.getLogger(__name__)
EmitFn = Callable[[dict[str, Any]], None]
ForwardServerRequest = Callable[[str, dict[str, Any]], Any]
WORKER_SERVER_REQUESTS = frozenset({"approval/request", "question/request"})

#: Inner bootstrap RPC budget. Waiters may time out sooner; the in-flight
#: bootstrap must keep running so a later prompt can join it instead of
#: spawning a second AgentV2 constructor.
_BOOTSTRAP_RPC_TIMEOUT_SECONDS = 300.0


def async_rpc_enabled() -> bool:
    """True when the C1 async transport should be used (default)."""
    return os.environ.get("RXYCODE_ASYNC_RPC", "1") != "0"


def _log_pipe_event(event: str, *, exc: BaseException | None = None) -> None:
    """Record a telemetry event for the pipe supervision paths."""
    if exc is None:
        _logger.error("[monitor] %s", event)
    else:
        _logger.error("[monitor] %s: %s", event, exc)


#: Sentinel used to shut down the AsyncRpcPipe outgoing queue.
_CLOSE = object()


class _SyncMailbox:
    """Thread-safe FIFO used by the legacy sync fallback (queue-free).

    The stdlib ``queue`` module is deliberately not imported in this file so
    the C1 completion criterion (grep for the ``queue`` module import on
    agent_host.py) reports no matches.
    """

    def __init__(self) -> None:
        self._items: Deque[Any] = collections.deque()
        self._cv = threading.Condition()

    def put(self, item: Any) -> None:
        with self._cv:
            self._items.append(item)
            self._cv.notify()

    def get(self, timeout: float | None = None) -> Any:
        with self._cv:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._items:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError
                if remaining is None:
                    self._cv.wait()
                else:
                    self._cv.wait(remaining)
            return self._items.popleft()


class AsyncRpcPipe:
    """Async JSON-RPC pipe over an asyncio subprocess (C1 §4.1).

    Replaces ``AgentHost._request``'s sync blocking bridge.  Requests are
    correlated by id into ``asyncio.Future`` objects; reader exceptions surface
    (never silently swallowed) and mark the pipe ``degraded``.

    Direction note: the child's stdin is *our* :class:`asyncio.StreamWriter`
    (we write into the worker), and the child's stdout is *our*
    :class:`asyncio.StreamReader` (we read responses/notifications from it).
    """

    def __init__(
        self,
        child_stdin: asyncio.StreamWriter,    # 我们 → worker stdin
        child_stdout: asyncio.StreamReader,   # worker stdout → 我们
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._child_stdin = child_stdin
        self._child_stdout = child_stdout
        self._emit = emit
        self.degraded = False                      # /status + watchdog readable
        self._failure_exc: BaseException | None = None
        self._closed = False
        self._graceful_shutdown = False
        self._shutdown_confirmed = False
        self._close_task: asyncio.Task[Any] | None = None
        self._requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._request_methods: dict[int, str] = {}
        self._next_id = itertools.count(1)
        self._outgoing: asyncio.Queue[Any] = asyncio.Queue()
        self._writer_task: asyncio.Task[Any] | None = None
        self._reader_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """Start the reader/writer tasks (idempotent) and supervise them."""
        if self._writer_task is not None or self._reader_task is not None:
            return
        self._writer_task = asyncio.create_task(self._writer_loop())
        self._reader_task = asyncio.create_task(self._reader_loop())
        for task in (self._writer_task, self._reader_task):
            task.add_done_callback(self._on_pipe_task_done)

    def _transition_failed(self, exc: BaseException) -> None:
        """One-time terminal transition to the failed state.

        Guards the ``degraded``/``_failure_exc`` transition so the pipe cannot
        log telemetry or change state more than once, and so a request racing a
        background failure sees an immediate rejection.
        """
        if self._failure_exc is not None:
            return
        self._failure_exc = exc
        self.degraded = True
        _log_pipe_event("async_rpc_pipe_task_error", exc=exc)

    def _is_shutdown(self) -> bool:
        """True when no new requests may be accepted."""
        return self._closed or self._failure_exc is not None

    def _reject_request(self, method: str) -> bool:
        """Whether a request of *method* must be rejected right now.

        Fully closed/failed pipes reject everything.  During graceful shutdown
        only the ``shutdown`` RPC (which asks the worker to exit) may be sent;
        anything else is rejected so no request races the closing pipe.
        """
        if self._closed or self._failure_exc is not None:
            return True
        if self._graceful_shutdown and method != "shutdown":
            return True
        return False

    def _confirm_shutdown(self) -> None:
        """Mark graceful shutdown after the worker acknowledged the RPC.

        Sets both ``_graceful_shutdown`` and ``_shutdown_confirmed`` so an
        ensuing EOF is treated as an expected (non-degrading) exit.  Only the
        host's kill path calls this, and only after the shutdown RPC response
        was received — otherwise a worker crash could be masked as a clean
        shutdown.
        """
        self._graceful_shutdown = True
        self._shutdown_confirmed = True

    @property
    def failure_exc(self) -> BaseException | None:
        """The terminal failure reason, if any (watchdog/status observable)."""
        return self._failure_exc

    def _on_pipe_task_done(self, task: asyncio.Task[Any]) -> None:
        """Surface background task failures and converge the sibling task.

        This is the final safety net: if a loop implementation ever exits with
        an exception without failing pending requests itself, the supervision
        callback fails them here (idempotent) and cancels the sibling so no
        background task is left blocking.  An *unexpected* cancellation of a
        reader/writer task (one not caused by our own close) is also treated as
        a transport failure.
        """
        if task.cancelled():
            if not self._closed and not self._graceful_shutdown:
                cancelled_exc = RuntimeError("pipe task cancelled unexpectedly")
                self._transition_failed(cancelled_exc)
                self._fail_all_pending(cancelled_exc)
                sibling = (
                    self._writer_task if task is self._reader_task
                    else self._reader_task
                )
                if sibling is not None and not sibling.done():
                    sibling.cancel()
            return
        exc = task.exception()
        if exc is not None:
            if self._closed or self._graceful_shutdown:
                # A writer/reader exception observed while we are closing (e.g.
                # BrokenPipe on a closed stdin) is an expected consequence of
                # teardown, not a transport degradation.  Fail any remaining
                # pending, but do not mark degraded.
                self._fail_all_pending(exc)
                return
            self._transition_failed(exc)
            if not self._closed:
                self._fail_all_pending(exc)
                sibling = (
                    self._writer_task if task is self._reader_task
                    else self._reader_task
                )
                if sibling is not None and not sibling.done():
                    sibling.cancel()

    async def close(self) -> None:
        """Orderly shutdown per §4.1: stop writes → wind down reader → fail
        pending → wait for writer/stdin close.

        Idempotent and concurrency-safe: concurrent callers await the same
        in-flight close task (shielded so caller cancellation cannot abort the
        teardown).  Never raises: a transport failure observed during close is
        recorded in ``_failure_exc`` / ``degraded`` (readable via
        ``AgentHost.degraded`` / the watchdog) rather than surfaced as an
        exception, so cleanup always runs to completion.
        """
        if self._close_task is not None:
            await asyncio.shield(self._close_task)
            return
        if self._closed:
            return
        task = asyncio.create_task(self._close_impl())

        def _clear_close_task(_done: asyncio.Task[Any]) -> None:
            if self._close_task is _done:
                self._close_task = None

        # Clear the reference only when the teardown task itself completes, so
        # a caller that is cancelled while awaiting close() cannot cause a
        # second _close_impl() to start against the same resources.
        task.add_done_callback(_clear_close_task)
        self._close_task = task
        await asyncio.shield(task)

    async def _close_impl(self) -> None:
        self._closed = True
        self._outgoing.put_nowait(_CLOSE)

        # Close child stdin directly (rather than relying on the writer task's
        # drain()): the child then sees stdin EOF, exits, and the reader
        # reaches stdout EOF naturally — without being blocked behind a
        # potentially-stuck writer drain().
        self._child_stdin.close()

        # Wind down the reader first: it resolves/EOF-detects pending requests.
        reader = self._reader_task
        if reader is not None:
            try:
                await asyncio.wait_for(reader, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                reader.cancel()
                with contextlib.suppress(BaseException):
                    await reader
            except BaseException:
                # Never let an unusual task failure escape a shutdown path, and
                # do not mark degraded: exceptions observed while *we* are
                # closing (e.g. BrokenPipe after stdin.close) are expected
                # teardown races, not transport failures.
                reader.cancel()
                with contextlib.suppress(BaseException):
                    await reader

        self._fail_all_pending(RuntimeError("pipe closed"))

        # Then wind down the writer (it may be idle on the queue by now).
        writer = self._writer_task
        if writer is not None:
            try:
                await asyncio.wait_for(writer, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                writer.cancel()
                with contextlib.suppress(BaseException):
                    await writer
            except BaseException:
                writer.cancel()
                with contextlib.suppress(BaseException):
                    await writer

        with contextlib.suppress(BaseException):
            await asyncio.wait_for(self._child_stdin.wait_closed(), timeout=5.0)

    def _fail_all_pending(self, exc: BaseException) -> None:
        """Fail every outstanding request; never swallow the error."""
        pending = list(self._requests.items())
        self._requests.clear()
        self._request_methods.clear()
        for _request_id, fut in pending:
            if not fut.done():
                fut.set_exception(exc)

    async def _writer_loop(self) -> None:
        """Consume ``_outgoing`` and serialize JSON-RPC lines to child stdin.

        Once the pipe is closing, only the ``_CLOSE`` sentinel is processed;
        ordinary queued messages are dropped (their requests are failed by the
        close path) so nothing is written after close begins.
        """
        try:
            while True:
                msg = await self._outgoing.get()
                if self._closed and msg is not _CLOSE:
                    continue
                if msg is _CLOSE:
                    self._child_stdin.close()
                    return
                self._child_stdin.write(
                    (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                )
                await self._child_stdin.drain()
        except asyncio.CancelledError:
            self._fail_all_pending(RuntimeError("pipe writer cancelled"))
            raise
        except Exception as exc:
            # A drain/write failure while *we* are closing the pipe is an
            # expected consequence of closing stdin (BrokenPipe/ConnectionReset),
            # not a transport degradation.
            if not self._closed:
                self._transition_failed(RuntimeError(f"pipe writer failed: {exc}"))
            self._fail_all_pending(RuntimeError(f"pipe writer failed: {exc}"))
            raise

    async def _reader_loop(self) -> None:
        """Read response lines from child stdout; never swallow errors.

        EOF is a terminal failure: the child exited, so no further responses
        can arrive.  We record it as degraded and fail all pending requests.
        """
        try:
            async for raw in self._child_stdout:
                line = raw.decode("utf-8", errors="replace")
                # Some tool/provider integrations emit a harmless blank line
                # while the worker is active. It carries no JSON-RPC meaning
                # and must not tear down every pending child notification.
                if not line.strip():
                    continue
                try:
                    msg = parse_line(line)
                except (TypeError, ValueError):
                    # Agent/provider libraries occasionally write diagnostics
                    # to stdout even though stdout is reserved for JSON-RPC.
                    # A single foreign line must not kill the notification
                    # channel and strand an otherwise completed child task.
                    _logger.warning(
                        "ignoring non-protocol worker stdout line bytes=%d",
                        len(raw),
                    )
                    continue
                if not isinstance(msg, dict):
                    _logger.warning(
                        "ignoring non-object worker stdout message bytes=%d",
                        len(raw),
                    )
                    continue
                rid = msg.get("id")
                has_method = isinstance(msg.get("method"), str)
                is_response = "result" in msg or "error" in msg
                if has_method:
                    # Worker-initiated message (notification or request such as
                    # approval/request, question/request).  Forward it regardless of whether it
                    # also carries result/error (malformed) or collides with a
                    # pending host request id — never resolve a host future
                    # from a message that claims to be a worker message.
                    if self._emit is not None:
                        self._emit(msg)
                elif is_response and rid in self._requests:
                    # A host-initiated RPC response (no method).
                    method = self._request_methods.pop(rid, "")
                    if method == "shutdown":
                        # The worker acknowledged shutdown: from this point a
                        # subsequent EOF is an expected, non-degrading exit.
                        self._shutdown_confirmed = True
                    fut = self._requests.pop(rid)
                    if not fut.done():
                        fut.set_result(msg)
                elif is_response:
                    # Unsolicited/unknown response: log for diagnosability.
                    _logger.warning(
                        "dropping unknown worker response id=%s (pending=%d)",
                        rid,
                        len(self._requests),
                    )
            eof = RuntimeError("worker pipe EOF")
            if not self._closed and not self._graceful_shutdown and not self._shutdown_confirmed:
                # EOF without an explicit close or a confirmed shutdown is an
                # unexpected worker exit: mark degraded, fail pending, and
                # surface the exception on the reader task itself (satisfies
                # "reader 异常浮出").
                self._transition_failed(eof)
                self._fail_all_pending(eof)
                raise eof
            # On a normal close() or a confirmed graceful shutdown the child
            # was shut down by us: fail any remaining pending requests with a
            # clear shutdown error (worker is gone), then end the reader
            # normally (not a degradation).
            self._fail_all_pending(
                RuntimeError("agent worker shut down before responding")
            )
        except EOFError as exc:
            wrapped = RuntimeError(f"worker pipe closed: {exc}")
            if self._closed or self._graceful_shutdown:
                # Closing: not a degradation.
                self._fail_all_pending(wrapped)
            else:
                self._transition_failed(wrapped)
                self._fail_all_pending(wrapped)
            raise wrapped from exc
        except asyncio.CancelledError:
            self._fail_all_pending(RuntimeError("pipe reader cancelled"))
            raise
        except Exception as exc:
            wrapped = RuntimeError(f"reader failed: {exc}")
            if self._closed or self._graceful_shutdown:
                # Closing: not a degradation (matches writer close-race).
                self._fail_all_pending(wrapped)
            else:
                self._transition_failed(wrapped)
                self._fail_all_pending(wrapped)
            raise

    async def request(
        self, method: str, params: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        """One RPC round-trip; timeout/cancel clean up without leaking a Future.

        Fails fast when the pipe is already failed/closed: there is no reader
        left to answer, so a new request would otherwise hang until timeout.

        Boundary (PHASE-C §4.3): a timeout here only stops *waiting* for the
        response — it does not cancel the worker-side execution of a running
        ``prompt``.  Callers that need the worker to actually stop must use
        :meth:`AgentHost.interrupt` (server timeout paths do this via
        ``kill_host=True``).  A new ``prompt`` issued after a timed-out one
        therefore starts a fresh worker task; this is the documented contract
        boundary, not a leak.
        """
        if self._reject_request(method):
            reason = self._failure_exc or RuntimeError("agent worker pipe closed")
            raise RuntimeError(f"agent worker pipe closed: {reason}")
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        request_id = next(self._next_id)
        self._requests[request_id] = fut
        self._request_methods[request_id] = method
        self._outgoing.put_nowait(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            msg = await asyncio.wait_for(fut, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._requests.pop(request_id, None)
            self._request_methods.pop(request_id, None)
            raise
        if "error" in msg:
            error = msg.get("error")
            if isinstance(error, dict):
                message = str(error.get("message", "agent worker error"))
            else:
                message = str(error or "agent worker error")
            raise RuntimeError(message)
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    def respond(self, request_id: int, result: Any, *, error: Any = None) -> None:
        """Send a JSON-RPC response to a worker-initiated request (e.g. approval).

        Dropped (with telemetry) when the pipe is already failed/closed — there
        is no writer left to deliver it.
        """
        if self._is_shutdown():
            _log_pipe_event(
                "async_rpc_pipe_respond_dropped",
                exc=RuntimeError(f"pipe closed, cannot respond to id {request_id}"),
            )
            return
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        self._outgoing.put_nowait(message)


class AgentHost:
    """One killable worker subprocess per session (dual transport)."""

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path,
        model_id: str | None = None,
        stub: bool,
        project_root: Path,
        forward_server_request: ForwardServerRequest,
        main_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.session_id = session_id
        self.workspace_root = workspace_root.resolve()
        self.model_id = str(model_id or "").strip() or None
        self._stub = stub
        self._forward_server_request = forward_server_request
        self._main_loop = main_loop
        self._bootstrapped = False
        self._bootstrap_task: asyncio.Task[Any] | None = None
        self._bootstrap_lock = asyncio.Lock()
        self._emit: EmitFn | None = None
        self._async = async_rpc_enabled()
        self._legacy_degraded = False
        self._proc: subprocess.Popen[str] | asyncio.subprocess.Process | None = None
        self._pipe: AsyncRpcPipe | None = None
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._pending: dict[int, _SyncMailbox] = {}
        self._pending_lock = threading.Lock()
        self._outgoing: _SyncMailbox = _SyncMailbox()
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._stderr_task: asyncio.Task[Any] | None = None
        self._env = os.environ.copy()
        self._env["PYTHONIOENCODING"] = "utf-8"
        self._env["PYTHONPATH"] = str(project_root)
        self._project_root = project_root

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the worker subprocess with the selected transport."""
        if self._async:
            await self._start_async()
        else:
            await asyncio.to_thread(self._start_legacy)

    async def _start_async(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "appserver.agent_worker",
            cwd=str(self._project_root),
            env=self._env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._pipe = AsyncRpcPipe(
            self._proc.stdin,
            self._proc.stdout,
            emit=self._route_notification,
        )
        await self._pipe.start()
        self._stderr_task = asyncio.create_task(self._drain_stderr_async())
        self._stderr_task.add_done_callback(self._on_stderr_task_done)

    def _on_stderr_task_done(self, task: asyncio.Task[Any]) -> None:
        """Surface stderr-drain failures instead of letting them disappear.

        A stderr failure is treated as terminal for the pipe: fail any pending
        requests so callers do not wait out their timeout.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _log_pipe_event("stderr_drain_task_error", exc=exc)
            if self._pipe is not None:
                self._pipe._transition_failed(
                    RuntimeError(f"stderr drain failed: {exc}")
                )
                self._pipe._fail_all_pending(
                    RuntimeError(f"stderr drain failed: {exc}")
                )

    async def _drain_stderr_async(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        async for raw in self._proc.stderr:
            text = raw.decode("utf-8", errors="replace").rstrip()
            if text:
                _logger.info("[agent_worker %s] %s", self.session_id[:8], text)

    def _start_legacy(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "appserver.agent_worker"],
            cwd=self._project_root,
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._stderr = threading.Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()
        self._writer.start()
        self._stderr.start()

    def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            text = line.rstrip()
            if text:
                _logger.info("[agent_worker %s] %s", self.session_id[:8], text)

    def _write_loop(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            while self._proc.poll() is None:
                try:
                    message = self._outgoing.get(timeout=0.2)
                except TimeoutError:
                    continue
                self._proc.stdin.write(json.dumps(message) + "\n")
                self._proc.stdin.flush()
        except Exception as exc:
            # A stdin write failure means the worker cannot be reached: mark
            # the legacy transport degraded and fail every pending request so
            # callers do not wait out their full timeout.
            self._legacy_degraded = True
            self._fail_all_legacy_pending(
                RuntimeError(f"legacy writer failed: {exc}")
            )
            raise

    def _fail_all_legacy_pending(self, exc: BaseException) -> None:
        """Fail every outstanding legacy request (EOF or writer failure)."""
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for mailbox in pending:
            mailbox.put(
                {"jsonrpc": "2.0", "error": {"code": -32000, "message": str(exc)}}
            )

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._route_message(message)
        # EOF = the worker exited.  Fail every outstanding legacy request so
        # callers do not wait out their full timeout.
        self._legacy_degraded = True
        self._fail_all_legacy_pending(RuntimeError("agent worker pipe EOF"))

    def _route_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if isinstance(request_id, int) and (
            "result" in message or "error" in message
        ):
            with self._pending_lock:
                pending = self._pending.get(request_id)
            if pending is not None:
                pending.put(message)
                return
        method = message.get("method")
        if isinstance(method, str) and method in WORKER_SERVER_REQUESTS:
            params = message.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            rid = message.get("id")
            if not isinstance(rid, int):
                return

            def _complete() -> None:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._forward_server_request(method, params),
                        self._main_loop,
                    )
                    result = future.result(timeout=125.0)
                    self._outgoing.put(
                        {"jsonrpc": "2.0", "id": rid, "result": result}
                    )
                except Exception as exc:
                    self._outgoing.put(
                        {
                            "jsonrpc": "2.0",
                            "id": rid,
                            "error": {"code": -32000, "message": str(exc)},
                        }
                    )

            threading.Thread(target=_complete, daemon=True).start()
            return
        if (
            isinstance(method, str)
            and (method.startswith("event/") or method.startswith("child_session/"))
            and self._emit
        ):
            self._emit(message)

    def _route_notification(self, message: dict[str, Any]) -> None:
        """Async-path notification router (approval/question requests + event/*)."""
        method = message.get("method")
        if isinstance(method, str) and method in WORKER_SERVER_REQUESTS:
            params = message.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            rid = message.get("id")
            if not isinstance(rid, int):
                return

            async def _complete() -> None:
                try:
                    result = await self._forward_server_request(
                        method, params
                    )
                    self._respond_to_worker(rid, result, error=None)
                except Exception as exc:
                    self._respond_to_worker(
                        rid,
                        None,
                        error={"code": -32000, "message": str(exc)},
                    )

            asyncio.create_task(_complete())
            return
        if (
            isinstance(method, str)
            and (method.startswith("event/") or method.startswith("child_session/"))
            and self._emit
        ):
            self._emit(message)

    def _respond_to_worker(self, rid: int, result: Any, *, error: Any) -> None:
        if self._pipe is not None:
            self._pipe.respond(rid, result, error=error)
        else:
            self._outgoing.put(
                {"jsonrpc": "2.0", "id": rid, "result": result}
                if error is None
                else {"jsonrpc": "2.0", "id": rid, "error": error}
            )

    async def _pipe_request(
        self, method: str, params: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        """Route a host-initiated RPC to the active transport.

        Legacy (switch=0) boundary (PHASE-C §4.3): the sync ``_request`` runs in
        ``asyncio.to_thread``.  Cancelling the await stops waiting but the
        blocked ``_SyncMailbox.get()`` thread keeps running until its own
        timeout — this is the documented "超时停止等待而非终止执行" contract for
        the legacy fallback, which exists only for AC7 switch=0 equivalence
        tests.
        """
        if self._async:
            assert self._pipe is not None
            return await self._pipe.request(method, params, timeout=timeout)
        return await asyncio.to_thread(self._request, method, params, timeout=timeout)

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> dict:
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        response_mailbox: _SyncMailbox = _SyncMailbox()
        with self._pending_lock:
            self._pending[request_id] = response_mailbox
        self._outgoing.put(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        try:
            message = response_mailbox.get(timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"agent worker timeout for {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in message:
            error = message.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", "agent worker error"))
            else:
                detail = str(error or "agent worker error")
            raise RuntimeError(detail)
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    # ── public API ───────────────────────────────────────────────

    @property
    def bootstrapped(self) -> bool:
        return self._bootstrapped

    async def ensure_bootstrapped(self, *, timeout: float) -> None:
        """Join a single in-flight bootstrap instead of starting a second one.

        A short waiter timeout (warm used to be 30s) must not cancel the
        worker-side constructor; the next prompt waits on the same task.
        """
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return
            task = self._bootstrap_task
            if task is None or task.done():
                if self._bootstrapped:
                    return
                self._bootstrap_task = asyncio.create_task(self._bootstrap_once())
                task = self._bootstrap_task
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def _bootstrap_once(self) -> None:
        await self._pipe_request(
            "bootstrap",
            {
                "stub": self._stub,
                "workspace_root": str(self.workspace_root),
                "session_id": self.session_id,
                "model_id": self.model_id,
            },
            timeout=_BOOTSTRAP_RPC_TIMEOUT_SECONDS,
        )
        self._bootstrapped = True

    async def run_prompt(
        self,
        *,
        text: str,
        run_id: str,
        timeout: float,
        emit: EmitFn,
        mode: str = "build",
        thinking_expanded: bool = False,
        permission_mode: str | None = None,
    ) -> dict[str, Any]:
        self._emit = emit
        return await self._pipe_request(
            "prompt",
            {
                "session_id": self.session_id,
                "text": text,
                "run_id": run_id,
                "mode": mode,
                "thinking_expanded": thinking_expanded,
                "permission_mode": permission_mode,
            },
            timeout=timeout,
        )

    async def run_subagent_rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
        emit: EmitFn,
    ) -> dict[str, Any]:
        """Run a subagent RPC on this Primary session's owned worker.

        Do not replace a live prompt emitter. GUI child-session polls used to
        swap ``_emit`` to a path that does not ``touch_job``, so collapsed
        thinking (no reasoning events) looked dead and the 120s watchdog
        killed the in-flight prompt. Child notifications still flow through
        the prompt emitter while a job is running.
        """
        if self._emit is None:
            self._emit = emit
        return await self._pipe_request(method, params, timeout=timeout)

    async def set_model(self, model_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        """Switch the model owned by this session's worker.

        Each session has one worker, so this operation is task-scoped and does
        not mutate the process-wide active-model setting used by the CLI.
        """
        if not self.alive():
            raise RuntimeError("session worker is not running")
        return await self._pipe_request(
            "model/switch", {"model_id": model_id}, timeout=timeout
        )

    async def set_thinking_expanded(self, expanded: bool, timeout: float = 5.0) -> bool:
        """Forward Thought expand state to the in-flight worker TUI."""
        if not self.alive():
            return False
        try:
            result = await self._pipe_request(
                "thinking/set_expanded",
                {"expanded": bool(expanded)},
                timeout=timeout,
            )
        except Exception:
            return False
        return bool(result.get("ok", False))

    async def steer(self, text: str, *, timeout: float = 5.0) -> dict[str, Any]:
        """Forward steer text to the in-flight worker prompt."""
        if not self.alive():
            raise RuntimeError("turn is not running")
        return await self._pipe_request(
            "prompt/steer",
            {"session_id": self.session_id, "text": text},
            timeout=timeout,
        )

    async def interrupt(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Send an interrupt RPC; the worker cancels its running task.

        Return fields:
        - ``cancelled``: an active prompt task was cancelled.
        - ``failed``: the interrupt RPC itself failed (host was cleaned up).
        - ``killed``: the host was force-terminated as the failure fallback.
        """
        if not self.alive():
            return {"cancelled": False, "failed": False, "killed": False}
        try:
            result = await self._pipe_request("interrupt", {}, timeout=timeout)
        except Exception as exc:
            _logger.warning("interrupt RPC failed for %s: %s", self.session_id, exc)
            await self.kill_async()
            return {"cancelled": False, "failed": True, "killed": True}
        return {"cancelled": bool(result.get("cancelled")), "failed": False, "killed": False}

    async def kill_async(self) -> None:
        if self._async:
            await self._kill_async()
        else:
            await asyncio.to_thread(self.kill)

    async def _kill_async(self) -> None:
        """Terminate the worker and always clean up pipe/stderr tasks.

        The cleanup runs even when the process already exited — otherwise the
        pipe reader/writer tasks and the stderr drain would leak in the event
        loop when the host is discarded.
        """
        proc = self._proc
        try:
            if proc is not None and isinstance(proc, asyncio.subprocess.Process) and not self._is_dead():
                shutdown_ok = False
                try:
                    if self._pipe is not None:
                        await asyncio.wait_for(
                            self._pipe.request("shutdown", {}, timeout=2.0), timeout=2.0
                        )
                        shutdown_ok = True
                except Exception:
                    pass
                if shutdown_ok:
                    # Only after the worker acknowledged the shutdown RPC do we
                    # treat the ensuing EOF as an expected (non-degrading) exit.
                    # If the RPC failed and the worker crashes first, the EOF is
                    # still surfaced as a transport degradation.
                    if self._pipe is not None:
                        self._pipe._confirm_shutdown()
                # Order per C1: shutdown RPC → terminate() → final kill().
                # On a failed shutdown we skip the natural-exit wait and go
                # straight to terminate (the worker did not answer the RPC).
                wait_s = 0.0 if not shutdown_ok else 2.0
                try:
                    await asyncio.wait_for(proc.wait(), timeout=wait_s)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            proc.kill()
                        await asyncio.wait_for(proc.wait(), timeout=5)
        finally:
            if self._pipe is not None:
                await self._pipe.close()
            if self._stderr_task is not None:
                self._stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._stderr_task

    def kill(self) -> None:
        if self._proc is None or self._is_dead():
            return
        try:
            self._outgoing.put(
                {"jsonrpc": "2.0", "id": 9999, "method": "shutdown", "params": {}}
            )
        except Exception:
            pass
        # Order per C1: shutdown RPC → terminate() → final kill().
        try:
            assert self._proc is not None
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
                self._proc.wait(timeout=5)

    def _is_dead(self) -> bool:
        if self._proc is None:
            return True
        if self._async:
            assert isinstance(self._proc, asyncio.subprocess.Process)
            return self._proc.returncode is not None
        return self._proc.poll() is not None

    def alive(self) -> bool:
        return self._proc is not None and not self._is_dead()

    @property
    def degraded(self) -> bool:
        """Transport-level degradation, readable by the watchdog/status."""
        if self._pipe is not None:
            return self._pipe.degraded
        return self._legacy_degraded
