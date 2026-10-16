"""Tool RPC frames. One device call runs once, and one task sends them."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Any

import websockets

from RxyCode.RxyCode1_1_0.execution.tool_journal import (
    RemoteJournalAdapter,
    remote_checkpoint_id,
)

CHUNK_LIMIT = 4096
WINDOW = 2


def _split(text: str, limit: int) -> list[str]:
    if not text:
        return []
    return [text[index:index + limit] for index in range(0, len(text), limit)]


class ToolRpcServer:
    """Runner side of invoke, chunk, result, ack, status, and cancel."""

    def __init__(
        self,
        *,
        device_id: str,
        journal: RemoteJournalAdapter,
        execute: Callable[..., str],
    ) -> None:
        self.device_id = device_id
        self.journal = journal
        self.execute = execute
        self.buffers: dict[str, list[str]] = {}
        self.results: dict[str, str] = {}
        self.meta: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self.cancel_flags: dict[str, threading.Event] = {}
        self.chunk_acks: dict[str, int] = {}
        self.ack_events: dict[str, asyncio.Event] = {}
        self._writers: set[int] = set()
        self._performs: set[asyncio.Task[None]] = set()
        self._guard = threading.Lock()

    def writer_count(self) -> int:
        with self._guard:
            return len(self._writers)

    async def handler(self, ws: Any) -> None:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        writer = asyncio.create_task(self._write(ws, queue))
        with self._guard:
            self._writers.add(id(writer))
        try:
            async for raw in ws:
                await self._on(json.loads(raw), queue)
        finally:
            for task in list(self._performs):
                task.cancel()
            with self._guard:
                self._writers.discard(id(writer))
            await queue.put(None)
            try:
                await writer
            except Exception:
                return

    async def _write(self, ws: Any, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        while True:
            item = await queue.get()
            if item is None:
                return
            await ws.send(json.dumps(item))

    async def _on(self, frame: dict[str, Any], queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        kind = str(frame.get("type") or "")
        if kind == "invoke":
            task = asyncio.create_task(self._invoke(frame, queue))
            self._performs.add(task)
            task.add_done_callback(self._performs.discard)
            return
        if kind == "ack":
            await self._ack(frame)
            return
        if kind == "chunk_ack":
            call_id = str(frame.get("call_id") or "")
            seq = int(frame.get("seq") or 0)
            self.chunk_acks[call_id] = max(self.chunk_acks.get(call_id, 0), seq)
            event = self.ack_events.get(call_id)
            if event is not None:
                event.set()
            return
        if kind == "status":
            await self._status(frame, queue)
            return
        if kind == "cancel":
            call_id = str(frame.get("call_id") or "")
            self.cancel_flags.setdefault(call_id, threading.Event()).set()
            await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})

    async def _invoke(
        self,
        frame: dict[str, Any],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        call_id = str(frame.get("call_id") or "")
        attempt_id = str(frame.get("attempt_id") or "")
        tool = str(frame.get("tool") or "")
        args = frame.get("args") if isinstance(frame.get("args"), dict) else {}
        if frame.get("device_id") != self.device_id:
            await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
            return
        self.meta[call_id] = (attempt_id, tool, args)
        reservation = self.journal.reserve(
            attempt_id=attempt_id,
            call_id=call_id,
            tool=tool,
            args=args,
            checkpoint_id=remote_checkpoint_id(attempt_id),
        )
        if reservation.action == "reuse":
            await queue.put(
                {
                    "type": "result",
                    "call_id": call_id,
                    "state": "completed",
                    "result": reservation.result,
                    "replay": True,
                }
            )
            return
        if reservation.action != "execute":
            await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
            return
        cancel = self.cancel_flags.setdefault(call_id, threading.Event())
        if cancel.is_set():
            await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})
            return
        result = await asyncio.to_thread(self.execute, args, cancel=cancel)
        if cancel.is_set():
            await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})
            return
        text = "" if result is None else str(result)
        self.results[call_id] = text
        parts = _split(text, CHUNK_LIMIT)
        self.buffers[call_id] = parts
        self.ack_events[call_id] = asyncio.Event()
        try:
            if len(text) > CHUNK_LIMIT:
                for seq, data in enumerate(parts, start=1):
                    await self._wait_window(call_id, seq)
                    await queue.put(
                        {"type": "chunk", "call_id": call_id, "seq": seq, "data": data}
                    )
            await queue.put(
                {
                    "type": "result",
                    "call_id": call_id,
                    "state": "completed",
                    "result": text,
                }
            )
        except asyncio.CancelledError:
            return

    async def _wait_window(self, call_id: str, seq: int) -> None:
        while seq > self.chunk_acks.get(call_id, 0) + WINDOW:
            event = self.ack_events[call_id]
            event.clear()
            if seq <= self.chunk_acks.get(call_id, 0) + WINDOW:
                return
            await event.wait()

    async def _ack(self, frame: dict[str, Any]) -> None:
        call_id = str(frame.get("call_id") or "")
        meta = self.meta.get(call_id)
        if meta is None or frame.get("subject") != "result":
            return
        attempt_id, tool, args = meta
        if self.journal.state(attempt_id=attempt_id, call_id=call_id) != "unknown":
            return
        self.journal.complete(
            attempt_id=attempt_id,
            call_id=call_id,
            tool=tool,
            args=args,
            result=self.results.get(call_id, ""),
        )

    async def _status(
        self,
        frame: dict[str, Any],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        call_id = str(frame.get("call_id") or "")
        meta = self.meta.get(call_id)
        if meta is None:
            await queue.put({"type": "status", "call_id": call_id, "state": "not_started"})
            return
        attempt_id, tool, args = meta
        state = self.journal.state(attempt_id=attempt_id, call_id=call_id)
        resume_from = int(frame.get("resume_from") or 0)
        if state == "completed":
            reservation = self.journal.reserve(
                attempt_id=attempt_id,
                call_id=call_id,
                tool=tool,
                args=args,
                checkpoint_id=remote_checkpoint_id(attempt_id),
            )
            await queue.put(
                {
                    "type": "result",
                    "call_id": call_id,
                    "state": "completed",
                    "result": reservation.result,
                    "replay": True,
                }
            )
            return
        await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
        for seq, data in enumerate(self.buffers.get(call_id, []), start=1):
            if seq > resume_from:
                await queue.put(
                    {
                        "type": "chunk",
                        "call_id": call_id,
                        "seq": seq,
                        "data": data,
                        "replay": True,
                    }
                )
        if call_id in self.results:
            await queue.put(
                {
                    "type": "result",
                    "call_id": call_id,
                    "state": "recovery_required",
                    "result": self.results[call_id],
                    "replay": True,
                }
            )


class RunningToolRpc:
    def __init__(self, server: ToolRpcServer, stop: threading.Event, thread: threading.Thread, port: int) -> None:
        self._server = server
        self._stop = stop
        self._thread = thread
        self.url = f"ws://127.0.0.1:{port}/tool-rpc"

    def writer_count(self) -> int:
        return self._server.writer_count()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def serve_tool_rpc(
    *,
    device_id: str,
    journal: RemoteJournalAdapter,
    execute: Callable[..., str],
) -> RunningToolRpc:
    rpc = ToolRpcServer(device_id=device_id, journal=journal, execute=execute)
    stop = threading.Event()
    ready = threading.Event()
    holder: dict[str, int] = {}

    def run() -> None:
        async def main() -> None:
            async with websockets.serve(rpc.handler, "127.0.0.1", 0) as sockets:
                holder["port"] = next(iter(sockets.sockets)).getsockname()[1]
                ready.set()
                while not stop.is_set():
                    await asyncio.sleep(0.05)
            for task in list(rpc._performs):
                task.cancel()

        asyncio.run(main())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(timeout=10):
        stop.set()
        raise RuntimeError("tool rpc did not start")
    return RunningToolRpc(rpc, stop, thread, holder["port"])
