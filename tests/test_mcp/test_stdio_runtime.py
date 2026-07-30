"""Real subprocess coverage for the MCP stdio lifecycle and Agent hot reload."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


FAKE_SERVER = r'''
import json
import os
import sys
import time

log_path = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "normal"

def emit(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()

for raw_line in sys.stdin:
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(raw_line)
        log.flush()
    message = json.loads(raw_line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        if mode == "hang_init":
            continue
        version = "2099-01-01" if mode == "bad_version" else "2025-11-25"
        emit({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "fake", "version": "1"},
            },
        })
    elif method == "tools/list":
        annotations = (
            {"destructiveHint": True, "readOnlyHint": True}
            if mode == "danger"
            else {}
        )
        emit({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo one string",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "delay": {"type": "number", "minimum": 0},
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "annotations": annotations,
                }],
            },
        })
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments", {})
        time.sleep(float(arguments.get("delay", 0)))
        text = arguments.get("text", "")
        if text == "env-check":
            text = (
                "implicit_missing="
                + str(os.environ.get("MCP_SHOULD_NOT_INHERIT") is None)
                + ";explicit="
                + str(os.environ.get("MCP_EXPLICIT", ""))
            )
        emit({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": "echo:" + text}],
                "structuredContent": {"echo": text},
                "isError": False,
            },
        })
'''


@pytest.fixture
def fake_server(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "fake_mcp_server.py"
    log = tmp_path / "mcp-wire.jsonl"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return script, log


def _messages(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_stdio_client_real_initialize_list_call_and_schema_validation(fake_server):
    from RxyCode.RxyCode1_1_0.mcp.client import (
        CURRENT_PROTOCOL_VERSION,
        MCPClient,
    )

    script, log = fake_server
    client = MCPClient(
        "fixture",
        sys.executable,
        [str(script), str(log)],
        timeout=1,
    )
    assert client.connect() is True
    process = client._process
    try:
        assert client.connected is True
        assert client.protocol_version == CURRENT_PROTOCOL_VERSION
        tools = client.get_tools()
        assert [(tool.name, tool.remote_name) for tool in tools] == [
            ("mcp_fixture_echo", "echo")
        ]

        result = client.call_tool("echo", {"text": "hello"})
        assert "echo:hello" in result
        assert '"echo": "hello"' in result

        call_count = sum(
            message.get("method") == "tools/call" for message in _messages(log)
        )
        rejected = client.call_tool("echo", {"delay": 0})
        assert rejected.startswith("[error: MCP arguments failed schema validation")
        assert sum(
            message.get("method") == "tools/call" for message in _messages(log)
        ) == call_count

        wire = log.read_text(encoding="utf-8")
        assert "Content-Length:" not in wire
        assert _messages(log)[0]["method"] == "initialize"
        assert any(
            message.get("method") == "notifications/initialized"
            for message in _messages(log)
        )
    finally:
        client.disconnect()
    assert process is not None and process.poll() is not None
    assert client.connected is False


def test_stdio_client_tool_timeout_is_real_and_bounded(fake_server):
    from RxyCode.RxyCode1_1_0.mcp.client import MCPClient

    script, log = fake_server
    client = MCPClient(
        "slow",
        sys.executable,
        [str(script), str(log)],
        timeout=0.1,
    )
    assert client.connect() is True
    try:
        result = client.call_tool("echo", {"text": "late", "delay": 0.5})
        assert result == "[error: MCP MCPTimeoutError]"
        assert client.connected is True
    finally:
        client.disconnect()


def test_stdio_client_rejects_unsupported_negotiated_version(fake_server):
    from RxyCode.RxyCode1_1_0.mcp.client import MCPClient

    script, log = fake_server
    client = MCPClient(
        "future",
        sys.executable,
        [str(script), str(log), "bad_version"],
        timeout=1,
    )
    assert client.connect() is False
    assert client.connected is False
    assert client.last_error_type == "MCPError"


def test_stdio_client_inherits_only_safe_environment_plus_explicit_values(
    fake_server, monkeypatch
):
    from RxyCode.RxyCode1_1_0.mcp.client import MCPClient

    script, log = fake_server
    monkeypatch.setenv("MCP_SHOULD_NOT_INHERIT", "host-only-secret")
    client = MCPClient(
        "environment",
        sys.executable,
        [str(script), str(log)],
        env={"MCP_EXPLICIT": "configured"},
        timeout=1,
    )
    assert client.connect() is True
    try:
        result = client.call_tool("echo", {"text": "env-check"})
        assert "implicit_missing=True;explicit=configured" in result
        assert "host-only-secret" not in result
    finally:
        client.disconnect()


@pytest.mark.asyncio
async def test_async_mcp_tool_cancellation_unwinds_the_client_wait(fake_server):
    from RxyCode.RxyCode1_1_0.mcp.client import load_mcp_servers

    script, log = fake_server
    loaded = load_mcp_servers(
        {
            "cancel": {
                "command": sys.executable,
                "args": [str(script), str(log)],
                "timeout": 5,
            }
        }
    )
    assert not loaded.errors
    tool = loaded.tools["mcp_cancel_echo"]
    task = asyncio.create_task(tool.ainvoke({"text": "late", "delay": 1}))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
    finally:
        for client in loaded.clients.values():
            client.disconnect()


def _bare_agent():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = AgentV2.__new__(AgentV2)
    agent._cfg = {
        "execution": {"max_tool_rounds": 4},
        "context": {},
    }
    agent._session_id = "latest"
    agent._tool_orchestrator = ToolOrchestrator()
    agent._mcp_lock = threading.RLock()
    agent._mcp_clients = {}
    agent._mcp_tool_names = set()
    agent._mcp_server_tool_names = {}
    agent._mcp_server_fingerprints = {}
    agent._mcp_errors = {}
    agent._mcp_retry_state = {}
    agent._mcp_config_fingerprint = None
    agent._mcp_runtime = {
        "configured_servers": 0,
        "connected_servers": 0,
        "tools": 0,
        "error_count": 0,
        "error_types": [],
        "backoff_servers": 0,
        "next_retry_seconds": 0,
        "process_isolation": "host_process",
        "environment": "safe_allowlist_plus_explicit",
    }
    agent._checkpoint_store = None
    agent._rate_limiter = None
    async def compress_if_needed(_session_id: str):
        return None

    agent._memory = SimpleNamespace(
        _rag_enabled=False,
        load_session=lambda: None,
        get_context_for_prompt=lambda _query="": "",
        add_interaction=lambda *_args: None,
        save_session=lambda: None,
        compress_if_needed=compress_if_needed,
        rag_cache_status=lambda: {"enabled": False},
    )
    agent._session_loaded = True
    agent.model_config = {
        "base_url": "https://example.invalid/v1",
        "model_name": "scripted",
        "api_key": "",
    }
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._side_effecting_tool_attempted = False
    agent._rag_indexer_thread = None
    agent._model_router = SimpleNamespace(configured_roles=[])
    agent._last_hook_audit = []

    async def observed(user_input: str, mode: str, run_id: str) -> str:
        return f"{mode}:{user_input}:{bool(run_id)}"

    agent._run_observed = observed
    return agent


@pytest.mark.asyncio
async def test_agent_next_run_hot_loads_executes_and_unloads_downloaded_mcp(
    fake_server,
):
    from RxyCode.RxyCode1_1_0.core.safety.policy import (
        RiskLevel,
        classify_tool_risk,
    )
    from RxyCode.RxyCode1_1_0.tools.download_tool import download_mcp
    from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config

    script, log = fake_server
    agent = _bare_agent()
    config = load_config()
    config["mcpServers"] = {}
    config["safety"] = {"enabled": True, "auto_approve": ["write"]}
    save_config(config)
    added = download_mcp(
        "hot",
        operation="add",
        command=sys.executable,
        args=[str(script), str(log)],
    )
    assert added.startswith("Successfully added MCP server")

    assert await agent.run("first", mode="build") == "build:first:True"
    tool_name = "mcp_hot_echo"
    assert agent._tool_orchestrator.get(tool_name) is not None
    assert classify_tool_risk(tool_name) is RiskLevel.WRITE
    first_client = agent._mcp_clients["hot"]

    result = await agent._tool_orchestrator.execute_tool(
        tool_name,
        {"text": "through-gate"},
        config={
            "safety": {"enabled": True, "auto_approve": ["write"]},
            "execution": {"tool_timeout_seconds": 2},
        },
    )
    assert "echo:through-gate" in result

    # Exercise the production simple-query route, not just the adapter in
    # isolation: the model sees the hot-loaded tool and its tool call resolves
    # through AgentV2._execute_tool -> ToolOrchestrator -> MCPClient.
    bound_names: list[list[str]] = []
    rounds = 0

    async def scripted_stream(messages, tools=None):
        nonlocal rounds
        rounds += 1
        bound_names.append([tool.name for tool in (tools or [])])
        if rounds == 1:
            call = SimpleNamespace(
                index=0,
                id="mcp-call-1",
                function=SimpleNamespace(
                    name=tool_name,
                    arguments='{"text":"from-model"}',
                ),
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="", reasoning_content="", tool_calls=[call]
                        )
                    )
                ],
                usage=None,
            )
        else:
            assert any(
                "echo:from-model" in str(getattr(message, "content", ""))
                for message in messages
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="model complete",
                            reasoning_content="",
                            tool_calls=None,
                        )
                    )
                ],
                usage=None,
            )

    agent._raw_stream = scripted_stream
    fast_result = await agent._fast_reply_with_tools(
        "Use the MCP echo tool", mode="build"
    )
    assert fast_result == "model complete"
    assert all(tool_name in names for names in bound_names)
    assert any(
        message.get("method") == "tools/call"
        and message.get("params", {}).get("arguments", {}).get("text")
        == "from-model"
        for message in _messages(log)
    )

    # An unchanged next run reuses the live session rather than leaking a new
    # subprocess, but a disconnected session is rebuilt on the following run.
    await agent.run("second", mode="build")
    assert agent._mcp_clients["hot"] is first_client
    first_client.disconnect()
    await agent.run("third", mode="build")
    assert agent._mcp_clients["hot"] is not first_client

    status = agent.runtime_status()["mcp"]
    assert status == {
        "configured_servers": 1,
        "connected_servers": 1,
        "tools": 1,
        "error_count": 0,
        "error_types": [],
        "backoff_servers": 0,
        "next_retry_seconds": 0,
        "process_isolation": "host_process",
        "environment": "safe_allowlist_plus_explicit",
    }
    assert "command" not in status
    assert "env" not in status

    removed = download_mcp("hot", operation="remove")
    assert removed.startswith("Successfully removed MCP server")
    active_client = agent._mcp_clients["hot"]
    await agent.run("after-remove", mode="build")
    assert agent._tool_orchestrator.get(tool_name) is None
    assert tool_name not in [tool.name for tool in agent._get_core_tools()]
    assert active_client.connected is False
    assert agent.runtime_status()["mcp"]["tools"] == 0
    agent.close_mcp()


@pytest.mark.asyncio
async def test_agent_escalates_destructive_mcp_annotation_to_danger(
    fake_server,
):
    from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config
    from RxyCode.RxyCode1_1_0.tools.download_tool import download_mcp

    script, log = fake_server
    config = load_config()
    config["mcpServers"] = {}
    config["safety"] = {"enabled": True, "auto_approve": ["write"]}
    save_config(config)
    download_mcp(
        "danger",
        operation="add",
        command=sys.executable,
        args=[str(script), str(log), "danger"],
    )

    agent = _bare_agent()
    assert agent._refresh_mcp_tools(force=True) is True
    tool_name = "mcp_danger_echo"
    assert agent._tool_orchestrator.get(tool_name) is not None

    before = sum(
        message.get("method") == "tools/call" for message in _messages(log)
    )
    rejected = await agent._execute_tool(tool_name, {"text": "blocked"})
    assert "rejected" in rejected.lower() or "approval" in rejected.lower()
    assert sum(
        message.get("method") == "tools/call" for message in _messages(log)
    ) == before

    config = load_config()
    config["safety"] = {"enabled": True, "auto_approve": ["danger"]}
    save_config(config)
    allowed = await agent._execute_tool(tool_name, {"text": "approved"})
    assert "echo:approved" in allowed
    agent.close_mcp()
    download_mcp("danger", operation="remove")


@pytest.mark.asyncio
async def test_mcp_failure_backoff_preserves_healthy_server(fake_server):
    from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config

    script, healthy_log = fake_server
    bad_log = healthy_log.with_name("bad-wire.jsonl")
    config = load_config()
    config["mcpServers"] = {
        "healthy": {
            "command": sys.executable,
            "args": [str(script), str(healthy_log)],
            "timeout": 1,
        },
        "offline": {
            "command": sys.executable,
            "args": [str(script), str(bad_log), "hang_init"],
            "timeout": 0.5,
        },
    }
    save_config(config)

    agent = _bare_agent()
    assert agent._refresh_mcp_tools(force=True) is True
    healthy_client = agent._mcp_clients["healthy"]
    initial_healthy_messages = len(_messages(healthy_log))
    initial_bad_messages = len(_messages(bad_log))
    assert initial_bad_messages >= 1

    started = time.perf_counter()
    assert agent._refresh_mcp_tools() is False
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25
    assert agent._mcp_clients["healthy"] is healthy_client
    assert len(_messages(healthy_log)) == initial_healthy_messages
    assert len(_messages(bad_log)) == initial_bad_messages
    status = agent.runtime_status()["mcp"]
    assert status["connected_servers"] == 1
    assert status["error_count"] == 1
    assert status["backoff_servers"] == 1
    assert status["next_retry_seconds"] >= 1
    agent.close_mcp()


def test_orchestrator_unregister_removes_dynamic_tool():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orchestrator = ToolOrchestrator()
    marker = object()
    orchestrator.register("dynamic", marker)
    assert orchestrator.unregister("dynamic") is True
    assert orchestrator.unregister("dynamic") is False
    assert orchestrator.get("dynamic") is None
