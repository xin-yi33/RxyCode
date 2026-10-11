"""Slow model RPCs must not hold the stdin loop shut.

A discover, connection test, or session model switch used to be awaited
inside ``AppServer.run`` before the next line was read. Interrupt and
approval replies already sitting on stdin could not enter processing.
Same-session prompt/model/state changes stay in arrival order.
"""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
from typing import Any

import pytest

from appserver.server import AppServer


def _line(payload: dict[str, Any]) -> str:
    return json.dumps(payload) + "\n"


def _install_stdin(monkeypatch: pytest.MonkeyPatch) -> queue.Queue[str]:
    lines: queue.Queue[str] = queue.Queue()

    def readline() -> str:
        return lines.get()

    monkeypatch.setattr(sys.stdin, "readline", readline)
    return lines


def _server(monkeypatch: pytest.MonkeyPatch) -> tuple[AppServer, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    async def capture(message: dict[str, Any]) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True

    async def _no_heartbeat() -> None:
        return None

    server._heartbeat_loop = _no_heartbeat  # type: ignore[method-assign]
    return server, sent


async def _stop(server_task: asyncio.Task[Any], lines: queue.Queue[str], release: asyncio.Event) -> None:
    release.set()
    lines.put("")
    server_task.cancel()
    with __import__("contextlib").suppress(asyncio.CancelledError):
        await server_task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("models/discover", "appserver.model_routes.discover"),
        ("models/test_connection", "appserver.model_routes.test_connection"),
    ],
)
async def test_slow_discover_lets_interrupt_and_approval_reply_in(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    target: str,
) -> None:
    """Discover or a connection test stays in flight while control messages run."""
    server, sent = _server(monkeypatch)
    lines = _install_stdin(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()
    interrupt_entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    approval: asyncio.Future[dict[str, Any]] = loop.create_future()
    server._pending_server[42] = approval

    async def slow_rpc(params: dict[str, Any]) -> dict[str, Any]:
        del params
        started.set()
        await release.wait()
        return {"ok": True, "models": []}

    monkeypatch.setattr(target, slow_rpc)

    async def wrapped_interrupt(params: dict[str, Any], request_id: Any) -> None:
        del params
        interrupt_entered.set()
        await server._respond(request_id, {"cancelled": True, "session_id": "s-a"})

    server._handle_interrupt = wrapped_interrupt  # type: ignore[method-assign]

    task = asyncio.create_task(server.run())
    try:
        lines.put(_line({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}))
        await asyncio.wait_for(started.wait(), timeout=2)
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/interrupt",
                    "params": {"session_id": "s-a"},
                }
            )
        )
        lines.put(
            _line({"jsonrpc": "2.0", "id": 42, "result": {"decision": "allow"}})
        )
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "approval/decide",
                    "params": {},
                }
            )
        )
        await asyncio.wait_for(interrupt_entered.wait(), timeout=0.5)
        await asyncio.wait_for(approval, timeout=0.5)
        assert approval.result()["decision"] == "allow"

        async def _decide_seen() -> None:
            while not any(item.get("id") == 3 for item in sent):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_decide_seen(), timeout=0.5)
        assert not release.is_set()
    finally:
        await _stop(task, lines, release)


@pytest.mark.asyncio
async def test_slow_set_active_does_not_block_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """models/set_active writes config off the reader; interrupt still enters."""
    server, _sent = _server(monkeypatch)
    lines = _install_stdin(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    interrupt_entered = asyncio.Event()

    def slow_set_active(params: dict[str, Any]) -> dict[str, Any]:
        started.set()
        release.wait()
        return {"ok": True, "id": params.get("id")}

    monkeypatch.setattr("appserver.model_routes.set_active", slow_set_active)

    async def wrapped_interrupt(params: dict[str, Any], request_id: Any) -> None:
        del params
        interrupt_entered.set()
        await server._respond(request_id, {"cancelled": True})

    server._handle_interrupt = wrapped_interrupt  # type: ignore[method-assign]
    task = asyncio.create_task(server.run())
    try:
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "models/set_active",
                    "params": {"id": "new/model"},
                }
            )
        )

        async def _started() -> None:
            while not started.is_set():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_started(), timeout=2)
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/interrupt",
                    "params": {"session_id": "s-a"},
                }
            )
        )
        await asyncio.wait_for(interrupt_entered.wait(), timeout=0.5)
        assert not release.is_set()
    finally:
        release.set()
        lines.put("")
        task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_slow_switch_keeps_same_session_order_and_accepts_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later prompt on the same session waits; interrupt and another session do not."""
    server, _sent = _server(monkeypatch)
    lines = _install_stdin(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()
    interrupt_entered = asyncio.Event()
    order: list[str] = []

    async def slow_set_model(params: dict[str, Any], request_id: Any) -> None:
        order.append(f"set:{params.get('session_id')}")
        started.set()
        await release.wait()
        order.append(f"set-done:{params.get('session_id')}")
        await server._respond(request_id, {"ok": True})

    async def record_prompt(params: dict[str, Any], request_id: Any) -> None:
        order.append(f"prompt:{params.get('session_id')}")
        await server._respond(request_id, {"ok": True})

    async def wrapped_interrupt(params: dict[str, Any], request_id: Any) -> None:
        del params
        order.append("interrupt")
        interrupt_entered.set()
        await server._respond(request_id, {"cancelled": True})

    server._handle_session_set_model = slow_set_model  # type: ignore[method-assign]
    server._handle_prompt = record_prompt  # type: ignore[method-assign]
    server._handle_interrupt = wrapped_interrupt  # type: ignore[method-assign]

    task = asyncio.create_task(server.run())
    try:
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "session/set_model",
                    "params": {"session_id": "s-a", "model_id": "new"},
                }
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/prompt",
                    "params": {"session_id": "s-a", "text": "later"},
                }
            )
        )
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {"session_id": "s-b", "text": "other"},
                }
            )
        )
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "session/interrupt",
                    "params": {"session_id": "s-a"},
                }
            )
        )
        await asyncio.wait_for(interrupt_entered.wait(), timeout=0.5)

        async def _other_prompt() -> None:
            while "prompt:s-b" not in order:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_other_prompt(), timeout=0.5)
        assert "prompt:s-a" not in order
        release.set()

        async def _same_prompt_after_switch() -> None:
            while "prompt:s-a" not in order:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_same_prompt_after_switch(), timeout=2)
        assert order.index("set-done:s-a") < order.index("prompt:s-a")
    finally:
        await _stop(task, lines, release)


@pytest.mark.asyncio
async def test_set_model_waits_for_the_set_active_that_arrived_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """session/set_model must observe an earlier models/set_active write."""
    server, _sent = _server(monkeypatch)
    lines = _install_stdin(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def slow_set_active(params: dict[str, Any]) -> dict[str, Any]:
        order.append("active")
        started.set()
        release.wait()
        order.append("active-done")
        return {"ok": True, "id": params.get("id")}

    async def record_set_model(params: dict[str, Any], request_id: Any) -> None:
        order.append(f"set:{params.get('model_id')}")
        await server._respond(request_id, {"ok": True})

    monkeypatch.setattr("appserver.model_routes.set_active", slow_set_active)
    server._handle_session_set_model = record_set_model  # type: ignore[method-assign]
    task = asyncio.create_task(server.run())
    try:
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "models/set_active",
                    "params": {"id": "new/model"},
                }
            )
        )

        async def _started() -> None:
            while not started.is_set():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_started(), timeout=2)
        lines.put(
            _line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/set_model",
                    "params": {"session_id": "s-a", "model_id": "new/model"},
                }
            )
        )
        await asyncio.sleep(0.15)
        assert order == ["active"]
        release.set()

        async def _switched() -> None:
            while "set:new/model" not in order:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_switched(), timeout=2)
        assert order.index("active-done") < order.index("set:new/model")
    finally:
        release.set()
        lines.put("")
        task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_slow_rpcs_are_bounded_and_shutdown_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At most a few discovers run at once, and EOF still finishes the server."""
    monkeypatch.setattr("appserver.server._SHUTDOWN_PROMPT_WAIT_SECONDS", 0.2)
    server, _sent = _server(monkeypatch)
    lines = _install_stdin(monkeypatch)
    entered = 0
    peak = 0
    release = asyncio.Event()

    async def slow_discover(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal entered, peak
        del params
        entered += 1
        peak = max(peak, entered)
        try:
            await release.wait()
        finally:
            entered -= 1
        return {"ok": True, "models": []}

    monkeypatch.setattr("appserver.model_routes.discover", slow_discover)
    task = asyncio.create_task(server.run())
    try:
        for request_id in range(1, 7):
            lines.put(
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "models/discover",
                        "params": {},
                    }
                )
            )
        await asyncio.sleep(0.3)
        assert peak <= 4
        assert peak >= 1
        lines.put("")
        await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        if not task.done():
            lines.put("")
            task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await task
