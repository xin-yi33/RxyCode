"""Tool RPC frames. One device call runs once, and replies share the device writer."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from RxyCode.RxyCode1_1_0.execution.tool_journal import (
    RemoteJournalAdapter,
    ToolJournalError,
    remote_checkpoint_id,
    validate_attempt_id,
)

CHUNK_LIMIT = 4096
WINDOW = 2
_BOUND: dict[str, "ToolRpcServer"] = {}


def bind_local_tools(
    *,
    device_id: str,
    journal: RemoteJournalAdapter,
    execute: Callable[..., str],
) -> None:
    """Attach this device's journal and tool body to the outbound session."""
    _BOUND[device_id] = ToolRpcServer(device_id=device_id, journal=journal, execute=execute)


def clear_local_tools(device_id: str) -> None:
    _BOUND.pop(device_id, None)


def tool_rpc_for(device_id: str) -> "ToolRpcServer | None":
    return _BOUND.get(device_id)


_BASH_CALL = threading.local()


def bind_bash_call(call_id: str) -> None:
    """Remember which call this thread is asking the user to approve."""
    _BASH_CALL.call_id = call_id


def observe_approval(device_id: str, event: dict[str, Any]) -> None:
    """Bind the approval that this thread just published. Other calls stay put."""
    server = _BOUND.get(device_id)
    call_id = str(getattr(_BASH_CALL, "call_id", "") or "")
    if server is None or not call_id or str(event.get("tool") or "") != "bash":
        return
    server.bind_approval(call_id, str(event.get("approval_id") or ""))


class _CancelGate:
    """Refuse the shell body when the caller already gave up."""

    coroutine = None

    def __init__(self, cancel: threading.Event, inner: Any) -> None:
        self._cancel = cancel
        self._inner = inner
        self.name = getattr(inner, "name", "bash")
        self.description = getattr(inner, "description", "")
        self.args_schema = getattr(inner, "args_schema", None)

    def invoke(self, payload: Any) -> str:
        if self._cancel.is_set():
            raise RuntimeError("cancelled before execution")
        return self._inner.invoke(payload)


def _run_remote_full(args: dict[str, Any], *, tool: str, call_id: str) -> str:
    """Remote Full uses the local grant. A cloud permission string is not enough."""
    from rxycode_runner.local.grant_store import click_sender_for, store_for

    device_id = str(_DEVICE.get() or "")
    capability = "shell" if tool == "bash" else "click"
    allowed, reason = store_for(device_id).evaluate(
        {
            "permission": "full",
            "session_id": str(args.get("session_id") or ""),
            "run_id": str(args.get("run_id") or ""),
            "capability": capability,
            "workspace": str(args.get("workspace") or ""),
            "workdir": str(args.get("workdir") or args.get("workspace") or ""),
        }
    )
    if not allowed:
        raise RuntimeError(reason)
    if tool == "click":
        from rxycode_runner.desktop.capabilities import bind_task_capabilities
        from rxycode_runner.desktop.windows_adapter import Monitor, click

        sender = click_sender_for(device_id)
        if sender is None:
            raise RuntimeError("CLICK_SENDER_REQUIRED")
        monitor = args.get("monitor") if isinstance(args.get("monitor"), dict) else {}
        task_id = call_id or "remote-full"
        bind_task_capabilities(task_id, frozenset({"click"}))
        result = click(
            task_id=task_id,
            capabilities=frozenset({"click"}),
            monitors=(
                Monitor(
                    x=int(monitor.get("x") or 0),
                    y=int(monitor.get("y") or 0),
                    width=int(monitor.get("width") or 0),
                    height=int(monitor.get("height") or 0),
                    dpi=int(monitor.get("dpi") or 96),
                ),
            ),
            monitor_index=0,
            logical_x=int(args.get("logical_x") or 0),
            logical_y=int(args.get("logical_y") or 0),
            send=sender,
            system="Windows",
            locked=False,
            wayland=False,
        )
        if not result.ok:
            raise RuntimeError(result.code)
        return result.code
    command = str(args.get("command") or "")
    if not command:
        raise ValueError("bash command required")
    from RxyCode.RxyCode1_1_0.tools.bash import run_bash

    workdir = str(args.get("workdir") or "")
    raw_timeout = args.get("timeout", None)
    timeout = 1800 if raw_timeout is None else int(raw_timeout)
    outcome = run_bash(command, workdir=workdir, timeout=timeout)
    if outcome.startswith(("[error", "[rejected", "[blocked", "[sandbox")):
        raise RuntimeError(outcome)
    return outcome


def local_tool(
    args: dict[str, Any],
    *,
    cancel: threading.Event,
    tool: str = "write",
    call_id: str = "",
) -> str:
    """Run the named device tool. write appends text; bash runs the command string."""
    from rxycode_runner.remote.client import writer_count

    if writer_count(_DEVICE.get()) != 1:
        raise RuntimeError("tool replies must share one writer")
    if str(args.get("permission") or "") == "full" and tool in {"bash", "click"}:
        return _run_remote_full(args, tool=tool, call_id=call_id)
    if tool == "bash":
        command = str(args.get("command") or "")
        if not command:
            raise ValueError("bash command required")
        if cancel.is_set():
            raise RuntimeError("cancelled before execution")
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
        from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

        workdir = str(args.get("workdir") or "")
        raw_timeout = args.get("timeout", None)
        timeout = 1800 if raw_timeout is None else int(raw_timeout)
        orchestrator = ToolOrchestrator()
        orchestrator.register("bash", _CancelGate(cancel, bash_tool))

        async def _through_gate() -> str:
            return await orchestrator.execute_tool(
                "bash",
                {"command": command, "workdir": workdir, "timeout": timeout},
                {
                    "safety": {
                        "enabled": True,
                        "permission_mode": "confirm_all",
                        "auto_approve": [],
                        "dry_run": False,
                    }
                },
                call_id=call_id or None,
            )

        bind_bash_call(call_id)
        try:
            outcome = asyncio.run(_through_gate())
        finally:
            bind_bash_call("")
        if cancel.is_set():
            raise RuntimeError("cancelled before execution")
        if outcome.startswith(("[error", "[rejected", "[blocked")):
            raise RuntimeError(outcome)
        return outcome
    if tool != "write":
        raise RuntimeError(f"tool {tool} is not available on this device")
    if str(args.get("mode") or "") == "cancel":
        _CANCEL_STARTED.set()
        cancel.wait(3)
        return "stopped"
    path = args.get("path")
    if str(args.get("mode") or "") == "write" and isinstance(path, str):
        target = Path(path)
        previous = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(previous + "W", encoding="utf-8")
        return "W"
    if isinstance(path, str):
        target = Path(path)
        piece = str(args.get("text") if args.get("text") is not None else "once")
        previous = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(previous + piece, encoding="utf-8")
    body = args.get("body")
    if isinstance(body, str):
        return body
    if args.get("text") is not None:
        return str(args["text"])
    return "once"


_DEVICE: Any = __import__("contextvars").ContextVar("rxy_tool_device", default="")
_CANCEL_STARTED = threading.Event()


def cancel_started() -> threading.Event:
    _CANCEL_STARTED.clear()
    return _CANCEL_STARTED


def _split(text: str, limit: int) -> list[str]:
    """Pack whole characters so each piece is at most `limit` UTF-8 bytes."""
    if limit < 4:
        raise ValueError("chunk limit")
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for char in text:
        encoded = len(char.encode("utf-8"))
        if encoded > limit:
            raise ValueError("character exceeds chunk limit")
        if current and size + encoded > limit:
            parts.append("".join(current))
            current = []
            size = 0
        current.append(char)
        size += encoded
    if current:
        parts.append("".join(current))
    return parts


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
        self.approval_ids: dict[str, str] = {}
        self.chunk_acks: dict[str, int] = {}
        self.ack_events: dict[str, asyncio.Event] = {}
        self._performs: set[asyncio.Task[None]] = set()

    def cancel_performs(self) -> None:
        for task in list(self._performs):
            task.cancel()

    def bind_approval(self, call_id: str, approval_id: str) -> None:
        if call_id and approval_id:
            self.approval_ids[call_id] = approval_id

    def _reject_pending(self, call_id: str) -> None:
        approval_id = self.approval_ids.get(call_id) or ""
        if not approval_id:
            return
        from RxyCode.RxyCode1_1_0.core.safety.approval import get_approval_broker

        broker = get_approval_broker()
        if broker is not None:
            broker.resolve(approval_id, "rejected")

    def _journal_attempt(self, call_id: str) -> str:
        digest = hashlib.sha256(f"{self.device_id}:{call_id}".encode("utf-8")).hexdigest()
        return "att_" + digest[:32]

    def _checkpoint(self, call_id: str) -> str:
        return remote_checkpoint_id(f"{self.device_id}:{call_id}")

    async def on_frame(
        self,
        frame: dict[str, Any],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
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
            self._reject_pending(call_id)
            await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})

    async def _invoke(
        self,
        frame: dict[str, Any],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        call_id = str(frame.get("call_id") or "")
        tool = str(frame.get("tool") or "")
        args = frame.get("args") if isinstance(frame.get("args"), dict) else {}
        if frame.get("device_id") != self.device_id:
            await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
            return
        try:
            validate_attempt_id(str(frame.get("attempt_id") or ""))
            journal_attempt = self._journal_attempt(call_id)
            self.meta[call_id] = (journal_attempt, tool, args)
            reservation = self.journal.reserve(
                attempt_id=journal_attempt,
                call_id=call_id,
                tool=tool,
                args=args,
                checkpoint_id=self._checkpoint(call_id),
            )
        except (ToolJournalError, ValueError):
            await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
            return
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
        _DEVICE.set(self.device_id)
        try:
            result = await asyncio.to_thread(
                self.execute, args, cancel=cancel, tool=tool, call_id=call_id
            )
        except Exception as exc:
            if cancel.is_set():
                await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})
                return
            await queue.put(
                {
                    "type": "status",
                    "call_id": call_id,
                    "state": "recovery_required",
                    "result": str(exc),
                }
            )
            return
        if cancel.is_set():
            await queue.put({"type": "status", "call_id": call_id, "state": "cancelled"})
            return
        text = "" if result is None else str(result)
        self.results[call_id] = text
        parts = _split(text, CHUNK_LIMIT)
        self.buffers[call_id] = parts
        self.ack_events[call_id] = asyncio.Event()
        try:
            if len(text.encode("utf-8")) > CHUNK_LIMIT:
                for seq, data in enumerate(parts, start=1):
                    await self._wait_window(call_id, seq)
                    await queue.put(
                        {"type": "chunk", "call_id": call_id, "seq": seq, "data": data}
                    )
            await queue.put(
                {"type": "result", "call_id": call_id, "state": "completed", "result": text}
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
        self.journal.journal.mark_attempt_complete(attempt_id)

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
                checkpoint_id=self._checkpoint(call_id),
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
        self.chunk_acks[call_id] = max(self.chunk_acks.get(call_id, 0), resume_from)
        self.ack_events.setdefault(call_id, asyncio.Event()).set()
        await queue.put({"type": "status", "call_id": call_id, "state": "recovery_required"})
        for seq, data in enumerate(self.buffers.get(call_id, []), start=1):
            if seq <= resume_from:
                continue
            await self._wait_window(call_id, seq)
            await queue.put(
                {"type": "chunk", "call_id": call_id, "seq": seq, "data": data, "replay": True}
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
