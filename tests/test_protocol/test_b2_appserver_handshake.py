"""PhaseG-B2 appserver initialize behavior."""

from __future__ import annotations

import pytest

from appserver.server import AppServer
from protocol.version import PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_initialize_1_0_and_1_1_succeed(monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server._handle_initialize(
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
        1,
    )
    assert server._initialized is True
    result = next(item["result"] for item in sent if "result" in item)
    assert result["protocol_version"] == PROTOCOL_VERSION
    assert result["capabilities"]["sessions"] is True
    assert result["capability_snapshot"]["thread_fork"] is False
    assert result["capability_snapshot"]["review"] is False
    assert "model_providers" in result
    assert {row["profile_id"] for row in result["permission_profiles"]} >= {
        "confirm_all",
        "auto_edit",
        "full_auto",
    }
    note = next(item for item in sent if item.get("method") == "initialized")
    assert note["params"]["protocol_version"] == PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_incompatible_version_is_rejected(monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server._handle_initialize(
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "2.0.0",
        },
        2,
    )
    assert server._initialized is False
    error = sent[0]["error"]
    assert error["code"] == -32006
    assert error["data"]["error_code"] == "PROTOCOL_MISMATCH"
    assert error["data"]["retryable"] is False


@pytest.mark.asyncio
async def test_not_initialized_and_unknown_method_have_stable_codes(monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "session/new", "params": {}}
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["code"] == -32002
    assert err["data"]["error_code"] == "NOT_INITIALIZED"
    assert err["data"]["retryable"] is False

    sent.clear()
    server._initialized = True
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "no/such", "params": {}}
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["code"] == -32601
    assert err["data"]["error_code"] == "UNSUPPORTED"
    assert err["data"]["retryable"] is False


@pytest.mark.asyncio
async def test_configuration_closed_and_overloaded(monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server._handle_initialize({"protocol_version": "1.1.0"}, 10)
    err = sent[0]["error"]
    assert err["data"]["error_code"] == "CONFIGURATION_MISSING"
    assert err["data"]["retryable"] is False

    sent.clear()
    server._shutdown = True
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "session/new",
            "params": {"workspace_root": "."},
        }
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "CLOSED"
    assert err["data"]["retryable"] is True

    sent.clear()
    server._shutdown = False
    server._initialized = True
    server._prompt_tasks = {object() for _ in range(256)}  # type: ignore[misc]
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "session/prompt",
            "params": {"session_id": "x", "text": "hi"},
        }
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "OVERLOADED"
    assert err["data"]["retryable"] is True

    sent.clear()
    await server._respond_error(13, -32004, "job stalled")
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "TIMEOUT"
    assert err["data"]["retryable"] is True
