"""Cloud-side dispatch onto the device's outbound websocket."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class DispatchResult:
    state: str
    result: str | None
    chunks: list[tuple[int, str]]
    truncated: bool = False


class RunnerClient:
    """Send tool frames on the paired device socket and read the replies."""

    def invoke(
        self,
        *,
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        ack: bool = True,
        stop_after_chunks: int | None = None,
    ) -> DispatchResult:
        return asyncio.run(
            self._invoke(
                gateway=gateway,
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
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        resume_from: int,
    ) -> DispatchResult:
        return asyncio.run(
            self._resume(
                gateway=gateway,
                device_id=device_id,
                call_id=call_id,
                attempt_id=attempt_id,
                resume_from=resume_from,
            )
        )

    def invoke_and_cancel(
        self,
        *,
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        started: Any,
    ) -> DispatchResult:
        return asyncio.run(
            self._cancel(
                gateway=gateway,
                device_id=device_id,
                call_id=call_id,
                attempt_id=attempt_id,
                tool=tool,
                args=args,
                started=started,
            )
        )

    async def _send(self, gateway: Any, device_id: str, frame: dict[str, Any]) -> None:
        await asyncio.to_thread(gateway.send_tool, device_id, frame)

    async def _recv(self, gateway: Any, device_id: str, call_id: str) -> dict[str, Any]:
        frame = await asyncio.to_thread(gateway.recv_tool, device_id, call_id, 5)
        return frame

    async def _invoke(
        self,
        *,
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        ack: bool,
        stop_after_chunks: int | None,
    ) -> DispatchResult:
        chunks: list[tuple[int, str]] = []
        await self._send(
            gateway,
            device_id,
            {
                "type": "invoke",
                "device_id": device_id,
                "call_id": call_id,
                "attempt_id": attempt_id,
                "tool": tool,
                "args": args,
            },
        )
        while True:
            frame = await self._recv(gateway, device_id, call_id)
            kind = frame.get("type")
            if kind == "chunk":
                seq = int(frame["seq"])
                chunks.append((seq, str(frame.get("data") or "")))
                if stop_after_chunks is not None and len(chunks) >= stop_after_chunks:
                    return DispatchResult("unacked", None, chunks, False)
                await self._send(
                    gateway,
                    device_id,
                    {"type": "chunk_ack", "device_id": device_id, "call_id": call_id, "seq": seq},
                )
                continue
            if kind == "result":
                if not ack:
                    return DispatchResult("unacked", frame.get("result"), chunks, False)
                await self._send(
                    gateway,
                    device_id,
                    {"type": "ack", "device_id": device_id, "call_id": call_id, "subject": "result"},
                )
                return DispatchResult("completed", frame.get("result"), chunks, False)
            if kind == "status":
                return DispatchResult(str(frame.get("state")), None, chunks, False)

    async def _resume(
        self,
        *,
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        resume_from: int,
    ) -> DispatchResult:
        chunks: list[tuple[int, str]] = []
        seen: set[int] = set()
        await self._send(
            gateway,
            device_id,
            {
                "type": "status",
                "device_id": device_id,
                "call_id": call_id,
                "attempt_id": attempt_id,
                "resume_from": resume_from,
            },
        )
        while True:
            frame = await self._recv(gateway, device_id, call_id)
            kind = frame.get("type")
            if kind == "chunk":
                seq = int(frame["seq"])
                if seq in seen or seq <= resume_from:
                    continue
                seen.add(seq)
                chunks.append((seq, str(frame.get("data") or "")))
                await self._send(
                    gateway,
                    device_id,
                    {"type": "chunk_ack", "device_id": device_id, "call_id": call_id, "seq": seq},
                )
                continue
            if kind == "result":
                await self._send(
                    gateway,
                    device_id,
                    {"type": "ack", "device_id": device_id, "call_id": call_id, "subject": "result"},
                )
                return DispatchResult(
                    str(frame.get("state") or "completed"),
                    frame.get("result"),
                    chunks,
                    bool(frame.get("truncated")),
                )
            if kind == "status" and frame.get("state") == "recovery_required":
                continue
            if kind == "status":
                return DispatchResult(str(frame.get("state")), None, chunks, bool(frame.get("truncated")))

    async def _cancel(
        self,
        *,
        gateway: Any,
        device_id: str,
        call_id: str,
        attempt_id: str,
        tool: str,
        args: dict[str, Any],
        started: Any,
    ) -> DispatchResult:
        await self._send(
            gateway,
            device_id,
            {
                "type": "invoke",
                "device_id": device_id,
                "call_id": call_id,
                "attempt_id": attempt_id,
                "tool": tool,
                "args": args,
            },
        )
        found = await asyncio.to_thread(started.wait, 3)
        if not found:
            raise TimeoutError("tool did not start")
        await self._send(
            gateway,
            device_id,
            {"type": "cancel", "device_id": device_id, "call_id": call_id},
        )
        frame = await self._recv(gateway, device_id, call_id)
        return DispatchResult(str(frame.get("state")), frame.get("result"), [], False)


def dispatch_device_call(**kwargs: Any) -> DispatchResult:
    """Worker entry point. Cloud code calls this, not the socket class."""
    return RunnerClient().invoke(**kwargs)


def dispatch_device_resume(**kwargs: Any) -> DispatchResult:
    return RunnerClient().resume(**kwargs)


def dispatch_device_cancel(**kwargs: Any) -> DispatchResult:
    return RunnerClient().invoke_and_cancel(**kwargs)
