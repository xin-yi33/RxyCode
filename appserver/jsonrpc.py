"""Newline-delimited JSON-RPC helpers for appserver stdio transport."""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
import os
import sys
import threading
from collections.abc import Awaitable, Callable
from typing import Any

_stdout_lock = threading.Lock()
_logger = logging.getLogger(__name__)


def _log_stream_coalescer_error(exc: BaseException) -> None:
    _logger.warning("stream coalescer flush failed during stop: %r", exc)


def stream_coalesce_enabled() -> bool:
    """C3 switch: RXYCODE_STREAM_COALESCE (default 1, category ③ perf).

    1 = batch stream notifications through StreamCoalescer (one to_thread per
    batch instead of per token); 0 = legacy per-token direct write.  Any
    other value falls back to the default (1).
    """
    return os.environ.get("RXYCODE_STREAM_COALESCE", "1") != "0"


def write_message_sync(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout (sync; safe from worker threads)."""
    with _stdout_lock:
        sys.stdout.write(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        sys.stdout.flush()


async def write_message(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message without blocking the asyncio event loop."""
    await asyncio.to_thread(write_message_sync, message)


class StreamCoalescer:
    """C3: batch per-token stream notifications into merged writes.

    Full-order record: ``_order`` keeps the total push sequence; ``flush()``
    emits in that order, merging adjacent same-kind segments into one sink
    call.  ``_buffer`` only drives the byte-threshold check.  Flush semantics
    (§4.2): already-written segments are never re-sent (at-most-once); unsent
    segments are requeued for the next flush (at-least-once); the segment
    being written when the sink raises/cancels is UNDECIDED — not retried,
    not silently dropped, surfaced to the caller.
    """

    FLUSH_INTERVAL_S = 0.07          # aligned with api_server_stream.py:283
    FLUSH_BYTE_THRESHOLD = 1024
    #: Bound for waiting on the flush lock: a zombie flush task left behind by
    #: a hard-timed-out teardown must not block every later flush forever.
    LOCK_WAIT_TIMEOUT_S = 2.0

    def __init__(
        self,
        sink: Callable[[str, str], Awaitable[None]] | Callable[[str, str], None],
    ) -> None:
        #: The sink may be async (§4.2) or a fast synchronous submitter (the
        #: worker's FIFO-writer enqueue).  Sync sinks additionally enable the
        #: synchronous ordering barrier (flush_submit_sync) used by the TUI
        #: to keep plain emits ordered against buffered stream content.
        self._sink = sink
        try:
            _call_attr = type(sink).__call__
        except AttributeError:
            _call_attr = None
        self._sink_is_async = inspect.iscoroutinefunction(sink) or (
            _call_attr is not None and inspect.iscoroutinefunction(_call_attr)
        )
        self._buffer: dict[str, str] = {}
        self._order: list[tuple[int, str, str]] = []
        self._pending_bytes = 0
        self._seq = itertools.count(1)
        self._flush_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self.degraded = False
        #: Ticker tasks cancelled by a controlled stop(): their CancelledError
        #: is the CONTROLLED shutdown cancel, not an external cancellation, so
        #: the done callback must not flag them as degraded.  Task identity is
        #: used instead of a shared boolean to avoid callback-timing races; a
        #: list preserves insertion order for bounded trimming (n <= 32, so
        #: membership scans are cheap).
        self._canceled_by_stop: list[asyncio.Task] = []
        #: Set when a final flush hard-times-out and the old flush task may
        #: still be running (swallowing sink): further flushes return
        #: immediately instead of waiting on the lock held by the zombie task.
        self._terminated = False
        #: Segment currently being written by the sink (kind, text), or None.
        #: Used to record UNDECIDED for the in-flight segment when the final
        #: flush hard-times-out and the sink swallows the cancellation.
        self._inflight_segment: tuple[str, str] | None = None
        #: Unsent segments of the in-progress flush (with original seqs),
        #: restored by a hard-timeout teardown so a later flush can retry
        #: them; cleared when the flush finishes or fails normally.
        self._flush_backlog: list[tuple[int, str, str]] = []
        #: Flush generation token: incremented when a hard-timeout aborts a
        #: flush.  A zombie flush task checks its captured epoch after every
        #: sink call and stops submitting further segments once aborted, so a
        #: recovered flush can safely retry the backlog without duplicates.
        self._flush_epoch = 0
        #: Segments whose write outcome is UNDECIDED (the sink raised or was
        #: cancelled mid-write): recorded with the exception so callers can
        #: observe what was NOT durably delivered.  [(kind, text, exc)]
        self.undecided_segments: list[tuple[str, str, BaseException]] = []

    async def start(self) -> None:
        """Start the background ticker.

        Re-entrant: a second call while a ticker is running stops the old one
        (which flushes its tail) and starts a fresh ticker — this is the
        documented recovery path after a ticker failure.  A failing old-ticker
        teardown is logged but never prevents the new ticker from starting, so
        recovery via start() is always possible; a successful start clears the
        degraded flag so the observable state reflects recovery.
        """
        if self._flush_task is not None and not self._flush_task.done():
            try:
                await self.stop()
            except Exception:
                self.degraded = True
        # Recovery after a hard-timeout teardown: clear the terminated flag so
        # a fresh start() can flush again.  (A zombie flush task from the
        # timed-out teardown may still hold the lock; a later flush then waits
        # for it or, if the sink truly never returns, the caller should build
        # a new coalescer instead.)
        self._terminated = False
        self.degraded = False
        self._flush_task = asyncio.create_task(self._ticker())
        self._flush_task.add_done_callback(self._on_ticker_done)

    def _on_ticker_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            # An EXTERNAL cancellation (not a controlled stop() cancel) is
            # observable: the ticker died without a clean teardown.
            if task not in self._canceled_by_stop:
                self.degraded = True
            return
        exc = task.exception()
        if exc is not None:
            self.degraded = True

    async def _ticker(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.FLUSH_INTERVAL_S)
                if self._order:
                    await self.flush()
        except asyncio.CancelledError:
            raise

    def push_sync(self, kind: str, text: str) -> bool:
        """Synchronously append to the pending batch (safe on the event
        loop; ordering-correct against concurrent plain emits).

        Returns True when the byte threshold is reached and a flush should
        be scheduled by the caller (async work is never done here).
        """
        seq = next(self._seq)
        self._buffer[kind] = self._buffer.get(kind, "") + text
        self._pending_bytes += len(text.encode("utf-8"))
        self._order.append((seq, kind, text))
        return self._pending_bytes >= self.FLUSH_BYTE_THRESHOLD

    async def push(self, kind: str, text: str) -> None:
        if self.push_sync(kind, text):
            await self.flush()

    async def flush(self) -> None:
        # _terminated is cleared by start(); retries after a hard-timeout are
        # allowed (the zombie flush is epoch-aborted, so it cannot duplicate),
        # bounded by the lock-wait timeout while the zombie holds the lock.
        try:
            await asyncio.wait_for(
                self._flush_lock.acquire(), timeout=self.LOCK_WAIT_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            # A zombie flush task from a hard-timed-out teardown may still
            # hold the lock; do not block every later flush forever.
            self.degraded = True
            return
        try:
            await self._flush_locked()
        finally:
            self._flush_lock.release()

    def has_pending(self) -> bool:
        return bool(self._order)

    def flush_submit_sync(self) -> None:
        """Synchronous ordering barrier for the TUI: submits every buffered
        segment to a SYNC sink right now, so a plain emit that follows lands
        in the writer queue AFTER the buffered stream content.

        Failure semantics mirror the async flush: a segment whose enqueue
        raises is recorded as UNDECIDED (not silently dropped), and the
        remaining segments are requeued with their original seqs so a later
        flush retries them (at-least-once).  A sink that unexpectedly returns
        an awaitable is treated as a hard error with the same accounting.

        Concurrency: the barrier is skipped while an async flush holds the
        lock (that flush will submit this content).  In the PRODUCTION path
        the sink is a synchronous FIFO enqueue with no awaits, so the lock is
        held for a single event-loop iteration and no plain emit can
        interleave with the flush; with an async sink the ordering degrades
        only in that narrow window (data is never lost).
        """
        if (
            self._sink_is_async
            or not self._order
            or self._terminated
            or self._flush_lock.locked()
        ):
            return
        pending = sorted(self._order, key=lambda s: s[0])  # total order by seq
        self._order = []
        self._buffer.clear()
        self._pending_bytes = 0
        merged: list[tuple[str, str]] = []
        merged_seqs: list[int] = []
        for seq, kind, text in pending:
            if merged and merged[-1][0] == kind and kind != "progress":
                merged[-1] = (kind, merged[-1][1] + text)
            else:
                merged.append((kind, text))
                merged_seqs.append(seq)
        written = 0
        accounted = False
        try:
            for kind, text in merged:
                result = self._sink(kind, text)
                if inspect.isawaitable(result):
                    # A "sync" callable that returns an awaitable cannot be
                    # submitted by the barrier: close the stray coroutine so
                    # it cannot leak, then account it like any failure.
                    if hasattr(result, "close"):
                        result.close()
                    self.undecided_segments.append(
                        (
                            merged[written][0],
                            merged[written][1],
                            RuntimeError(
                                "sync ordering barrier requires a synchronous sink"
                            ),
                        )
                    )
                    self._requeue_unsent(
                        self._unsent_with_seqs(merged, merged_seqs, written + 1)
                    )
                    accounted = True
                    raise RuntimeError(
                        "sync ordering barrier requires a synchronous sink"
                    )
                written += 1
        except BaseException as exc:
            if not accounted and written < len(merged):
                # The failing segment is UNDECIDED; requeue the rest.
                kind, text = merged[written]
                self.undecided_segments.append((kind, text, exc))
            if not accounted:
                self._requeue_unsent(
                    self._unsent_with_seqs(merged, merged_seqs, written + 1)
                )
            raise

    async def _flush_locked(self) -> None:
        pending = sorted(self._order, key=lambda s: s[0])  # total order by seq
        self._order = []
        self._buffer.clear()
        self._pending_bytes = 0
        merged: list[tuple[str, str]] = []
        merged_seqs: list[int] = []
        for seq, kind, text in pending:
            if merged and merged[-1][0] == kind and kind != "progress":
                merged[-1] = (kind, merged[-1][1] + text)
            else:
                merged.append((kind, text))
                merged_seqs.append(seq)
        #: Recoverable backlog for a hard-timeout teardown: the segments NOT
        #: yet written (the in-flight first segment is EXCLUDED — it is
        #: UNDECIDED, never re-sent).  Restored to _order by the caller so a
        #: later flush can retry them (at-least-once) even though the zombie
        #: flush task holds them in its local scope.
        self._flush_backlog = self._unsent_with_seqs(merged, merged_seqs, 1)
        epoch = self._flush_epoch
        written = 0
        try:
            for kind, text in merged:
                if epoch != self._flush_epoch:
                    # This flush was aborted by a hard-timeout teardown:
                    # stop submitting further segments (at-most-once).
                    self._flush_backlog = []
                    return
                self._inflight_segment = (kind, text)
                try:
                    result = self._sink(kind, text)
                    if inspect.isawaitable(result):
                        await result
                finally:
                    self._inflight_segment = None
                written += 1
                self._flush_backlog = self._unsent_with_seqs(
                    merged, merged_seqs, written + 1
                )
        except asyncio.CancelledError:
            if epoch == self._flush_epoch:
                # Normal cancellation: requeue unsent segments.  When a
                # hard-timeout teardown already aborted this flush (epoch
                # changed) it restored the backlog and recorded UNDECIDED
                # itself — do NOT requeue or record again.
                self._requeue_unsent(
                    self._unsent_with_seqs(merged, merged_seqs, written + 1)
                )
                self._flush_backlog = []
                if written < len(merged):
                    # The segment being written when cancelled is UNDECIDED:
                    # record it durably instead of dropping it silently.
                    kind, text = merged[written]
                    self.undecided_segments.append(
                        (
                            kind,
                            text,
                            asyncio.CancelledError("sink cancelled mid-write"),
                        )
                    )
            raise
        except BaseException as exc:
            if epoch == self._flush_epoch:
                self._requeue_unsent(
                    self._unsent_with_seqs(merged, merged_seqs, written + 1)
                )
                self._flush_backlog = []
                if written < len(merged):
                    kind, text = merged[written]
                    self.undecided_segments.append((kind, text, exc))
            raise
        self._flush_backlog = []

    @staticmethod
    def _unsent_with_seqs(
        merged: list[tuple[str, str]],
        merged_seqs: list[int],
        start: int,
    ) -> list[tuple[int, str, str]]:
        """Pair merged segments with their leading seq, from ``start`` on."""
        return [
            (seq, kind, text)
            for seq, (kind, text) in zip(merged_seqs[start:], merged[start:])
        ]

    def _requeue_unsent(self, unsent: list[tuple[int, str, str]]) -> None:
        """Put unsent merged segments back at the head of _order with their
        ORIGINAL seq values preserved.

        Segments pushed while the failed flush was in flight carry larger
        seqs; keeping the original seqs here means the total order by seq
        never inverts (older content always precedes newer content).  The
        byte accounting is restored so the threshold check keeps working.

        INVARIANT: ``_order`` is the ONLY source of what gets emitted; the
        ``_buffer``/``_pending_bytes`` state exists solely for threshold and
        ticker decisions, never for ordering.
        """
        for _seq, kind, text in unsent:
            self._buffer[kind] = self._buffer.get(kind, "") + text
            self._pending_bytes += len(text.encode("utf-8"))
        self._order[:0] = unsent

    async def stop(self) -> None:
        """Tear down: cancel the ticker, then flush the trailing buffer.

        Fault-tolerant by contract (PHASE-C §4.2 teardown): a ticker that
        already failed, a final-flush sink failure, or a sink that never
        returns (bounded by STOP_FLUSH_TIMEOUT_S) is surfaced through
        ``degraded``/``undecided_segments`` and logged, never raised to the
        caller — the caller must still be able to send its terminal response.
        """
        if self._flush_task is None:
            # Nothing was started: still flush the residual buffer under the
            # same fault-tolerant contract.
            await self._guarded_final_flush()
            return
        if self._flush_task not in self._canceled_by_stop:
            self._canceled_by_stop.append(self._flush_task)
        if len(self._canceled_by_stop) > 32:
            # Bound the list: drop the oldest half.
            del self._canceled_by_stop[:16]
        cancelled = False
        try:
            if (
                self._flush_task.done()
                and not self._flush_task.cancelled()
                and self._flush_task.exception() is not None
            ):
                # The ticker already failed: surface degraded synchronously,
                # independent of the done-callback scheduling.
                self.degraded = True
            self._flush_task.cancel()
            # asyncio.wait does NOT propagate the ticker's own cancellation
            # into this coroutine, so a controlled stop completes normally;
            # only an EXTERNAL cancellation of stop() itself raises here.
            try:
                await asyncio.wait({self._flush_task}, timeout=5.0)
            except asyncio.CancelledError:
                cancelled = True  # external cancellation of stop()
            # The final flush runs regardless (consumed-cancel continuation).
            await self._guarded_final_flush()
        except asyncio.CancelledError:
            # stop() was cancelled again during the final flush: the flush is
            # fault-tolerant and consumed the cancellation; propagate.
            cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _flush_guarded_coro(self) -> None:
        """Run the final flush inside its own task, consuming ONE propagated
        cancellation: if the task is cancelled (a parent's cancellation
        reaches it), the flush requeues its unsent segments, so a single
        retry delivers them; the cancellation is then re-raised so the task
        still ends cancelled."""
        try:
            await self.flush()
        except asyncio.CancelledError:
            await self.flush()  # unsent segments were requeued; deliver them
            raise

    async def _guarded_final_flush(self) -> None:
        """Final trailing flush under a HARD timeout.

        The flush runs in its own task behind a shield: when the timeout
        fires we cancel it best-effort and return WITHOUT waiting for it, so
        a sink that swallows cancellation cannot extend the teardown.  The
        residual is surfaced via degraded/undecided_segments (recorded by
        _flush_locked); any exception is logged, never raised to the caller.
        """
        flush_task = asyncio.create_task(self._flush_guarded_coro())
        try:
            await asyncio.wait_for(
                asyncio.shield(flush_task), timeout=self.STOP_FLUSH_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            self.degraded = True
            # The zombie flush task may still hold the lock (swallowing sink):
            # mark the coalescer terminated AND abort its generation so it
            # stops submitting further segments (at-most-once).  Record the
            # in-flight segment as UNDECIDED and restore the unsent backlog
            # (at-least-once) so nothing is lost.
            self._terminated = True
            self._flush_epoch += 1
            if self._inflight_segment is not None:
                kind, text = self._inflight_segment
                self.undecided_segments.append(
                    (kind, text, asyncio.TimeoutError("final flush timed out"))
                )
            if self._flush_backlog:
                self._requeue_unsent(self._flush_backlog)
                self._flush_backlog = []
            flush_task.cancel()  # best-effort; do NOT wait for it
            _log_stream_coalescer_error(asyncio.TimeoutError("final flush timed out"))
        except asyncio.CancelledError:
            # stop() itself was cancelled: the flush task consumed the
            # propagated cancellation and is delivering the requeued segments
            # (best effort).  WAIT for it with a cancellation-proof loop
            # (asyncio.wait does not propagate cancellations into the awaited
            # task; a repeated cancellation of stop() only restarts the wait)
            # so the trailing buffer is in the writer queue before we
            # propagate.  Any sink failure during that wait is recorded, but
            # the ORIGINAL cancellation is what propagates.
            self.degraded = True
            flush_task.cancel()
            while not flush_task.done():
                try:
                    await asyncio.wait({flush_task}, timeout=10.0)
                    break
                except asyncio.CancelledError:
                    continue
            if flush_task.cancelled():
                pass
            elif flush_task.exception() is not None:
                self.degraded = True
                _log_stream_coalescer_error(flush_task.exception())
            raise
        except BaseException as exc:
            self.degraded = True
            if not flush_task.done():
                flush_task.cancel()
            _log_stream_coalescer_error(exc)

    STOP_FLUSH_TIMEOUT_S = 5.0


def parse_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("JSON-RPC payload must be an object")
    return payload


def is_client_request(message: dict[str, Any]) -> bool:
    return isinstance(message.get("method"), str) and "id" in message


def is_client_response(message: dict[str, Any]) -> bool:
    return "id" in message and ("result" in message or "error" in message)


def is_notification(message: dict[str, Any]) -> bool:
    return isinstance(message.get("method"), str) and "id" not in message
