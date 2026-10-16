"""Cloud-side dispatch onto one device tool RPC socket."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import websockets


class DispatchRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class DispatchResult:
    state: str
    result: str | None
    chunks: list[tuple[int, str]]
    truncated: bool = False


def _require_loopback_or_tls(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme == "wss":
        return
    if parsed.scheme == "ws" and host in {"127.0.0.1", "localhost", "::1"}:
        return
    raise DispatchRejected("TLS_REQUIRED")


class RunnerClient:
    """Send invoke, status, ack, and cancel. Frames leave through one socket."""

    def invoke(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        ack: bool = True,
        stop_after_chunks: int | None = None,
    ) -> DispatchResult:
        _require_loopback_or_tls(url)
        return asyncio.run(
            self._invoke(
                url=url,
                device_id=device_id,
                call_id=call_id,
                attempt_id=attempt_id,
                tool=tool,
                args=args,
                ack=ack,
                stop_after_chunks=stop_after_chunks,
            )
        )

    def resume(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        resume_from: int,
    ) -> DispatchResult:
        _require_loopback_or_tls(url)
        return asyncio.run(
            self._resume(
                url=url,
                device_id=device_id,
                call_id=call_id,
                attempt_id=attempt_id,
                tool=tool,
                args=args,
                resume_from=resume_from,
            )
        )

    def invoke_and_cancel(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        started: Any,
    ) -> DispatchResult:
        _require_loopback_or_tls(url)
        return asyncio.run(
            self._cancel(
                url=url,
                device_id=device_id,
                call_id=call_id,
                attempt_id=attempt_id,
                tool=tool,
                args=args,
                started=started,
            )
        )

    async def _invoke(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        ack: bool,
        stop_after_chunks: int | None,
    ) -> DispatchResult:
        chunks: list[tuple[int, str]] = []
        async with websockets.connect(url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "invoke",
                        "device_id": device_id,
                        "call_id": call_id,
                        "attempt_id": attempt_id,
                        "tool": tool,
                        "args": args,
                    }
                )
            )
            while True:
                frame = json.loads(await ws.recv())
                kind = frame.get("type")
                if kind == "chunk":
                    chunks.append((int(frame["seq"]), str(frame.get("data") or "")))
                    if stop_after_chunks is not None and len(chunks) >= stop_after_chunks:
                        return DispatchResult("unacked", None, chunks, False)
                    continue
                if kind == "result":
                    if not ack:
                        return DispatchResult("unacked", frame.get("result"), chunks, False)
                    await ws.send(
                        json.dumps({"type": "ack", "call_id": call_id, "subject": "result"})
                    )
                    return DispatchResult("completed", frame.get("result"), chunks, False)
                if kind == "status":
                    return DispatchResult(str(frame.get("state")), None, chunks, False)

    async def _resume(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        resume_from: int,
    ) -> DispatchResult:
        del tool, args
        chunks: list[tuple[int, str]] = []
        seen: set[int] = set()
        truncated = False
        async with websockets.connect(url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "status",
                        "device_id": device_id,
                        "call_id": call_id,
                        "attempt_id": attempt_id,
                        "resume_from": resume_from,
                    }
                )
            )
            while True:
                frame = json.loads(await ws.recv())
                kind = frame.get("type")
                if kind == "chunk":
                    seq = int(frame["seq"])
                    if seq in seen or seq <= resume_from:
                        continue
                    seen.add(seq)
                    chunks.append((seq, str(frame.get("data") or "")))
                    continue
                if kind == "result":
                    await ws.send(
                        json.dumps({"type": "ack", "call_id": call_id, "subject": "result"})
                    )
                    return DispatchResult(
                        str(frame.get("state") or "completed"),
                        frame.get("result"),
                        chunks,
                        bool(frame.get("truncated")),
                    )
                if kind == "status":
                    truncated = bool(frame.get("truncated"))
                    if frame.get("state") == "recovery_required" and not chunks:
                        continue
                    if frame.get("state") == "recovery_required":
                        continue
                    return DispatchResult(str(frame.get("state")), None, chunks, truncated)

    async def _cancel(
        self,
        *,
        url: str,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        started: Any,
    ) -> DispatchResult:
        async with websockets.connect(url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "invoke",
                        "device_id": device_id,
                        "call_id": call_id,
                        "attempt_id": attempt_id,
                        "tool": tool,
                        "args": args,
                    }
                )
            )
            found = await asyncio.to_thread(started.wait, 3)
            if not found:
                raise TimeoutError("tool did not start")
            await ws.send(json.dumps({"type": "cancel", "call_id": call_id, "device_id": device_id}))
            frame = json.loads(await ws.recv())
            return DispatchResult(str(frame.get("state")), frame.get("result"), [], False)
