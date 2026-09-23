"""C3 contract tests: StreamCoalescer batching/ordering/flush semantics.

Covers 搂4.2 semantics: ticker flush, byte-threshold flush, cross-kind total
order (seq), adjacent same-kind merge, stop() trailing flush, exception/
cancellation requeue (at-least-once for unsent, UNDECIDED for in-flight),
degraded flag, idempotent start, and the AC7 dual-path switch contract
(RXYCODE_STREAM_COALESCE=1 coalesces; =0 keeps the per-token direct write).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import pytest

from appserver.jsonrpc import StreamCoalescer, stream_coalesce_enabled


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RXYCODE_STREAM_COALESCE", raising=False)


# 鈹€鈹€ batching / ordering 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@pytest.mark.asyncio
async def test_adjacent_same_kind_merged_into_one_sink_call():
    calls: list[tuple[str, str]] = []
    sink = _sync_sink(calls)
    c = StreamCoalescer(sink)
    await c.push("token", "Hel")
    await c.push("token", "lo ")
    await c.push("token", "world")
    await c.flush()
    assert calls == [("token", "Hello world")], calls
    await c.stop()


@pytest.mark.asyncio
async def test_cross_kind_total_order_preserved():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.push("token", "T1")
    await c.push("reasoning", "R1")
    await c.push("progress", "P1")
    await c.push("token", "T2")
    await c.flush()
    assert [kind for kind, _ in calls] == ["token", "reasoning", "progress", "token"]
    await c.stop()


@pytest.mark.asyncio
async def test_non_adjacent_same_kind_not_merged():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.push("token", "A")
    await c.push("progress", "B")
    await c.push("token", "C")
    await c.flush()
    assert calls == [("token", "A"), ("progress", "B"), ("token", "C")], calls
    await c.stop()


# 鈹€鈹€ flush triggers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@pytest.mark.asyncio
async def test_byte_threshold_triggers_immediate_flush():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.push("token", "a" * 1024)  # exactly at threshold -> flush
    assert calls, "byte threshold must trigger an immediate flush"
    await c.stop()


@pytest.mark.asyncio
async def test_ticker_flushes_after_interval():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.start()
    try:
        await c.push("token", "tick")
        await asyncio.sleep(0.15)  # > FLUSH_INTERVAL_S (0.07)
        assert calls, "ticker must flush buffered text after the interval"
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_stop_flushes_trailing_buffer():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.push("token", "trailing")
    await c.stop()
    assert calls == [("token", "trailing")], "stop() must flush the tail"


# 鈹€鈹€ failure semantics 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@pytest.mark.asyncio
async def test_exception_requeues_unsent_not_inflight():
    """Sink raising on the 2nd merged segment: 1st stays written (at-most-
    once), 3rd is requeued (at-least-once), the failing segment is UNDECIDED
    (neither re-sent nor dropped silently)."""
    calls: list[tuple[str, str]] = []
    attempts: list[int] = []

    async def failing_sink(kind: str, text: str) -> None:
        calls.append((kind, text))
        attempts.append(len(calls))
        if len(calls) == 2:
            raise RuntimeError("sink boom")

    c = StreamCoalescer(failing_sink)
    await c.push("token", "seg1")
    await c.push("reasoning", "seg2")
    await c.push("progress", "seg3")
    with pytest.raises(RuntimeError, match="sink boom"):
        await c.flush()
    # seg1 written, seg2 failed in-flight, seg3 requeued.
    assert calls == [("token", "seg1"), ("reasoning", "seg2")], calls
    await c.flush()  # requeued seg3 goes out; seg2 is NOT retried
    assert calls == [
        ("token", "seg1"),
        ("reasoning", "seg2"),
        ("progress", "seg3"),
    ], calls
    await c.stop()


@pytest.mark.asyncio
async def test_cancel_requeues_unsent():
    calls: list[tuple[str, str]] = []

    async def slow_sink(kind: str, text: str) -> None:
        calls.append((kind, text))
        await asyncio.sleep(10)

    c = StreamCoalescer(slow_sink)
    await c.push("token", "first")
    await c.push("reasoning", "second")
    task = asyncio.create_task(c.flush())
    await asyncio.sleep(0.05)  # sink is mid-write on the first segment
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [("token", "first")], calls  # in-flight segment wrote
    await c.flush()  # requeued "second" is retried
    assert ("reasoning", "second") in calls, calls
    await c.stop()


# 鈹€鈹€ supervision / lifecycle 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@pytest.mark.asyncio
async def test_ticker_error_sets_degraded():
    async def boom_sink(kind: str, text: str) -> None:
        raise RuntimeError("ticker boom")

    c = StreamCoalescer(boom_sink)
    await c.start()
    await c.push("token", "x")
    await asyncio.sleep(0.15)  # ticker fires, sink raises -> degraded
    assert c.degraded is True, "ticker failure must set degraded"
    await c.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_and_restarts():
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.start()
    await c.start()  # second start stops the old ticker, starts fresh
    await c.push("token", "ok")
    await asyncio.sleep(0.15)
    assert calls, "restarted coalescer must keep flushing"
    await c.stop()
    await c.stop()  # double stop is safe


@pytest.mark.asyncio
async def test_restart_clears_degraded():
    """Recovery semantics: after a ticker failure sets degraded, a fresh
    start() must clear the flag so /status can observe recovery."""
    async def boom_sink(kind: str, text: str) -> None:
        raise RuntimeError("boom")

    c = StreamCoalescer(boom_sink)
    await c.start()
    await c.push("token", "x")
    await asyncio.sleep(0.15)
    assert c.degraded is True
    # Recover with a working sink.
    calls: list[tuple[str, str]] = []
    c._sink = _sync_sink(calls)
    await c.start()
    assert c.degraded is False, "restart must clear degraded"
    await c.push("token", "y")
    await asyncio.sleep(0.15)
    assert calls, "recovered coalescer must keep flushing"
    await c.stop()


@pytest.mark.asyncio
async def test_requeue_preserves_total_order_with_concurrent_push():
    """Segments pushed while a flush is failing must NOT overtake the
    requeued (older) content: the second flush must emit in original seq
    order 鈥?A, B(requeued), C(pushed during flush), never A, C, B."""
    emitted: list[tuple[str, str]] = []
    b_entered = asyncio.Event()
    release_b = asyncio.Event()

    async def failing_sink(kind: str, text: str) -> None:
        emitted.append((kind, text))
        if kind == "reasoning":  # segment B: block until C is pushed
            b_entered.set()
            await release_b.wait()
            raise RuntimeError("sink boom on b")

    c = StreamCoalescer(failing_sink)
    await c.push("token", "A")
    await c.push("reasoning", "B")
    flush_task = asyncio.create_task(c.flush())
    # Wait until the flush is INSIDE segment B (mid-write), then push C.
    await asyncio.wait_for(b_entered.wait(), timeout=2.0)
    await c.push("progress", "C")
    release_b.set()
    with pytest.raises(RuntimeError, match="sink boom on b"):
        await flush_task
    # Second flush: A already written (at-most-once); B requeued with its
    # ORIGINAL seq (older than C) so order must be B then C.
    await c.flush()
    kinds = [k for k, _ in emitted]
    assert kinds == ["token", "reasoning", "progress"], kinds
    await c.stop()


# 鈹€鈹€ AC7 dual-path switch 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def test_stream_coalesce_switch_default_on():
    assert stream_coalesce_enabled() is True


def test_stream_coalesce_switch_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_STREAM_COALESCE", "0")
    assert stream_coalesce_enabled() is False


def test_stream_coalesce_switch_invalid_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RXYCODE_STREAM_COALESCE", "banana")
    assert stream_coalesce_enabled() is True


# 鈹€鈹€ ProtocolTui integration (worker path) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@pytest.mark.asyncio
async def test_tui_stream_token_coalesces_not_per_token(monkeypatch: pytest.MonkeyPatch):
    """With the coalescer bound, stream_token pushes into it instead of
    emitting one MessageDelta per token; a flush emits ONE merged delta."""
    from appserver.tui import ProtocolTui

    written: list[dict[str, Any]] = []
    c = StreamCoalescer(
        _sync_sink(written)
    )
    tui = ProtocolTui("s1", lambda model: _record(written, "emit", str(model)))
    tui.set_coalescer(c)
    await c.start()
    try:
        tui.stream_token("Hel")
        tui.stream_token("lo")
        await tui.drain_push_tasks()  # order scheduled pushes before the flush
        await c.flush()
        token_writes = [w for w in written if w[0] == "token"]
        assert token_writes == [("token", "Hello")], token_writes
        assert not any(
            isinstance(w, tuple) and w[0] == "emit" for w in written
        ), "coalesced path must not emit per-token MessageDelta"
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_tui_without_coalescer_keeps_direct_emit():
    """Switch-off path: no coalescer bound -> stream_token emits directly."""
    from appserver.tui import ProtocolTui

    emitted: list[Any] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.stream_token("direct")
    assert len(emitted) == 1, "unbound tui must keep the direct emit path"


@pytest.mark.asyncio
async def test_push_failure_observable_even_if_task_finished_early():
    """A push task that failed BEFORE drain is still observable via
    push_failures (collected by the done callback, not only at drain time).
    A byte-threshold push (>= 1024 chars) triggers an in-push flush whose
    sink failure fails the push task itself."""
    from appserver.tui import ProtocolTui

    async def boom_sink(kind: str, text: str) -> None:
        raise RuntimeError("push boom")

    c = StreamCoalescer(boom_sink)
    tui = ProtocolTui("s1", lambda m: None)
    tui.set_coalescer(c)
    await c.start()
    try:
        tui.stream_token("a" * 1024)  # threshold push -> flush -> sink boom
        # Let the push task complete on its own (drain is a no-op afterwards).
        await asyncio.sleep(0.2)
        assert tui.push_failures, "failed push must be recorded via done callback"
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_stop_tolerates_failing_sink_and_cancelled_sink():
    """stop() must not raise on a failing sink (degraded) or a sink that
    never returns (cancelled mid-write) 鈥?teardown is fault-tolerant."""
    async def failing_sink(kind: str, text: str) -> None:
        raise RuntimeError("sink always fails")

    c = StreamCoalescer(failing_sink)
    await c.start()
    await c.push("token", "x")
    await asyncio.sleep(0.15)
    assert c.degraded is True
    await c.stop()  # must not raise despite the failing sink

    async def hanging_sink(kind: str, text: str) -> None:
        await asyncio.sleep(10)

    c2 = StreamCoalescer(hanging_sink)
    await c2.start()
    await c2.push("token", "y")
    await asyncio.sleep(0.05)
    await c2.stop()  # ticker cancelled mid-write; stop must not raise


@pytest.mark.asyncio
async def test_start_recovers_when_old_teardown_flush_fails():
    """Recovery: start() after a degraded ticker must create a fresh ticker
    even when stopping the old one (final flush) raises."""
    failing = True

    async def sink(kind: str, text: str) -> None:
        if failing:
            raise RuntimeError("flush boom")

    c = StreamCoalescer(sink)
    await c.start()
    await c.push("token", "x")
    await asyncio.sleep(0.15)
    assert c.degraded is True
    failing = False  # recovery: sink works again
    await c.start()  # must not raise even though old teardown flush fails
    assert c.degraded is False
    calls: list[tuple[str, str]] = []
    c._sink = _sync_sink(calls)
    await c.push("token", "y")
    await asyncio.sleep(0.15)
    assert calls, "recovered ticker must flush"
    await c.stop()


@pytest.mark.asyncio
async def test_worker_switch_0_does_not_build_coalescer(monkeypatch: pytest.MonkeyPatch):
    """AC7 0 妗? with RXYCODE_STREAM_COALESCE=0 the REAL worker prompt path
    must not construct a coalescer; every stream_token goes through the
    legacy direct-emit 鈫?_schedule_write 鈫?write_message path (one write per
    token, no drain/stop behaviour change)."""
    import appserver.agent_worker as aw

    built: list[bool] = []
    writes: list[str] = []

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            # Agent V2 emits tokens through the bound TUI.
            bound = aw.get_bound_tui()
            for _ in range(3):
                bound.stream_token("tok")
            return FakeResult()

    class FakeResult:
        status = "succeeded"
        answer = "a"
        thinking = "t"
        input_tokens = 1
        output_tokens = 1

    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: False)
    monkeypatch.setattr(aw, "StreamCoalescer", lambda sink: _coalescer_stub(built))
    monkeypatch.setattr(aw, "Session", FakeSession)

    async def fake_write(message):
        if "result" in message:
            writes.append("result")
        else:
            writes.append("notification")

    monkeypatch.setattr(aw, "write_message", fake_write)

    worker = aw.AgentWorker()
    worker._agent = object()
    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    assert not built, "switch 0 must never construct a coalescer"
    assert writes.count("notification") == 3, (
        f"switch 0 must keep one write per token, got {writes}"
    )
    assert writes[-1] == "result", f"result must be last, got {writes}"


class _coalescer_stub:
    """Records construction; never actually used (switch-off path)."""

    def __init__(self, built: list[bool]) -> None:
        built.append(True)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_batched_writes_reduce_transport_calls():
    """N tokens coalesce into far fewer stdout writes: the sink (which maps to
    write_message 鈫?one to_thread per call) must be invoked once per merged
    batch, not once per token."""
    import appserver.jsonrpc as jrpc
    from appserver.tui import ProtocolTui

    sink_calls = 0

    async def counting_sink(kind: str, text: str) -> None:
        nonlocal sink_calls
        sink_calls += 1

    c = StreamCoalescer(counting_sink)
    tui = ProtocolTui("s1", lambda m: None)
    tui.set_coalescer(c)
    await c.start()
    try:
        for _ in range(200):
            tui.stream_token("a")
        await tui.drain_push_tasks()
        await c.flush()
        assert sink_calls <= 1, (
            f"200 tokens must coalesce into a single write, got {sink_calls}"
        )
        assert jrpc.stream_coalesce_enabled() is True
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_stop_tolerates_residual_flush_failure():
    """stop() must not raise when the FINAL flush (residual buffer) hits a
    failing sink 鈥?the failure is surfaced via degraded/undecided_segments."""
    async def failing_sink(kind: str, text: str) -> None:
        raise RuntimeError("residual boom")

    c = StreamCoalescer(failing_sink)
    await c.start()
    await c.push("token", "tail")  # residual, never ticker-flushed
    await asyncio.sleep(0.01)
    await c.stop()  # final flush fails -> degraded, no raise
    assert c.degraded is True
    assert c.undecided_segments, "failed final segment must be recorded"


@pytest.mark.asyncio
async def test_stop_bounded_when_sink_hangs():
    """stop() must complete in bounded time even when the final flush's sink
    never returns (STOP_FLUSH_TIMEOUT_S)."""
    async def hanging_sink(kind: str, text: str) -> None:
        await asyncio.sleep(30)

    c = StreamCoalescer(hanging_sink)
    await c.start()
    await c.push("token", "tail")
    await asyncio.sleep(0.01)
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    assert c.degraded is True


@pytest.mark.asyncio
async def test_undecided_segment_recorded_on_sink_failure():
    """The segment being written when the sink raises is recorded as
    UNDECIDED (kind/text/exception) and is never retried."""
    calls: list[tuple[str, str]] = []

    async def failing_sink(kind: str, text: str) -> None:
        calls.append((kind, text))
        if kind == "reasoning":
            raise RuntimeError("mid boom")

    c = StreamCoalescer(failing_sink)
    await c.push("token", "A")
    await c.push("reasoning", "B")
    await c.push("progress", "C")
    with pytest.raises(RuntimeError, match="mid boom"):
        await c.flush()
    assert c.undecided_segments and c.undecided_segments[0][:2] == ("reasoning", "B")
    assert c.undecided_segments[0][2] is not None
    await c.flush()  # C retried; B NOT retried (UNDECIDED)
    assert calls == [("token", "A"), ("reasoning", "B"), ("progress", "C")]
    await c.stop()


@pytest.mark.asyncio
async def test_worker_success_wind_down_order(monkeypatch: pytest.MonkeyPatch):
    """Worker success path: drain -> stop (trailing flush) -> pending-write
    flush -> result; notifications written before the terminal result."""
    import appserver.agent_worker as aw
    from appserver.tui import ProtocolTui

    order: list[str] = []

    class FakeResult:
        status = "succeeded"
        answer = "the answer"
        thinking = "thinking"
        input_tokens = 1
        output_tokens = 2

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            return FakeResult()

    worker = aw.AgentWorker()
    worker._agent = object()

    async def fake_write(message):
        if "result" in message:
            order.append("result")
        elif message.get("method"):
            order.append("notification")

    import appserver.jsonrpc as jrpc

    monkeypatch.setattr(aw, "write_message", fake_write)
    monkeypatch.setattr(aw, "Session", FakeSession)
    # A coalescer sink that records its flush against the result order.

    class FakeCoalescer:
        def __init__(self, sink):
            self.sink = sink

        async def start(self):
            order.append("coalescer_start")

        async def stop(self):
            self.sink("token", "tail")  # sync FIFO sink
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", lambda sink: FakeCoalescer(sink))
    monkeypatch.setattr(jrpc, "stream_coalesce_enabled", lambda: True)

    worker._next_id = 1
    await worker._handle_prompt(
        {"text": "hi", "session_id": "s1", "run_id": "r1"}, request_id=7
    )
    assert order[0] == "coalescer_start"
    assert order[-1] == "result", f"result must be last, got {order}"
    assert "coalescer_stop" in order, "stop must flush the tail before result"
    assert order.index("coalescer_stop") < order.index("result")


@pytest.mark.asyncio
async def test_cross_kind_total_bytes_threshold():
    """The 1024-byte threshold counts the WHOLE pending batch (all kinds),
    not each kind separately: 600+600 bytes across kinds triggers a flush."""
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.push("token", "a" * 600)
    assert not calls, "600 bytes below threshold must not flush"
    await c.push("reasoning", "b" * 600)  # total 1200 >= 1024 -> flush
    assert calls, "cross-kind total bytes must trigger an immediate flush"
    await c.stop()


@pytest.mark.asyncio
async def test_cancel_records_undecided_segment():
    """The segment being written when the flush is cancelled is recorded in
    undecided_segments (observable, never silently dropped)."""
    calls: list[tuple[str, str]] = []

    async def slow_sink(kind: str, text: str) -> None:
        calls.append((kind, text))
        await asyncio.sleep(10)

    c = StreamCoalescer(slow_sink)
    await c.push("token", "first")
    await c.push("reasoning", "second")
    task = asyncio.create_task(c.flush())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.undecided_segments, "cancelled mid-write segment must be recorded"
    assert c.undecided_segments[0][:2] == ("token", "first")
    await c.stop()


@pytest.mark.asyncio
async def test_ticker_immediate_failure_then_stop_sets_degraded():
    """stop() right after a ticker failure must surface degraded even if the
    done callback has not run yet (no reliance on callback scheduling)."""
    async def boom_sink(kind: str, text: str) -> None:
        raise RuntimeError("instant boom")

    c = StreamCoalescer(boom_sink)
    await c.start()
    await c.push("token", "x")  # ticker will fail on its first flush
    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        if c._flush_task is not None and c._flush_task.done():
            break
        await asyncio.sleep(0.01)
    assert c._flush_task is not None and c._flush_task.done()
    await c.stop()  # must set degraded synchronously from the task state
    assert c.degraded is True


@pytest.mark.asyncio
async def test_worker_error_wind_down_orders_stream_before_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """Worker error path: stream trailing flush must precede the error
    response, and queued notifications must be flushed before it."""
    import appserver.agent_worker as aw

    order: list[str] = []

    class BoomSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, *a, **k):
            raise RuntimeError("prompt exploded")

    worker = aw.AgentWorker()
    worker._agent = object()

    async def fake_write(message):
        if "error" in message:
            order.append("error_response")
        elif "result" in message:
            order.append("result")

    monkeypatch.setattr(aw, "write_message", fake_write)
    monkeypatch.setattr(aw, "Session", BoomSession)

    class FakeCoalescer:
        """Mirrors production StreamCoalescer.stop() idempotency: a second
        stop (from the unified finally) is a no-op."""

        def __init__(self, sink):
            self.sink = sink
            self._stopped = False

        async def start(self):
            order.append("coalescer_start")

        async def stop(self):
            if self._stopped:
                return
            self._stopped = True
            self.sink("token", "tail")  # sync FIFO sink
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", lambda sink: FakeCoalescer(sink))
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)

    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    assert order[0] == "coalescer_start"
    assert order[-1] == "error_response", f"error must be last, got {order}"
    assert order.index("coalescer_stop") < order.index("error_response")


@pytest.mark.asyncio
async def test_worker_session_construction_failure_no_ticker_leak(
    monkeypatch: pytest.MonkeyPatch,
):
    """A Session construction failure must still tear the coalescer down
    (no background ticker leak)."""
    import appserver.agent_worker as aw

    order: list[str] = []

    class BoomSession:
        def __init__(self, *a, **k):
            raise RuntimeError("session construct boom")

    worker = aw.AgentWorker()
    worker._agent = object()

    async def fake_write(message):
        if "error" in message:
            order.append("error_response")
        else:
            order.append("write")

    monkeypatch.setattr(aw, "write_message", fake_write)
    monkeypatch.setattr(aw, "Session", BoomSession)

    class FakeCoalescer:
        """Mirrors production stop() idempotency (unified finally re-runs it)."""

        def __init__(self, sink):
            self.sink = sink
            self._stopped = False

        async def start(self):
            order.append("coalescer_start")

        async def stop(self):
            if self._stopped:
                return
            self._stopped = True
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", lambda sink: FakeCoalescer(sink))
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)

    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    assert "coalescer_start" in order
    assert "coalescer_stop" in order, "teardown must run on construction failure"
    assert order[-1] == "error_response", (
        f"terminal error must be last (ordered after notifications), got {order}"
    )


@pytest.mark.asyncio
async def test_worker_switch_1_real_coalescer_orders_stream_before_result(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC7 1 妗? the REAL worker path with a REAL StreamCoalescer merges token
    notifications into one write, and the terminal result arrives after the
    stream flush (drain 鈫?stop)."""
    import appserver.agent_worker as aw
    import appserver.jsonrpc as jrpc

    writes: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            bound = aw.get_bound_tui()
            for _ in range(5):
                bound.stream_token("tok")
            return FakeResult()

    class FakeResult:
        status = "succeeded"
        answer = "a"
        thinking = "t"
        input_tokens = 1
        output_tokens = 1

    monkeypatch.setattr(aw, "Session", FakeSession)
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)

    async def fake_write(message):
        if "result" in message:
            writes.append(("result", ""))
        else:
            # A stream notification: MessageDelta text (merged tokens).
            text = str(message.get("params", {}).get("text", ""))
            writes.append(("notification", text))

    monkeypatch.setattr(aw, "write_message", fake_write)

    worker = aw.AgentWorker()
    worker._agent = object()
    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    # 5 tokens merged into ONE notification write; result strictly last.
    assert writes[-1][0] == "result", f"result must be last, got {writes}"
    notif = [w for w in writes if w[0] == "notification"]
    assert len(notif) == 1, f"5 tokens must coalesce into one write, got {notif}"
    assert "".join(t for _, t in notif) == "toktoktoktoktok", notif


@pytest.mark.asyncio
async def test_multibyte_utf8_threshold():
    """The byte threshold counts UTF-8 BYTES: 512 Chinese chars (1536 bytes)
    must trigger a flush while 300 (900 bytes) must not."""
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    han = "\u6d4b"  # 测 — 3 bytes in UTF-8
    await c.push("token", han * 300)  # 900 bytes < 1024
    assert not calls, "900 bytes must stay buffered"
    await c.push("reasoning", han * 50)  # +150 bytes = 1050 >= 1024
    assert calls, "multibyte total must trigger the byte threshold"
    await c.stop()


@pytest.mark.asyncio
async def test_repeated_start_keeps_single_ticker():
    """start() re-entry replaces the old ticker: after two starts exactly one
    ticker task is running and the first one is finished."""
    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(_sync_sink(calls))
    await c.start()
    first = c._flush_task
    await c.start()
    second = c._flush_task
    assert first.done(), "old ticker must be finished after re-start"
    assert second is not None and not second.done()
    assert first is not second, "restart must create a fresh ticker task"
    await c.stop()
    assert second.done()


@pytest.mark.asyncio
async def test_push_during_successful_flush_not_lost():
    """Content pushed while a flush is running must NOT be lost: it lands in
    the next flush in order."""
    calls: list[tuple[str, str]] = []
    entered = asyncio.Event()

    async def slow_sink(kind: str, text: str) -> None:
        calls.append((kind, text))
        if kind == "token":
            entered.set()
            await asyncio.sleep(0.05)

    c = StreamCoalescer(slow_sink)
    await c.push("token", "A")
    flush_task = asyncio.create_task(c.flush())
    await entered.wait()
    await c.push("reasoning", "B")  # pushed while flush is mid-write
    await flush_task
    await c.flush()
    kinds = [k for k, _ in calls]
    assert kinds == ["token", "reasoning"], f"B must not be lost: {kinds}"
    await c.stop()


@pytest.mark.asyncio
async def test_two_consecutive_failed_flushes_with_concurrent_pushes():
    """Two consecutive failed flushes, each with a concurrent push, must keep
    total order and never duplicate already-written segments."""
    emitted: list[tuple[str, str]] = []
    gate = asyncio.Event()

    async def flaky_sink(kind: str, text: str) -> None:
        emitted.append((kind, text))
        if text in ("B", "D"):
            gate.set()
            await asyncio.sleep(0.02)
            raise RuntimeError(f"sink boom on {text}")

    c = StreamCoalescer(flaky_sink)
    await c.push("token", "A")
    await c.push("reasoning", "B")
    t1 = asyncio.create_task(c.flush())
    await gate.wait()
    await c.push("progress", "C")  # during first failure
    with pytest.raises(RuntimeError, match="sink boom on B"):
        await t1
    # Second flush: B requeued (before C), then D pushed during it.
    gate.clear()
    await c.push("reasoning", "D")  # different kind so it is NOT merged with C
    t2 = asyncio.create_task(c.flush())
    while not gate.is_set() and len(emitted) < 3:
        await asyncio.sleep(0.01)
    await c.push("progress", "E")  # during second failure
    with pytest.raises(RuntimeError, match="sink boom on D"):
        await t2
    await c.flush()
    kinds = [k for k, _ in emitted]
    assert kinds == [
        "token", "reasoning", "progress", "reasoning", "progress",
    ], kinds
    await c.stop()


@pytest.mark.asyncio
async def test_adjacent_same_kind_across_retry_not_duplicated():
    """A merged same-kind segment whose single write fails is UNDECIDED: it is
    recorded and never re-sent on the next flush (no duplicates)."""
    emitted: list[tuple[str, str]] = []

    async def failing_sink(kind: str, text: str) -> None:
        emitted.append((kind, text))
        if len(emitted) == 1:
            raise RuntimeError("first write fails")

    c = StreamCoalescer(failing_sink)
    await c.push("token", "x")
    await c.push("token", "y")  # adjacent same kind, merged into one segment
    with pytest.raises(RuntimeError):
        await c.flush()
    assert c.undecided_segments, "the failing merged segment must be UNDECIDED"
    await c.flush()  # nothing requeued (the segment was in-flight)
    assert emitted == [("token", "xy")], (
        "merged segment must not be duplicated on retry"
    )
    await c.stop()


@pytest.mark.asyncio
async def test_writer_cancel_does_not_break_queue_counts(monkeypatch: pytest.MonkeyPatch):
    """Cancelling the worker writer must not corrupt the queue's task_done
    accounting: join() keeps working and no ValueError surfaces."""
    import appserver.agent_worker as aw

    worker = aw.AgentWorker()
    async with _writer_scope(worker):
        worker._schedule_write({"jsonrpc": "2.0", "method": "x"})
        # Cancel the writer while a message is queued/being written.
        w = worker._write_task
        w.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await w
        # The queue accounting must still be consistent for a fresh writer.
        worker._ensure_writer()
        worker._schedule_write({"jsonrpc": "2.0", "method": "y"})
        await asyncio.wait_for(worker._write_queue.join(), timeout=2.0)


@pytest.mark.asyncio
async def test_concurrent_emit_and_terminal_response_keep_order(
    monkeypatch: pytest.MonkeyPatch,
):
    """_write_ordered's drain->submit window is atomic under the order lock:
    a concurrent emit injected AT the drain boundary (inside the locked
    window) still lands BEFORE the response."""
    import appserver.agent_worker as aw

    writes: list[str] = []

    async def fake_write(message):
        if "result" in message:
            writes.append("result")
        elif message.get("method"):
            writes.append("notification")

    monkeypatch.setattr(aw, "write_message", fake_write)
    worker = aw.AgentWorker()
    async with _writer_scope(worker):
        worker._schedule_write({"jsonrpc": "2.0", "method": "note1"})
        # Inject a concurrent emit INSIDE the locked drain->submit window.
        orig_flush = worker._flush_pending_writes

        async def inject_then_flush():
            await orig_flush()
            worker._schedule_write({"jsonrpc": "2.0", "method": "note2"})

        worker._flush_pending_writes = inject_then_flush
        await worker._write_ordered(
            {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        )
        await asyncio.wait_for(worker._write_queue.join(), timeout=2.0)
        assert writes[-1] == "result", f"result must be last, got {writes}"
        assert writes.count("notification") == 2, writes


@pytest.mark.asyncio
async def test_writer_shutdown_bounded_drain_then_cancel():
    """run() shutdown drains the queue with a bounded wait before cancelling
    the writer (no unbounded hang, queued notifications get a chance)."""
    import appserver.agent_worker as aw

    worker = aw.AgentWorker()
    async with _writer_scope(worker):
        worker._schedule_write({"jsonrpc": "2.0", "method": "note"})
        # Simulate the run() finally block's bounded drain.
        try:
            await asyncio.wait_for(worker._write_queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            w = worker._write_task
            if w is not None and not w.done():
                w.cancel()
        assert worker._write_queue.qsize() == 0


import contextlib as _ctx


@_ctx.asynccontextmanager
async def _writer_scope(worker):
    """Start the worker writer and tear it down afterwards."""
    worker._ensure_writer()
    try:
        yield
    finally:
        w = worker._write_task
        if w is not None and not w.done():
            w.cancel()
            with _ctx.suppress(asyncio.CancelledError):
                await w


@pytest.mark.asyncio
async def test_stop_hard_timeout_when_sink_swallows_cancellation():
    """stop() must return within the bound even when the sink swallows
    CancelledError (hard timeout: cancel the flush task and stop waiting)."""
    swallowed = asyncio.Event()

    async def stubborn_sink(kind: str, text: str) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            swallowed.set()
            await asyncio.sleep(30)  # swallow the cancellation

    c = StreamCoalescer(stubborn_sink)
    await c.start()
    await c.push("token", "tail")
    await asyncio.sleep(0.01)
    t0 = asyncio.get_running_loop().time()
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed <= StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 1, elapsed
    assert c.degraded is True
    await asyncio.sleep(0.1)  # let the best-effort cancel propagate to the sink
    assert swallowed.is_set(), "the sink must have been cancelled"


@pytest.mark.asyncio
async def test_stop_without_start_tolerates_sink_failure():
    """stop() on an un-started coalescer with a residual buffer and failing
    sink must be fault-tolerant (degraded set, no raise)."""
    async def failing_sink(kind: str, text: str) -> None:
        raise RuntimeError("boom")

    c = StreamCoalescer(failing_sink)
    await c.push("token", "tail")  # never started; residual buffered
    await c.stop()  # must not raise
    assert c.degraded is True


@pytest.mark.asyncio
async def test_external_ticker_cancel_sets_degraded_but_stop_cancel_does_not():
    """搂4.2 supervision: an EXTERNAL cancel of the ticker sets degraded; the
    controlled stop() cancellation must NOT set it."""
    calls: list[tuple[str, str]] = []

    async def ok_sink(kind: str, text: str) -> None:
        await asyncio.sleep(0)

    c = StreamCoalescer(_sync_sink(calls))
    await c.start()
    # External cancel (not via stop()): observable as degraded.
    c._flush_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await c._flush_task
    assert c.degraded is True, "external ticker cancel must set degraded"

    # Controlled stop() cancellation must NOT set degraded.
    c2 = StreamCoalescer(ok_sink)
    await c2.start()
    assert c2.degraded is False
    await c2.stop()
    assert c2.degraded is False, "controlled stop must not set degraded"


@pytest.mark.asyncio
async def test_stop_timeout_records_inflight_segment_undecided():
    """When the final flush hard-times-out (sink swallows cancellation), the
    in-flight segment must be recorded as UNDECIDED and a later start/flush
    must not duplicate it."""
    async def stubborn_sink(kind: str, text: str) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(30)  # swallow

    c = StreamCoalescer(stubborn_sink)
    await c.start()
    await c.push("token", "tail")
    await asyncio.sleep(0.01)
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    assert c.degraded is True
    assert c.undecided_segments, "in-flight segment must be UNDECIDED on timeout"
    assert c.undecided_segments[0][:2] == ("token", "tail")
    # Recovered instance: a fresh flush must not resend the UNDECIDED segment.
    await c.flush()
    assert len(c.undecided_segments) == 1, "UNDECIDED segment must not be re-sent"


@pytest.mark.asyncio
async def test_stream_token_before_tool_call_stays_ordered():
    """A tool notification emitted right after a stream token must land AFTER
    the token in the writer queue (synchronous ordering barrier)."""
    from appserver.jsonrpc import StreamCoalescer
    from appserver.tui import ProtocolTui

    queue: list[tuple[str, str]] = []

    def sync_sink(kind: str, text: str) -> None:
        queue.append((kind, text))

    c = StreamCoalescer(sync_sink)
    tui = ProtocolTui("s1", lambda model: queue.append(("plain", str(model))))
    tui.set_coalescer(c)
    tui.stream_token("A")  # buffered in the coalescer
    tui.write_tool_call("read", {"filePath": "x"})  # barrier flushes A first
    assert [q for q in queue if q[0] != "plain"][:1] == [("token", "A")], queue
    assert queue[0] == ("token", "A"), f"token must precede the tool call: {queue}"
    await c.stop()


@pytest.mark.asyncio
async def test_threshold_push_then_plain_emit_stays_ordered():
    """Even at the byte threshold (flush scheduled as a task), a plain emit
    that follows immediately must not overtake the buffered stream content:
    the barrier submits synchronously before the plain emit."""
    from appserver.jsonrpc import StreamCoalescer
    from appserver.tui import ProtocolTui

    queue: list[str] = []

    def sync_sink(kind: str, text: str) -> None:
        queue.append(f"stream:{kind}")

    c = StreamCoalescer(sync_sink)
    tui = ProtocolTui("s1", lambda model: queue.append("plain"))
    tui.set_coalescer(c)
    tui.stream_token("a" * 1024)  # threshold: flush task scheduled
    tui.write_tool_call("read", {"filePath": "x"})  # barrier flushes first
    assert queue[0] == "stream:token", f"stream must precede plain: {queue}"
    assert queue[1] == "plain", f"plain must follow the stream: {queue}"
    await c.stop()


def _sync_sink(calls: list[tuple[str, str]]) -> Callable[[str, str], None]:
    """Sync sink recording (kind, text) — used by the many batching tests."""
    def sink(kind: str, text: str) -> None:
        calls.append((kind, str(text)))

    return sink


@pytest.mark.asyncio
async def test_barrier_sink_failure_records_undecided_and_requeues():
    """flush_submit_sync failure semantics: the failing segment is recorded as
    UNDECIDED and the remaining segments are requeued (never silently lost)."""
    from appserver.jsonrpc import StreamCoalescer
    from appserver.tui import ProtocolTui

    attempts: list[str] = []

    def flaky_sink(kind: str, text: str) -> None:
        attempts.append(text)
        if len(attempts) == 1:
            raise RuntimeError("enqueue boom")

    c = StreamCoalescer(flaky_sink)
    tui = ProtocolTui("s1", lambda m: None)
    tui.set_coalescer(c)
    tui.stream_token("A")
    tui.stream_token("B")  # merged with A into one segment
    tui.write_progress("P")  # different kind: its own segment
    try:
        tui.write_tool_call("read", {"filePath": "x"})  # barrier flushes
    except RuntimeError:
        pass
    assert c.undecided_segments, "failing barrier segment must be UNDECIDED"
    await c.flush()  # requeued progress segment retried
    assert len(attempts) >= 2, attempts


@pytest.mark.asyncio
async def test_plain_emit_after_token_stays_ordered(monkeypatch: pytest.MonkeyPatch):
    """A plain (non-tool) notification emitted right after a stream token must
    land after the token — the barrier lives in the worker's emit callback."""
    import appserver.agent_worker as aw

    writes: list[str] = []

    async def fake_write(message):
        if "result" in message:
            writes.append("result")
        else:
            writes.append("plain")

    monkeypatch.setattr(aw, "write_message", fake_write)

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            bound = aw.get_bound_tui()
            bound.stream_token("tok")  # buffered stream content
            bound.write_info("note")  # plain notification via the emit callback
            return FakeResult()

    class FakeResult:
        status = "succeeded"
        answer = "a"
        thinking = "t"
        input_tokens = 1
        output_tokens = 1

    monkeypatch.setattr(aw, "Session", FakeSession)
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)

    worker = aw.AgentWorker()
    worker._agent = object()
    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    # token notification + plain note notification + result, strictly ordered.
    assert writes[-1] == "result", f"result must be last, got {writes}"
    assert writes.count("plain") == 2, writes


@pytest.mark.asyncio
async def test_start_recovers_after_hard_timeout_terminated():
    """start() after a hard-timeout teardown clears the terminated flag so the
    instance can flush again once the zombie flush task releases the lock
    (recovery semantics)."""
    async def stubborn_sink(kind: str, text: str) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(6)  # swallow the cancel, then finish

    c = StreamCoalescer(stubborn_sink)
    await c.start()
    await c.push("token", "tail")
    await asyncio.sleep(0.01)
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    assert c._terminated is True
    # Recover with a working sync sink and restart; the zombie releases the
    # lock within a few seconds, after which the new ticker can flush.
    calls: list[tuple[str, str]] = []
    c._sink = _sync_sink(calls)
    await c.start()
    assert c._terminated is False, "start() must clear the terminated flag"
    await c.push("token", "new")
    # The zombie flush task holds the lock for a few seconds; poll until the
    # recovered coalescer can actually flush (bounded by 15s).
    deadline = asyncio.get_running_loop().time() + 15.0
    while not calls and asyncio.get_running_loop().time() < deadline:
        await c.flush()
        await asyncio.sleep(0.5)
    assert calls, "recovered coalescer must flush again"
    await c.stop()


@pytest.mark.asyncio
async def test_barrier_skipped_while_async_flush_holds_lock():
    """The sync barrier must skip while an async flush holds the lock (data
    is never taken/cleared concurrently)."""
    from appserver.jsonrpc import StreamCoalescer

    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_sink(kind: str, text: str) -> None:
        entered.set()
        await release.wait()

    c = StreamCoalescer(slow_sink)
    await c.push("token", "A")
    flush_task = asyncio.create_task(c.flush())
    await entered.wait()  # async flush holds the lock, mid-sink
    # Barrier while the lock is held: must be a no-op, content preserved.
    c.flush_submit_sync()
    release.set()
    await flush_task
    # The buffered content was submitted by the async flush.
    assert not c.has_pending()
    await c.stop()


@pytest.mark.asyncio
async def test_stop_timeout_keeps_unsent_backlog_retryable():
    """When the final flush hard-times-out, segments AFTER the in-flight one
    must survive in _order (requeued backlog) and be retryable later — and
    the zombie flush task must NOT re-submit them (at-most-once)."""
    zombie_submissions: list[tuple[str, str]] = []

    async def stubborn_sink(kind: str, text: str) -> None:
        zombie_submissions.append((kind, text))
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(6)  # swallow, then finish

    c = StreamCoalescer(stubborn_sink)
    await c.start()
    await c.push("token", "first")
    await c.push("reasoning", "second")  # unsent backlog once first is inflight
    await asyncio.sleep(0.01)
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    # first = UNDECIDED (in-flight); second restored to _order (backlog).
    assert c.undecided_segments and c.undecided_segments[0][0] == "token"
    assert c.has_pending(), "unsent backlog must be restored for retry"
    # After the zombie releases the lock, a recovered flush delivers 'second'
    # exactly once: the zombie's epoch was aborted so it cannot re-submit.
    calls: list[tuple[str, str]] = []
    c._sink = _sync_sink(calls)
    await c.start()
    deadline = asyncio.get_running_loop().time() + 15.0
    while not calls and asyncio.get_running_loop().time() < deadline:
        await c.flush()
        await asyncio.sleep(0.5)
    assert ("reasoning", "second") in calls, calls
    # The UNDECIDED in-flight segment ('first') must NEVER be re-sent by the
    # recovered flush, and the zombie must not re-submit the backlog.
    assert not any(k == "token" for k, _ in calls), (
        f"UNDECIDED in-flight segment must not be re-sent: {calls}"
    )
    assert not any(k == "reasoning" for k, _ in zombie_submissions), (
        f"zombie flush must not re-submit the restored backlog: "
        f"{zombie_submissions}"
    )
    await c.stop()


@pytest.mark.asyncio
async def test_worker_result_sent_even_when_coalescer_degraded(
    monkeypatch: pytest.MonkeyPatch,
):
    """A degraded coalescer must not block the terminal result: the worker
    still sends success (failures are logged by _wind_down_stream)."""
    import appserver.agent_worker as aw

    writes: list[str] = []

    class BoomCoalescer:
        def __init__(self, sink):
            self.degraded = True

        async def start(self):
            raise RuntimeError("start boom")

        async def stop(self):
            pass

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            return FakeResult()

    class FakeResult:
        status = "succeeded"
        answer = "a"
        thinking = "t"
        input_tokens = 1
        output_tokens = 1

    async def fake_write(message):
        if "result" in message:
            writes.append("result")
        elif "error" in message:
            writes.append("error")

    monkeypatch.setattr(aw, "write_message", fake_write)
    monkeypatch.setattr(aw, "Session", FakeSession)
    monkeypatch.setattr(aw, "StreamCoalescer", BoomCoalescer)
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)

    worker = aw.AgentWorker()
    worker._agent = object()
    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    assert writes == ["error"], (
        f"terminal response must still be sent despite the degraded "
        f"coalescer, got {writes}"
    )


@pytest.mark.asyncio
async def test_worker_real_path_counts_thread_switches(monkeypatch: pytest.MonkeyPatch):
    """Core C3 criterion, transport-level: in the REAL worker path with the
    coalescer on, N tokens produce far fewer than N write_message calls
    (each = one to_thread switch in the real transport); with the switch off
    they stay one per token."""
    import appserver.agent_worker as aw

    real_write = aw.write_message
    write_calls = 0

    async def counting_write(message):
        nonlocal write_calls
        write_calls += 1
        await real_write(message)

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def prompt(self, agent, text, mode="build", run_id=None):
            bound = aw.get_bound_tui()
            for _ in range(100):
                bound.stream_token("t")
            return FakeResult()

    class FakeResult:
        status = "succeeded"
        answer = "a"
        thinking = "t"
        input_tokens = 1
        output_tokens = 1

    monkeypatch.setattr(aw, "Session", FakeSession)
    monkeypatch.setattr(aw, "write_message", counting_write)

    # Switch ON (default): 100 tokens -> far fewer than 100 writes.
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: True)
    worker = aw.AgentWorker()
    worker._agent = object()
    write_calls = 0
    await worker._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=7)
    coalesced_calls = write_calls
    assert coalesced_calls < 100, (
        f"coalesced path must not write once per token: {coalesced_calls}"
    )

    # Switch OFF: one direct write per token.
    monkeypatch.setattr(aw, "stream_coalesce_enabled", lambda: False)
    worker2 = aw.AgentWorker()
    worker2._agent = object()
    write_calls = 0
    await worker2._handle_prompt({"text": "hi", "session_id": "s1"}, request_id=8)
    assert write_calls >= 100, (
        f"switch-off path must keep per-token writes: {write_calls}"
    )


@pytest.mark.asyncio
async def test_wind_down_cancel_still_completes_drain_then_stop(
    monkeypatch: pytest.MonkeyPatch,
):
    """Cancelling the worker during the stream teardown must NOT skip drain
    or stop: the teardown completes (tail flush), then the cancellation
    propagates."""
    import appserver.agent_worker as aw

    order: list[str] = []

    class FakeCoalescer:
        def __init__(self, sink):
            self.sink = sink
            self._stopped = False

        async def start(self):
            pass

        async def stop(self):
            if self._stopped:
                return
            self._stopped = True
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", FakeCoalescer)
    worker = aw.AgentWorker()

    from appserver.tui import ProtocolTui

    drain_entered = asyncio.Event()
    release_drain = asyncio.Event()
    orig_drain = None

    tui = ProtocolTui("s1", lambda m: None)
    fake_coalescer = FakeCoalescer(None)
    orig_drain = tui.drain_push_tasks

    async def slow_drain():
        drain_entered.set()
        await release_drain.wait()
        await orig_drain()

    tui.drain_push_tasks = slow_drain

    async def caller():
        await worker._wind_down_stream(tui, fake_coalescer)

    caller_task = asyncio.create_task(caller())
    await drain_entered.wait()
    caller_task.cancel()  # external cancellation DURING the drain
    release_drain.set()
    with pytest.raises(asyncio.CancelledError):
        await caller_task
    # The teardown task ran to completion in the background (drain finished,
    # stop ran) even though the caller was cancelled.
    deadline = asyncio.get_running_loop().time() + 5.0
    while "coalescer_stop" not in order and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
    assert "coalescer_stop" in order, order


@pytest.mark.asyncio
async def test_stop_timeout_then_sink_accepts_cancel_no_duplicate_requeue():
    """When the final flush times out and the sink then ACCEPTS the
    cancellation, the backlog must be requeued exactly once (the timeout
    handler restored it; the cancelled flush must not requeue it again)."""
    async def cooperative_sink(kind: str, text: str) -> None:
        await asyncio.sleep(60)  # blocks past the timeout; responds to cancel

    c = StreamCoalescer(cooperative_sink)
    await c.start()
    await c.push("token", "A")
    await c.push("reasoning", "B")
    await asyncio.sleep(0.01)
    await asyncio.wait_for(c.stop(), timeout=StreamCoalescer.STOP_FLUSH_TIMEOUT_S + 2)
    # Backlog ('B', after the in-flight 'A') restored exactly once.
    pending = list(c._order)
    b_segments = [s for s in pending if s[1] == "reasoning"]
    assert len(b_segments) == 1, f"backlog must be requeued once: {pending}"
    assert c.undecided_segments and c.undecided_segments[0][0] == "token"
    await c.stop()


@pytest.mark.asyncio
async def test_wind_down_double_cancel_still_completes_stop(
    monkeypatch: pytest.MonkeyPatch,
):
    """A SECOND cancellation during the teardown must still not skip stop."""
    import appserver.agent_worker as aw

    order: list[str] = []

    class FakeCoalescer:
        def __init__(self, sink):
            self.sink = sink
            self._stopped = False

        async def start(self):
            pass

        async def stop(self):
            if self._stopped:
                return
            self._stopped = True
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", FakeCoalescer)
    worker = aw.AgentWorker()

    from appserver.tui import ProtocolTui

    drain_entered = asyncio.Event()
    release_drain = asyncio.Event()
    tui = ProtocolTui("s1", lambda m: None)
    fake_coalescer = FakeCoalescer(None)
    orig_drain = tui.drain_push_tasks

    async def slow_drain():
        drain_entered.set()
        await release_drain.wait()
        await orig_drain()

    tui.drain_push_tasks = slow_drain

    async def caller():
        await worker._wind_down_stream(tui, fake_coalescer)

    caller_task = asyncio.create_task(caller())
    await drain_entered.wait()
    caller_task.cancel()
    caller_task.cancel()  # double cancellation
    release_drain.set()
    with pytest.raises(asyncio.CancelledError):
        await caller_task
    deadline = asyncio.get_running_loop().time() + 5.0
    while "coalescer_stop" not in order and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
    assert "coalescer_stop" in order, order


@pytest.mark.asyncio
async def test_real_tui_mixed_kinds_preserve_order():
    """Real ProtocolTui + real StreamCoalescer: token → reasoning → progress
    → token keep order and merge adjacent same-kind segments."""
    from appserver.jsonrpc import StreamCoalescer
    from appserver.tui import ProtocolTui

    wire: list[tuple[str, str]] = []

    def sync_sink(kind: str, text: str) -> None:
        wire.append((kind, text))

    def emit(model: object) -> None:
        # Reasoning bypasses the coalescer and is emitted directly after the
        # ordering barrier, so the chain is not stuck behind the batcher.
        if type(model).__name__ == "ReasoningSnapshot":
            wire.append(("reasoning", str(getattr(model, "text", ""))))

    c = StreamCoalescer(sync_sink)
    tui = ProtocolTui("s1", emit)
    tui.set_coalescer(c)
    await c.start()
    try:
        tui.stream_token("T1")
        tui.set_thinking_expanded(True)
        tui.write_reasoning("R1")
        tui.write_progress("P1")
        tui.stream_token("T2")
        tui.stream_token("T3")  # adjacent token, merged with T2
        await tui.drain_push_tasks()
        await c.flush()
    finally:
        await c.stop()
    kinds = [k for k, _ in wire]
    assert kinds == ["token", "reasoning", "progress", "token"], kinds
    assert wire[0] == ("token", "T1"), wire
    assert wire[1] == ("reasoning", "R1"), wire
    assert wire[3] == ("token", "T2T3"), wire


@pytest.mark.asyncio
async def test_order_seq_monotonic_across_retries_and_concurrent_push():
    """Internal _order must stay sorted by seq through failures, retries and
    concurrent pushes (total order invariant)."""
    emitted: list[tuple[str, str]] = []
    gate = asyncio.Event()

    async def flaky_sink(kind: str, text: str) -> None:
        emitted.append((kind, text))
        if text in ("B", "D"):
            gate.set()
            await asyncio.sleep(0.02)
            raise RuntimeError(f"boom {text}")

    c = StreamCoalescer(flaky_sink)
    await c.push("token", "A")
    await c.push("reasoning", "B")
    t1 = asyncio.create_task(c.flush())
    await gate.wait()
    await c.push("progress", "C")
    with pytest.raises(RuntimeError):
        await t1
    gate.clear()
    await c.push("reasoning", "D")
    t2 = asyncio.create_task(c.flush())
    while not gate.is_set() and len(emitted) < 3:
        await asyncio.sleep(0.01)
    await c.push("progress", "E")
    with pytest.raises(RuntimeError):
        await t2
    seqs = [s for s, _, _ in c._order]
    assert seqs == sorted(seqs), f"_order must stay sorted by seq: {seqs}"
    await c.flush()
    assert not c.has_pending()
    await c.stop()


@pytest.mark.asyncio
async def test_barrier_with_async_sink_skips_without_losing_data():
    """With an async sink the sync barrier is skipped; the content is not
    lost — the async flush delivers it."""
    async def async_sink(kind: str, text: str) -> None:
        calls.append((kind, text))

    calls: list[tuple[str, str]] = []
    c = StreamCoalescer(async_sink)
    await c.push("token", "A")
    c.flush_submit_sync()  # async sink: barrier skips
    assert not calls, "barrier must skip for async sinks"
    await c.flush()  # async flush delivers
    assert calls == [("token", "A")], calls
    await c.stop()


@pytest.mark.asyncio
async def test_stop_cancelled_still_flushes_tail():
    """Cancelling stop() itself must not lose the trailing buffer: the final
    flush runs, then the cancellation propagates."""
    calls: list[tuple[str, str]] = []
    sink_entered = asyncio.Event()
    release_sink = asyncio.Event()

    async def gated_sink(kind: str, text: str) -> None:
        sink_entered.set()
        await release_sink.wait()
        calls.append((kind, text))

    c = StreamCoalescer(gated_sink)
    await c.start()
    # Threshold push blocks inside the sink: a flush is deterministically
    # in progress when stop() runs.
    push_task = asyncio.create_task(c.push("token", "a" * 1024))
    await sink_entered.wait()
    stop_task = asyncio.create_task(c.stop())
    await asyncio.sleep(0.05)
    stop_task.cancel()  # external cancellation mid-teardown
    release_sink.set()
    with pytest.raises(asyncio.CancelledError):
        await stop_task
    await push_task
    await asyncio.sleep(0.2)
    # The tail was delivered exactly once despite the cancellation.
    assert calls == [("token", "a" * 1024)], calls
    await c.stop()


@pytest.mark.asyncio
async def test_stop_while_ticker_flushing_completes_normally():
    """A controlled stop() while a flush is in progress must NOT raise
    CancelledError and must deliver the tail (no false external-cancel)."""
    calls: list[tuple[str, str]] = []
    sink_entered = asyncio.Event()
    release_sink = asyncio.Event()

    async def gated_sink(kind: str, text: str) -> None:
        sink_entered.set()
        await release_sink.wait()
        calls.append((kind, text))

    c = StreamCoalescer(gated_sink)
    await c.start()
    push_task = asyncio.create_task(c.push("token", "a" * 1024))
    await sink_entered.wait()  # flush is inside the sink
    stop_task = asyncio.create_task(c.stop())
    await asyncio.sleep(0.05)  # stop() is now cancelling mid-flush
    release_sink.set()
    await stop_task  # must complete normally, no CancelledError
    await push_task
    assert calls == [("token", "a" * 1024)], calls
    assert not stop_task.cancelled()
    await c.stop()


@pytest.mark.asyncio
async def test_stop_cancel_waits_for_residual_flush_before_propagating():
    """When stop() is cancelled BEFORE the residual flush starts, stop() must
    wait for that flush to deliver the backlog tail before propagating the
    cancel (the in-flight segment stays UNDECIDED — never re-sent)."""
    for _attempt in range(5):
        calls: list[tuple[str, str]] = []
        sink_entered = asyncio.Event()
        release_sink = asyncio.Event()

        async def gated_sink(
            kind: str, text: str,
            _calls=calls, _entered=sink_entered, _release=release_sink,
        ) -> None:
            _entered.set()
            await _release.wait()
            _calls.append((kind, text))

        c = StreamCoalescer(gated_sink)
        await c.push("token", "first")
        await c.push("reasoning", "second")
        stop_task = asyncio.create_task(c.stop())
        await sink_entered.wait()
        stop_task.cancel()
        release_sink.set()
        with pytest.raises(asyncio.CancelledError):
            await stop_task
        if len(calls) >= 1:
            break
        await asyncio.sleep(0.01)
    assert len(calls) >= 1, (
        f"stop must wait for the backlog flush: {calls}"
    )
    await c.stop()


@pytest.mark.asyncio
async def test_wind_down_waits_for_teardown_before_propagating_cancel(
    monkeypatch: pytest.MonkeyPatch,
):
    """_wind_down_stream must wait for the teardown (drain->stop) to complete
    before the cancellation propagates — no racing tail."""
    import appserver.agent_worker as aw

    order: list[str] = []

    class FakeCoalescer:
        def __init__(self, sink):
            self.sink = sink
            self._stopped = False

        async def start(self):
            pass

        async def stop(self):
            if self._stopped:
                return
            self._stopped = True
            order.append("coalescer_stop")

    monkeypatch.setattr(aw, "StreamCoalescer", FakeCoalescer)
    worker = aw.AgentWorker()

    from appserver.tui import ProtocolTui

    drain_entered = asyncio.Event()
    release_drain = asyncio.Event()
    tui = ProtocolTui("s1", lambda m: None)
    fake_coalescer = FakeCoalescer(None)
    orig_drain = tui.drain_push_tasks

    async def slow_drain():
        drain_entered.set()
        await release_drain.wait()
        await orig_drain()

    tui.drain_push_tasks = slow_drain

    async def caller():
        await worker._wind_down_stream(tui, fake_coalescer)

    caller_task = asyncio.create_task(caller())
    await drain_entered.wait()
    caller_task.cancel()
    await asyncio.sleep(0.05)  # let the teardown wait for the drain
    assert "coalescer_stop" not in order, (
        "stop must not run before the drain finished"
    )
    release_drain.set()
    with pytest.raises(asyncio.CancelledError):
        await caller_task
    assert "coalescer_stop" in order, (
        "teardown must complete before the cancellation propagates"
    )


@pytest.mark.asyncio
async def test_switch_0_mixed_kinds_keep_legacy_direct_order():
    """AC7 0-d档 regression: with the coalescer off, mixed kinds and plain
    emits keep the legacy per-call direct emit order."""
    from appserver.tui import ProtocolTui

    emitted: list[str] = []
    tui = ProtocolTui("s1", lambda m: emitted.append(type(m).__name__))
    tui.stream_token("T")       # direct MessageDelta
    tui.set_thinking_expanded(True)
    tui.write_reasoning("R")    # direct ReasoningSnapshot
    tui.write_progress("P")     # direct ProgressUpdate
    tui.write_tool_call("read", {"filePath": "x"})
    tui.write_tool_result("ok", call_id="c1")
    tui.stream_token("T2")
    assert emitted == [
        "MessageDelta",
        "ReasoningSnapshot",
        "ProgressUpdate",
        "ToolBegin",
        "ProgressUpdate",  # tool wait label, after the tool card opens
        "ToolEnd",
        "MessageDelta",
    ], emitted


async def _record(calls: list[tuple[str, str]], kind: str, text: str) -> None:
    calls.append((kind, str(text)))
