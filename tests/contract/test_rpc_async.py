"""C1 contract tests: AsyncRpcPipe process-boundary async transport.

Covers (PHASE-C-ASYNC-SINGLE-AGENT-CORE.md C1):
  - request timeout / error / cancel paths (no Future leak)
  - reader exception surfaces (not swallowed) + pipe.degraded observable
  - interrupt truly cancels worker run_task (appserver-level integration)
  - legacy sync fallback (RXYCODE_ASYNC_RPC=0) regression assertions
  - stdio smoke for switch=0 and switch=1
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

import pytest

from appserver.agent_host import AsyncRpcPipe, AgentHost
from protocol.version import PROTOCOL_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── mock streams for AsyncRpcPipe error-path unit tests ──────────

class _PipeEOF:
    pass


class _QueueReader:
    """Fake StreamReader: async-iterates queued lines; can raise on demand."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[bytes | BaseException | _PipeEOF] = asyncio.Queue()

    def push(self, line: bytes) -> None:
        self._q.put_nowait(line)

    def push_exc(self, exc: BaseException) -> None:
        self._q.put_nowait(exc)

    def finish(self) -> None:
        self._q.put_nowait(_PipeEOF())

    def __aiter__(self) -> "_QueueReader":
        return self

    async def __anext__(self) -> bytes:
        item = await self._q.get()
        if isinstance(item, _PipeEOF):
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeWriter:
    """Fake StreamWriter; drain() can be made to fail."""

    def __init__(self, *, drain_exc: BaseException | None = None) -> None:
        self.written = bytearray()
        self._drain_exc = drain_exc
        self.closed = False

    def write(self, data: bytes) -> None:
        if self._drain_exc is None:
            self.written += data

    async def drain(self) -> None:
        if self._drain_exc is not None:
            raise self._drain_exc

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


# ── helpers ──────────────────────────────────────────────────────

def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env["RXYCODE_APPSERVER_STUB"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def test_worker_stdio_limit_covers_large_write_payloads():
    """T01 final/write JSON-RPC lines exceed asyncio's default 64 KiB reader."""
    import inspect

    from appserver.agent_host import WORKER_STDIO_LIMIT_BYTES, AgentHost

    assert WORKER_STDIO_LIMIT_BYTES >= 1024 * 1024
    source = inspect.getsource(AgentHost._start_async)
    assert "limit=WORKER_STDIO_LIMIT_BYTES" in source


async def _spawn_worker() -> tuple[asyncio.subprocess.Process, AsyncRpcPipe]:
    from appserver.agent_host import WORKER_STDIO_LIMIT_BYTES

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "appserver.agent_worker",
        cwd=str(PROJECT_ROOT),
        env=_worker_env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=WORKER_STDIO_LIMIT_BYTES,
    )
    pipe = AsyncRpcPipe(proc.stdin, proc.stdout)
    await pipe.start()
    return proc, pipe


async def _shutdown(
    proc: asyncio.subprocess.Process, pipe: AsyncRpcPipe
) -> None:
    await pipe.close()
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5.0)


def _bootstrap_params(session_id: str = "t1") -> dict:
    return {
        "stub": True,
        "workspace_root": str(PROJECT_ROOT),
        "session_id": session_id,
    }


# ── AsyncRpcPipe: happy path against a real worker subprocess ────

@pytest.mark.asyncio
async def test_rpc_round_trip_bootstrap_prompt():
    proc, pipe = await _spawn_worker()
    try:
        result = await pipe.request("bootstrap", _bootstrap_params(), timeout=15.0)
        assert result["ok"] is True

        prompt = await pipe.request(
            "prompt",
            {"session_id": "t1", "text": "hello", "run_id": "r1", "mode": "build"},
            timeout=15.0,
        )
        assert prompt["status"] == "succeeded"
        assert prompt["text"] == "stub:hello"
    finally:
        await _shutdown(proc, pipe)


@pytest.mark.asyncio
async def test_rpc_request_timeout_no_future_leak():
    proc, pipe = await _spawn_worker()
    try:
        await pipe.request("bootstrap", _bootstrap_params(), timeout=15.0)

        with pytest.raises(asyncio.TimeoutError):
            await pipe.request(
                "prompt",
                {"session_id": "t1", "text": "slow:x", "run_id": "r2"},
                timeout=0.1,
            )
        assert not pipe._requests
        assert not pipe._request_methods

        follow_up = await pipe.request(
            "prompt",
            {"session_id": "t1", "text": "hi", "run_id": "r3"},
            timeout=15.0,
        )
        assert follow_up["status"] == "succeeded"
    finally:
        await _shutdown(proc, pipe)


@pytest.mark.asyncio
async def test_rpc_request_error_raises_runtime_error():
    proc, pipe = await _spawn_worker()
    try:
        with pytest.raises(RuntimeError, match="unknown method"):
            await pipe.request("no_such_method", {}, timeout=5.0)
        assert not pipe._requests
        assert not pipe._request_methods
    finally:
        await _shutdown(proc, pipe)


@pytest.mark.asyncio
async def test_rpc_request_cancel_no_future_leak():
    proc, pipe = await _spawn_worker()
    try:
        await pipe.request("bootstrap", _bootstrap_params(), timeout=15.0)

        task = asyncio.create_task(
            pipe.request(
                "prompt",
                {"session_id": "t1", "text": "slow:x", "run_id": "r4"},
                timeout=30.0,
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not pipe._requests
        assert not pipe._request_methods

        follow_up = await pipe.request(
            "prompt",
            {"session_id": "t1", "text": "hi", "run_id": "r5"},
            timeout=15.0,
        )
        assert follow_up["status"] == "succeeded"
    finally:
        await _shutdown(proc, pipe)


# ── AsyncRpcPipe: error paths (mock streams) ─────────────────────

@pytest.mark.asyncio
async def test_reader_exception_surfaces_and_sets_degraded():
    reader = _QueueReader()
    writer = _FakeWriter()
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()
    try:
        task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        reader.push_exc(RuntimeError("reader boom"))

        with pytest.raises(RuntimeError, match="reader boom"):
            await task
        await asyncio.sleep(0.05)
        assert pipe.degraded is True
        # The reader task itself must have completed with the original error
        # (not swallowed); the supervision callback consumed it.
        assert pipe._reader_task is not None
        assert pipe._reader_task.done()
        assert pipe.failure_exc is not None
    finally:
        reader.finish()
        await pipe.close()


@pytest.mark.asyncio
async def test_reader_ignores_blank_stdout_lines_without_losing_protocol_response():
    reader = _QueueReader()
    writer = _FakeWriter()
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()
    try:
        task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        import json as _json
        request_id = _json.loads(bytes(writer.written).decode("utf-8").strip())["id"]
        reader.push(b"\n")
        reader.push(_json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}).encode() + b"\n")
        assert await task == {"ok": True}
        assert pipe.degraded is False
    finally:
        reader.finish()
        await pipe.close()


@pytest.mark.asyncio
async def test_reader_ignores_non_protocol_stdout_without_losing_protocol_response():
    reader = _QueueReader()
    writer = _FakeWriter()
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()
    try:
        task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        import json as _json
        request_id = _json.loads(bytes(writer.written).decode("utf-8").strip())["id"]
        reader.push(b"provider diagnostic that is not json\n")
        reader.push(b"42\n")
        reader.push(_json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}).encode() + b"\n")
        assert await task == {"ok": True}
        assert pipe.degraded is False
    finally:
        reader.finish()
        await pipe.close()


@pytest.mark.asyncio
async def test_writer_error_fails_pending_and_sets_degraded():
    reader = _QueueReader()
    writer = _FakeWriter(drain_exc=OSError("pipe broken"))
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()
    try:
        task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        with pytest.raises(RuntimeError, match="pipe writer failed"):
            await task
        assert pipe.degraded is True
    finally:
        reader.finish()
        await pipe.close()


@pytest.mark.asyncio
async def test_worker_request_id_collision_is_not_misrouted():
    """A worker approval/request whose id collides with a pending host request
    must be forwarded to emit (it carries ``method``), not resolve the host
    request (which requires a ``result``/``error`` response)."""
    emitted: list[dict] = []
    reader = _QueueReader()
    writer = _FakeWriter()
    pipe = AsyncRpcPipe(writer, reader, emit=lambda m: emitted.append(m))
    await pipe.start()
    try:
        task = asyncio.create_task(pipe.request("prompt", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        # Read the host request id from what the writer emitted.
        line = bytes(writer.written).decode("utf-8").strip()
        import json as _json

        host_id = _json.loads(line)["id"]
        # Worker sends an approval/request with the SAME id.
        reader.push(
            _json.dumps(
                {"jsonrpc": "2.0", "id": host_id, "method": "approval/request",
                 "params": {"request_id": "r1"}}
            ).encode()
        )
        await asyncio.sleep(0.05)
        assert any(m.get("method") == "approval/request" for m in emitted)
        # The host prompt request is still pending (not mis-resolved).
        assert host_id in pipe._requests
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        reader.finish()
        await pipe.close()


@pytest.mark.asyncio
async def test_request_after_close_fails_fast():
    """A closed pipe must reject new requests instead of hanging to timeout."""
    reader = _QueueReader()
    pipe = AsyncRpcPipe(_FakeWriter(), reader)
    await pipe.start()
    reader.finish()
    await pipe.close()
    with pytest.raises(RuntimeError, match="pipe closed"):
        await pipe.request("bootstrap", {}, timeout=5.0)


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """start() must not spawn duplicate reader/writer tasks."""
    reader = _QueueReader()
    pipe = AsyncRpcPipe(_FakeWriter(), reader)
    await pipe.start()
    first_reader = pipe._reader_task
    await pipe.start()
    assert pipe._reader_task is first_reader
    assert pipe._writer_task is not None
    reader.finish()
    await pipe.close()


@pytest.mark.asyncio
async def test_close_while_writer_draining_does_not_degrade():
    """Closing stdin while the writer is mid-drain is expected, not degraded."""
    reader = _QueueReader()

    class _BlockingDrainWriter(_FakeWriter):
        async def drain(self) -> None:
            await asyncio.sleep(3600.0)   # simulate a stuck drain

    writer = _BlockingDrainWriter()
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()

    # Put a request so the writer loop is writing and then draining.
    task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
    await asyncio.sleep(0.1)

    # Real close() sets _closed first, so the ensuing reader EOF / drain
    # cancellation is expected (non-degrading).
    close_task = asyncio.create_task(pipe.close())
    await asyncio.sleep(0.1)
    reader.finish()
    await close_task
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
    assert pipe._closed is True
    assert pipe.degraded is False


@pytest.mark.asyncio
async def test_close_cancelled_then_close_again_waits_same_task():
    """A cancelled close() must not start a second teardown; a later close()
    awaits the same in-flight _close_task."""
    reader = _QueueReader()

    class _BlockingDrainWriter(_FakeWriter):
        async def drain(self) -> None:
            await asyncio.sleep(3600.0)

    pipe = AsyncRpcPipe(_BlockingDrainWriter(), reader)
    await pipe.start()

    task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
    await asyncio.sleep(0.1)

    first = asyncio.create_task(pipe.close())
    await asyncio.sleep(0.1)
    first.cancel()
    with contextlib.suppress(BaseException):
        await first

    # The teardown task must still be running (not cleared by the cancel).
    assert pipe._close_task is not None

    reader.finish()
    await pipe.close()          # must await the same task, not spawn another
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
    assert pipe._closed is True


@pytest.mark.asyncio
async def test_close_with_writer_broken_pipe_does_not_degrade():
    """A BrokenPipe on the writer while closing is expected, not degraded."""
    reader = _QueueReader()
    broken = asyncio.Event()

    class _BrokenPipeWriter(_FakeWriter):
        async def drain(self) -> None:
            if broken.is_set():
                raise ConnectionResetError("broken pipe")

    writer = _BrokenPipeWriter()
    pipe = AsyncRpcPipe(writer, reader)
    await pipe.start()

    task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
    await asyncio.sleep(0.1)

    # Start close (sets _closed first).  Then let the writer's next drain raise
    # BrokenPipe — this must not be recorded as a degradation.
    close_task = asyncio.create_task(pipe.close())
    await asyncio.sleep(0.1)
    broken.set()
    reader.finish()
    await close_task
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
    assert pipe._closed is True
    assert pipe.degraded is False


@pytest.mark.asyncio
async def test_real_reader_failure_survives_later_close():
    """A real reader failure must stay degraded even if close() runs after."""
    reader = _QueueReader()
    pipe = AsyncRpcPipe(_FakeWriter(), reader)
    await pipe.start()

    task = asyncio.create_task(pipe.request("bootstrap", {}, timeout=5.0))
    await asyncio.sleep(0.05)
    reader.push_exc(RuntimeError("reader boom"))
    with pytest.raises(RuntimeError, match="reader boom"):
        await task

    await asyncio.sleep(0.05)
    assert pipe.degraded is True
    assert pipe.failure_exc is not None

    # A later close() must not clear the already-recorded degradation.
    await pipe.close()
    assert pipe._closed is True
    assert pipe.degraded is True


@pytest.mark.asyncio
async def test_interrupt_before_prompt_task_runs_still_answers():
    """An interrupt arriving before the prompt task first runs must still get
    a prompt response (no hanging parent request)."""
    from unittest.mock import AsyncMock

    from appserver.agent_worker import AgentWorker

    worker = AgentWorker()
    worker._agent = object()

    def fake_bind(session_id, tui):
        return (None, None)

    def fake_reset(tokens):
        return None

    class _BlockingSession:
        def __init__(self, **kwargs):
            pass

        async def prompt(self, agent, text, *, mode, run_id):
            await asyncio.sleep(3600.0)
            return "never"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("appserver.agent_worker.bind_prompt_context", fake_bind)
    monkeypatch.setattr("appserver.agent_worker.reset_prompt_context", fake_reset)
    monkeypatch.setattr("appserver.agent_worker.Session", _BlockingSession)
    messages: list[dict] = []
    monkeypatch.setattr(
        "appserver.agent_worker.write_message",
        AsyncMock(side_effect=lambda msg: messages.append(msg)),
    )

    run_task = asyncio.create_task(
        worker._dispatch_safe(
            {"jsonrpc": "2.0", "id": 2, "method": "prompt",
             "params": {"text": "hi", "session_id": "s", "run_id": "r1"}}
        )
    )
    worker._run_task = run_task
    # Simulate run()'s _clear_run done-callback firing on early cancellation.
    worker._answered_request_ids = set()

    def _clear_run(_t):
        if worker._run_task is _t:
            worker._run_task = None
        if _t.cancelled() and 2 not in worker._answered_request_ids:
            # Mirrors production run(): the answered marker is set inside the
            # write helper, not before it.
            asyncio.create_task(worker._write_interrupted_response(2))

    run_task.add_done_callback(_clear_run)
    # Interrupt immediately — the prompt dispatch task may not have started yet.
    await worker._handle_interrupt(3)

    try:
        await asyncio.wait_for(run_task, timeout=5.0)
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.1)  # let the fresh interrupted-response task run
    # The prompt must have been answered (id=2) even on early cancellation,
    # and only after the response write succeeded.
    assert any(
        m.get("id") == 2 and m.get("result", {}).get("status") == "cancelled"
        for m in messages
    )
    assert 2 in worker._answered_request_ids
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_reader_exception_during_close_not_degraded():
    """A reader exception observed while closing must not mark degraded."""
    reader = _QueueReader()
    pipe = AsyncRpcPipe(_FakeWriter(), reader)
    await pipe.start()

    # Start close() (sets _closed first), then make the reader raise while the
    # pipe is closing.
    close_task = asyncio.create_task(pipe.close())
    await asyncio.sleep(0.1)
    reader.push_exc(ConnectionResetError("reset during close"))
    await close_task
    assert pipe._closed is True
    assert pipe.degraded is False


@pytest.mark.asyncio
async def test_graceful_shutdown_allows_shutdown_rpc_but_blocks_others():
    """_confirm_shutdown must not block the shutdown RPC, and a normal
    close after it must still run full teardown (no degraded, tasks reaped)."""
    reader = _QueueReader()
    writer = _FakeWriter()
    pipe = AsyncRpcPipe(writer, reader, emit=lambda m: None)
    await pipe.start()

    pipe._confirm_shutdown()
    assert pipe._graceful_shutdown is True
    assert pipe._closed is False
    # Request() is still usable for the shutdown RPC (graceful != closed).
    assert pipe._is_shutdown() is False

    # Non-shutdown RPCs must be rejected during graceful shutdown.
    with pytest.raises(RuntimeError, match="pipe closed"):
        await pipe.request("prompt", {}, timeout=5.0)
    assert not pipe._requests
    assert not pipe._request_methods

    task = asyncio.create_task(pipe.request("shutdown", {}, timeout=5.0))
    await asyncio.sleep(0.05)
    line = bytes(writer.written).decode("utf-8").strip()
    import json as _json

    assert _json.loads(line)["method"] == "shutdown"
    reader.push(
        _json.dumps({"jsonrpc": "2.0", "id": _json.loads(line)["id"],
                     "result": {"ok": True}}).encode()
    )
    assert (await asyncio.wait_for(task, timeout=2.0)).get("ok") is True

    # A full close must still run teardown even after graceful shutdown.
    reader.finish()
    await pipe.close()
    assert pipe._closed is True
    assert pipe.degraded is False


def test_host_exposes_pipe_degraded_flag():
    """/status-readable degraded state is reachable through the AgentHost."""
    assert hasattr(AgentHost, "degraded")
    assert AgentHost.degraded is not None  # property descriptor exists


# ── Legacy sync fallback (RXYCODE_ASYNC_RPC=0) regression ────────

@pytest.mark.asyncio
async def test_legacy_fallback_bootstrap_and_prompt(monkeypatch):
    monkeypatch.setenv("RXYCODE_ASYNC_RPC", "0")
    host = AgentHost(
        session_id="legacy1",
        workspace_root=PROJECT_ROOT,
        stub=True,
        project_root=PROJECT_ROOT,
        forward_server_request=lambda method, params: {"ok": True},
        main_loop=asyncio.get_running_loop(),
    )
    await host.start()
    try:
        await host.ensure_bootstrapped(timeout=15.0)
        result = await host.run_prompt(
            text="hello", run_id="r1", timeout=15.0, emit=lambda message: None
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:hello"
    finally:
        await host.kill_async()


# ── New async path smoke at the host level (RXYCODE_ASYNC_RPC=1) ──

@pytest.mark.asyncio
async def test_async_host_bootstrap_and_prompt(monkeypatch):
    monkeypatch.setenv("RXYCODE_ASYNC_RPC", "1")
    host = AgentHost(
        session_id="async1",
        workspace_root=PROJECT_ROOT,
        stub=True,
        project_root=PROJECT_ROOT,
        forward_server_request=lambda method, params: {"ok": True},
        main_loop=asyncio.get_running_loop(),
    )
    await host.start()
    try:
        await host.ensure_bootstrapped(timeout=15.0)
        result = await host.run_prompt(
            text="hello", run_id="r1", timeout=15.0, emit=lambda message: None
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:hello"
    finally:
        await host.kill_async()


# ── Interrupt truly cancels the running prompt (not a timeout) ───

@pytest.mark.asyncio
async def test_interrupt_cancels_hung_prompt(monkeypatch):
    """A hung prompt must be cancelled by session/interrupt, not left to time out."""
    monkeypatch.setenv("RXYCODE_ASYNC_RPC", "1")
    host = AgentHost(
        session_id="int1",
        workspace_root=PROJECT_ROOT,
        stub=True,
        project_root=PROJECT_ROOT,
        forward_server_request=lambda method, params: {"ok": True},
        main_loop=asyncio.get_running_loop(),
    )
    await host.start()
    try:
        await host.ensure_bootstrapped(timeout=15.0)

        prompt_task = asyncio.create_task(
            host.run_prompt(
                text="hang:forever", run_id="int-r1", timeout=30.0,
                emit=lambda message: None,
            )
        )
        await asyncio.sleep(0.3)

        interrupt = await host.interrupt(timeout=5.0)
        assert interrupt.get("cancelled") is True

        # The prompt must resolve as cancelled (not wait the full 30s timeout).
        result = await asyncio.wait_for(prompt_task, timeout=5.0)
        assert result.get("status") == "cancelled"
    finally:
        await host.kill_async()


@pytest.mark.asyncio
async def test_interrupt_with_no_active_prompt(monkeypatch):
    monkeypatch.setenv("RXYCODE_ASYNC_RPC", "1")
    host = AgentHost(
        session_id="int2",
        workspace_root=PROJECT_ROOT,
        stub=True,
        project_root=PROJECT_ROOT,
        forward_server_request=lambda method, params: {"ok": True},
        main_loop=asyncio.get_running_loop(),
    )
    await host.start()
    try:
        await host.ensure_bootstrapped(timeout=15.0)
        interrupt = await host.interrupt(timeout=5.0)
        assert interrupt.get("cancelled") in (True, False)
    finally:
        await host.kill_async()


# ── SessionSlots acquire-cancel leak test (C4 moved here) ─────────

class _SessionSlots:
    """Session-level concurrency slots (C1 contract copy of C4 §4.4)."""

    def __init__(self, max_concurrent: int) -> None:
        self._global = asyncio.Semaphore(max_concurrent)
        self._per_session: dict[str, asyncio.Semaphore] = {}
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, session_id: str) -> None:
        await self._global.acquire()
        session_acquired = False
        try:
            async with self._lock:
                sem = self._per_session.get(session_id)
                if sem is None:
                    sem = asyncio.Semaphore(1)
                    self._per_session[session_id] = sem
            await sem.acquire()
            session_acquired = True
            async with self._lock:
                self._active[session_id] = self._active.get(session_id, 0) + 1
        except asyncio.CancelledError:
            if session_acquired:
                sem.release()
            self._global.release()
            raise

    def release(self, session_id: str) -> None:
        sem = self._per_session.get(session_id)
        if sem is not None:
            sem.release()
        n = self._active.get(session_id, 0)
        if n > 0:
            self._active[session_id] = n - 1
        self._global.release()


@pytest.mark.asyncio
async def test_session_slots_acquire_cancel_does_not_leak():
    """Cancelling an acquire waiting for a slot must not leak global/session counts."""
    slots = _SessionSlots(max_concurrent=2)
    slots._active = {"blocker": 1}
    slots._per_session["blocker"] = asyncio.Semaphore(0)
    await slots._global.acquire()   # hold both global slots
    await slots._global.acquire()

    waiter = asyncio.create_task(slots.acquire("other"))
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    slots._global.release()          # release the test's two holds
    slots._global.release()
    # Both global slots must still be available — a leaked acquire would block
    # the second one below.
    await asyncio.wait_for(slots._global.acquire(), timeout=1.0)
    await asyncio.wait_for(slots._global.acquire(), timeout=1.0)
    slots._global.release()
    slots._global.release()
    assert slots._active.get("other", 0) == 0


# ── Real appserver subprocess: stdio smoke + server-level interrupt ─

import json  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
# NOTE: this queue is only used by the *test-process* stdio client below.  The
# production fallback (appserver/agent_host.py) is queue-free (C1 判据 1:
# rg "queue.Queue" appserver/agent_host.py 为空).
import queue as _queue_mod  # noqa: E402


class _AppserverClient:
    """Minimal stdio JSON-RPC client for the appserver subprocess."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._pending: dict[int, _queue_mod.Queue[dict]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: _queue_mod.Queue[dict] = _queue_mod.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # Drain the appserver's stderr so its pipe never fills and deadlocks
        # the child process on stderr writes.
        self._stderr_drain = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_drain.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            text = line.rstrip()
            if text:
                sys.stderr.write(f"[appserver-contract-stderr] {text}\n")

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            message = json.loads(line)
            rid = message.get("id")
            routed = False
            if isinstance(rid, int):
                with self._pending_lock:
                    pending = self._pending.get(rid)
                if pending is not None:
                    pending.put(message)
                    routed = True
            if not routed:
                self._notifications.put(message)

    def read_event(self, timeout: float = 1.0) -> dict | None:
        """Read the next notification (does not consume pending responses)."""
        try:
            return self._notifications.get(timeout=timeout)
        except _queue_mod.Empty:
            return None

    def send(self, method: str, params: dict) -> int:
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            + "\n"
        )
        self.proc.stdin.flush()
        return request_id

    def send_expect(self, method: str, params: dict) -> tuple[int, _queue_mod.Queue[dict]]:
        """Register the response queue BEFORE writing stdin, so a fast response
        cannot be dropped by the reader thread before the caller subscribes."""
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        response: _queue_mod.Queue[dict] = _queue_mod.Queue()
        with self._pending_lock:
            self._pending[request_id] = response
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            + "\n"
        )
        self.proc.stdin.flush()
        return request_id, response

    def request(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        request_id, response = self.send_expect(method, params)
        try:
            message = response.get(timeout=timeout)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in message:
            raise AssertionError(message["error"])
        return message.get("result") or {}


@pytest.mark.parametrize("switch", ["0", "1"])
def test_appserver_stdio_smoke(switch: str):
    """End-to-end initialize/session-new/prompt over real appserver stdio."""
    env = os.environ.copy()
    env["RXYCODE_APPSERVER_STUB"] = "1"
    env["RXYCODE_ASYNC_RPC"] = switch
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        client = _AppserverClient(proc)
        init = client.request(
            "initialize",
            {"client_name": "pytest", "client_version": "0.0.0", "protocol_version": PROTOCOL_VERSION},
        )
        assert init["protocol_version"] == PROTOCOL_VERSION
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        result = client.request(
            "session/prompt",
            {"session_id": session["session_id"], "text": "hello"},
            timeout=30.0,
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:hello"
    finally:
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": {}})
                        + "\n"
                    )
                    proc.stdin.flush()
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)


@pytest.mark.parametrize("switch", ["0", "1"])
def test_appserver_interrupt_cancels_hung_prompt(switch: str):
    """session/interrupt must cancel a hung prompt, not wait for timeout."""
    env = os.environ.copy()
    env["RXYCODE_APPSERVER_STUB"] = "1"
    env["RXYCODE_ASYNC_RPC"] = switch
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        client = _AppserverClient(proc)
        client.request(
            "initialize",
            {"client_name": "pytest", "client_version": "0.0.0", "protocol_version": "1.0.0"},
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        prompt_id, response = client.send_expect(
            "session/prompt",
            {"session_id": session["session_id"], "text": "hang:forever", "timeout_seconds": 60},
        )
        # Wait until the worker has actually started the prompt (cold worker
        # bootstrap can exceed a fixed short sleep), then interrupt it.  The
        # "running" job-state event is emitted before the prompt executes.
        deadline = time.monotonic() + 15.0
        saw_running = False
        while time.monotonic() < deadline:
            message = client.read_event(timeout=0.5)
            if message is None:
                continue
            if message.get("method") == "event/job_status":
                params = message.get("params") or {}
                if params.get("state") == "running":
                    saw_running = True
                    break
        assert saw_running, "prompt never reached the running state"
        # Cold Windows workers finish bootstrap after job_status=running.
        # Poll interrupt until the worker has a prompt task (or agent).
        interrupt = {"cancelled": False}
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            interrupt = client.request(
                "session/interrupt",
                {"session_id": session["session_id"]},
                timeout=10.0,
            )
            if interrupt.get("cancelled") is True:
                break
            time.sleep(0.2)
        assert interrupt.get("cancelled") is True, interrupt

        try:
            message = response.get(timeout=15.0)
        finally:
            with client._pending_lock:
                client._pending.pop(prompt_id, None)
        # The hung prompt resolves as a failure promptly (not after 60s timeout).
        assert message.get("result", {}).get("status") == "cancelled"
    finally:
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": {}})
                        + "\n"
                    )
                    proc.stdin.flush()
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)


def test_host_degraded_propagates_from_pipe():
    """host.degraded reflects the AsyncRpcPipe failure state end-to-end."""
    host = AgentHost(
        session_id="deg1",
        workspace_root=PROJECT_ROOT,
        stub=True,
        project_root=PROJECT_ROOT,
        forward_server_request=lambda method, params: {"ok": True},
        main_loop=asyncio.new_event_loop(),
    )
    host._async = True
    assert host.degraded is False
    pipe = AsyncRpcPipe(
        _FakeWriter(), _QueueReader(), emit=None
    )
    pipe._transition_failed(RuntimeError("boom"))
    assert pipe.degraded is True
    host._pipe = pipe
    assert host.degraded is True


# ── Worker unit-level interrupt: assert run_task.cancelled() directly ─

@pytest.mark.asyncio
async def test_worker_interrupt_cancels_run_task(monkeypatch):
    """Interrupt must cancel the worker's run_task (not merely reply)."""
    from unittest.mock import AsyncMock

    from appserver.agent_worker import AgentWorker

    worker = AgentWorker()
    worker._agent = object()

    entered = asyncio.Event()

    class _SlowAgent:
        def __init__(self):
            self._entered = entered

        async def run(self, text: str, mode: str = "build") -> str:
            self._entered.set()
            await asyncio.sleep(3600.0)
            return "never"

    slow = _SlowAgent()
    worker._agent = slow

    def fake_bind(session_id, tui):
        return (None, None)

    def fake_reset(tokens):
        return None

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def prompt(self, agent, text, *, mode, run_id):
            return await slow.run(text, mode=mode)

    monkeypatch.setattr("appserver.agent_worker.bind_prompt_context", fake_bind)
    monkeypatch.setattr("appserver.agent_worker.reset_prompt_context", fake_reset)
    monkeypatch.setattr("appserver.agent_worker.Session", FakeSession)
    messages: list[dict] = []
    monkeypatch.setattr(
        "appserver.agent_worker.write_message",
        AsyncMock(side_effect=lambda msg: messages.append(msg)),
    )

    run_task = asyncio.create_task(
        worker._handle_prompt(
            {"text": "hi", "session_id": "s", "run_id": "r1"}, 2
        )
    )
    worker._run_task = run_task  # normally set by run(); wired here for the unit
    await asyncio.wait_for(entered.wait(), timeout=2.0)

    await worker._handle_interrupt(3)

    try:
        await asyncio.wait_for(run_task, timeout=5.0)
    except asyncio.CancelledError:
        pass  # cancelled is the expected outcome
    assert run_task.cancelled() is True
    assert any(
        m.get("id") == 3 and m.get("result", {}).get("cancelled") is True
        for m in messages
    )
    assert any(m.get("id") == 2 for m in messages)  # prompt replied (failed)
