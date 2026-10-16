"""Outbound device websocket. This process does not listen for a public port."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
from typing import Any
from urllib.parse import urlparse

import websockets

logger = logging.getLogger(__name__)
_TOOL_FRAMES = {"invoke", "ack", "chunk_ack", "status", "cancel"}

_STOP = threading.Event()
_LOCK = threading.Lock()
_TOKENS: dict[str, str] = {}
_WRITERS: dict[str, set[int]] = {}
_PROTOCOL = "1.1.0"
_SCOPE = "device"


class ConnectRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Closed:
    failed = False


def request_stop() -> None:
    _STOP.set()


def reset_stop() -> None:
    _STOP.clear()


def token_for(device_id: str) -> str:
    with _LOCK:
        return _TOKENS.get(device_id, "")


def writer_count(device_id: str) -> int:
    with _LOCK:
        return len(_WRITERS.get(device_id, ()))


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def require_outbound_tls(url: str) -> None:
    """Only loopback may use ws://. Any other host must be wss://."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme == "wss":
        return
    if parsed.scheme == "ws" and host in _LOOPBACK:
        return
    raise ConnectRejected("TLS_REQUIRED")


def tls_context_for(url: str) -> ssl.SSLContext | None:
    """WSS keeps the default certificate check. Verification is not turned off."""
    require_outbound_tls(url)
    if not url.startswith("wss://"):
        return None
    return ssl.create_default_context()


def run_connect(
    *,
    url: str,
    device_id: str,
    os_name: str,
    capabilities: list[str],
    pairing_code: str = "",
    token: str = "",
    protocol_version: str = _PROTOCOL,
    heartbeat_seconds: float = 15.0,
) -> None:
    require_outbound_tls(url)
    _ensure_local_tools(device_id)
    asyncio.run(
        _connect(
            url=url,
            device_id=device_id,
            os_name=os_name,
            capabilities=list(capabilities),
            pairing_code=pairing_code,
            token=token,
            protocol_version=protocol_version,
            heartbeat_seconds=heartbeat_seconds,
        )
    )


async def _connect(
    *,
    url: str,
    device_id: str,
    os_name: str,
    capabilities: list[str],
    pairing_code: str,
    token: str,
    protocol_version: str,
    heartbeat_seconds: float,
) -> None:
    state = {"token": token, "scope": _SCOPE}
    while not _STOP.is_set():
        try:
            outcome, reason = await _one_session(
                url=url,
                device_id=device_id,
                os_name=os_name,
                capabilities=capabilities,
                pairing_code=pairing_code,
                protocol_version=protocol_version,
                heartbeat_seconds=heartbeat_seconds,
                state=state,
            )
        except Exception as exc:
            logger.info("device socket closed", extra={"device_id": device_id})
            if not state["token"]:
                raise ConnectRejected("DISCONNECTED") from exc
            await asyncio.sleep(0.05)
            continue
        if outcome == "stop":
            return
        if outcome == "rejected":
            raise ConnectRejected(reason)
        if not state["token"]:
            raise ConnectRejected(reason or "DISCONNECTED")
        await asyncio.sleep(0.05)


async def _one_session(
    *,
    url: str,
    device_id: str,
    os_name: str,
    capabilities: list[str],
    pairing_code: str,
    protocol_version: str,
    heartbeat_seconds: float,
    state: dict[str, str],
) -> tuple[str, str]:
    context = tls_context_for(url)
    async with websockets.connect(url, ssl=context) as ws:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        failed = _Closed()
        writer = asyncio.create_task(_write(ws, queue, device_id, failed))
        reader: asyncio.Task[None] | None = None
        try:
            hello: dict[str, Any] = {
                "type": "hello",
                "device_id": device_id,
                "os": os_name,
                "capabilities": capabilities,
                "protocol_version": protocol_version,
                "scope": state["scope"],
            }
            if state["token"]:
                hello["token"] = state["token"]
            else:
                hello["pairing_code"] = pairing_code
            await queue.put(hello)
            raw = await ws.recv()
            first = json.loads(raw)
            if first.get("type") != "hello_ok":
                return "rejected", str(first.get("code") or "REJECTED")
            granted = str(first.get("scope") or "")
            if state["token"] and granted != state["scope"]:
                return "rejected", "SCOPE_UPGRADE"
            if first.get("tool_permission") is not True:
                return "rejected", "NO_TOOL"
            state["scope"] = granted
            state["token"] = str(first["token"])
            with _LOCK:
                _TOKENS[device_id] = state["token"]
            logger.info("device session ready", extra={"device_id": device_id})
            session_id = str(first["session_id"])
            reader = asyncio.create_task(
                _read_downstream(ws, device_id, queue, failed)
            )
            elapsed = heartbeat_seconds
            while not _STOP.is_set():
                if failed.failed:
                    return "lost", "DISCONNECTED"
                if elapsed >= heartbeat_seconds:
                    await queue.put({"type": "heartbeat", "session_id": session_id})
                    elapsed = 0.0
                await asyncio.sleep(0.05)
                elapsed += 0.05
            return "stop", ""
        finally:
            if reader is not None:
                reader.cancel()
            rpc = _tool_rpc(device_id)
            if rpc is not None:
                rpc.cancel_performs()
            await queue.put(None)
            try:
                await writer
            except Exception:
                logger.info("device writer closed", extra={"device_id": device_id})


def _ensure_local_tools(device_id: str) -> None:
    from pathlib import Path
    from tempfile import mkdtemp

    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.transport.tool_rpc import bind_local_tools, local_tool, tool_rpc_for

    if tool_rpc_for(device_id) is not None:
        return
    directory = Path(mkdtemp(prefix="rxycode-tool-rpc-"))
    bind_local_tools(
        device_id=device_id,
        journal=RemoteJournalAdapter(ToolExecutionJournal(directory)),
        execute=local_tool,
    )


def _tool_rpc(device_id: str) -> Any:
    from rxycode_runner.transport.tool_rpc import tool_rpc_for

    return tool_rpc_for(device_id)


async def _read_downstream(
    ws: Any,
    device_id: str,
    queue: asyncio.Queue[dict[str, Any] | None],
    failed: _Closed,
) -> None:
    try:
        while True:
            frame = json.loads(await ws.recv())
            if not isinstance(frame, dict) or frame.get("type") not in _TOOL_FRAMES:
                continue
            rpc = _tool_rpc(device_id)
            if rpc is not None:
                await rpc.on_frame(frame, queue)
    except asyncio.CancelledError:
        raise
    except Exception:
        failed.failed = True


async def _write(
    ws: Any,
    queue: asyncio.Queue[dict[str, Any] | None],
    device_id: str,
    failed: _Closed,
) -> None:
    task = asyncio.current_task()
    task_id = id(task)
    with _LOCK:
        _WRITERS.setdefault(device_id, set()).add(task_id)
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            await ws.send(json.dumps(item))
    except Exception:
        failed.failed = True
    finally:
        with _LOCK:
            _WRITERS.get(device_id, set()).discard(task_id)
