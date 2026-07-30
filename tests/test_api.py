"""
Tests for the API server SSE endpoints.

Verifies:
1. /status endpoint returns model and cache info
2. /chat/stream endpoint produces SSE-formatted events
3. /command endpoint routes commands correctly
4. Error handling for missing model config
"""
import pytest
import json
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_agent():
    """Create a mock agent that returns predictable responses."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="Test response")
    agent._execute_tool = AsyncMock(return_value="[saved: memory #1]")
    agent.model_config = {"model_name": "test-model", "api_key": "test-key"}
    agent._memory = MagicMock()
    agent._memory.clear = MagicMock()
    agent._session_loaded = False
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._stream_mode = False
    agent._flush_thinking = MagicMock()
    agent.get_thinking_history = MagicMock(return_value="")
    return agent


@pytest.fixture
def client(mock_agent):
    """Create a FastAPI test client with mocked agent.

    The api_server uses a module-level ``_state`` dict (``_state["agent"]``)
    rather than a ``get_agent()`` function, so we patch ``_state`` directly.
    We also avoid importing the full app (which reconfigures ``sys.stdout``
    on Windows) and instead set up the minimum needed for testing.
    """
    from fastapi.testclient import TestClient
    from RxyCode.RxyCode1_1_0 import api_server

    # Save original state to restore after tests
    original_state = dict(api_server._state)
    # Inject the mock agent and a TUI proxy directly into _state
    api_server._state["agent"] = mock_agent
    api_server._state["tui_proxy"] = api_server.APIProxyTUI()
    api_server._state["busy"] = False
    api_server._state["chat_history"] = []
    api_server._state["mode"] = "build"

    token = api_server.configure_api_token()
    with TestClient(
        api_server.app,
        client=("127.0.0.1", 50000),
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c

    # Restore original state to prevent leaking into other tests
    api_server._state.clear()
    api_server._state.update(original_state)


class TestStatusEndpoint:
    def test_status_returns_ok(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data
        assert "mode" in data

    def test_status_includes_cache_info(self, client):
        resp = client.get("/status")
        data = resp.json()
        # Cache fields should exist (may be 0 if no calls made)
        assert "cache_size" in data
        assert set(data["application_cache"]) == {"precise", "semantic"}
        assert "provider_cache" in data

    def test_status_exposes_application_cache_counts_and_rates(self, client):
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        token_stats.record_application_cache("precise", hit=True)
        token_stats.record_application_cache("precise", hit=False)
        token_stats.record_application_cache("semantic", bypass=True)

        data = client.get("/status").json()

        assert data["application_cache"]["precise"]["hit_rate"] == 50.0
        assert data["application_cache"]["precise"]["eligible"] == 2
        assert data["application_cache"]["semantic"]["bypassed"] == 1
        assert data["application_cache"]["semantic"]["bypass_rate"] == 100.0
        token_stats.reset()

    def test_status_includes_run_monitor_snapshot(self, client):
        data = client.get("/status").json()
        assert "runs" in data
        assert "status_counts" in data["runs"]
        assert "average_duration_s" in data["runs"]


class TestChatStreamEndpoint:
    def test_chat_stream_returns_sse(self, client, mock_agent):
        """The /chat/stream endpoint should return SSE-formatted data."""
        resp = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )
        assert resp.status_code == 200
        # SSE responses have text/event-stream content type
        content_type = resp.headers.get("content-type", "")
        assert "event-stream" in content_type or "text/plain" in content_type

    def test_chat_stream_contains_done_event(self, client, mock_agent):
        """The stream must end with a 'done' event."""
        resp = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )
        body = resp.text
        assert "data:" in body  # SSE format
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
        done = next(event for event in events if event["type"] == "done")
        final = next(event for event in events if event["type"] == "final")
        assert done["status"] == "succeeded"
        assert done["run_id"] == final["run_id"]

    def test_agent_error_sentinel_is_not_reported_as_success(self, client, mock_agent):
        mock_agent.run.return_value = "[agent error: tool failed]"
        resp = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert not any(event["type"] == "final" for event in events)
        error = next(event for event in events if event["type"] == "error")
        done = next(event for event in events if event["type"] == "done")
        assert error["run_id"] == done["run_id"]
        assert done["status"] == "failed"

    def test_soft_budget_notice_is_reported_as_timeout(self, client, mock_agent):
        mock_agent.run.return_value = "[Build paused at ~30s] configured budget reached"
        resp = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert not any(event["type"] == "final" for event in events)
        done = next(event for event in events if event["type"] == "done")
        assert done["status"] == "timed_out"

    @pytest.mark.parametrize(
        ("result", "expected_status"),
        [
            ("[blocked: write path not allowed]", "failed"),
            ("[rejected by user: bash]", "failed"),
            ("[dry-run] bash was not executed", "failed"),
            ("[Build failed after ~4s] graph exploded", "failed"),
            ("Download failed: HTTP Error 404", "failed"),
            ("[search error: All engines failed or timed out]", "timed_out"),
            ("[cancelled]", "cancelled"),
        ],
    )
    def test_non_success_sentinels_update_sse_and_monitor(
        self, client, mock_agent, result, expected_status
    ):
        from RxyCode.RxyCode1_1_0.log.monitor import run_monitor

        run_monitor.reset()
        mock_agent.run.return_value = result

        resp = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )

        events = [
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        assert not any(event["type"] == "final" for event in events)
        error = next(event for event in events if event["type"] == "error")
        done = next(event for event in events if event["type"] == "done")
        assert error["status"] == expected_status
        assert done["status"] == expected_status

        runs = client.get("/status").json()["runs"]
        assert runs["total_runs"] == 1
        assert runs["status_counts"] == {expected_status: 1}
        assert runs["last_run"]["status"] == expected_status
        run_monitor.reset()

    def test_lifecycle_outer_exception_emits_error_then_done(self, client, mock_agent):
        """外层的 _api_run_lifecycle.run 若抛非取消异常（生命周期包装层或
        run_serialized 内层 try 之前的 setup 阶段逃逸），必须向前端发
        `error` 事件再发 `done`，绝不能静默关闭（0 事件、前端无可见失败原因）。"""
        from RxyCode.RxyCode1_1_0 import api_server

        async def boom(*_args, **_kwargs):
            raise RuntimeError("lifecycle exploded before agent.run")

        original_run = api_server._api_run_lifecycle.run
        api_server._api_run_lifecycle.run = boom
        try:
            resp = client.post(
                "/chat/stream",
                json={"message": "Hello", "mode": "build"},
            )
        finally:
            api_server._api_run_lifecycle.run = original_run

        events = [
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        error = next(event for event in events if event["type"] == "error")
        done = next(event for event in events if event["type"] == "done")
        assert error["status"] == "failed"
        assert "lifecycle exploded" in error["message"]
        assert done["status"] == "failed"
        assert error["run_id"] == done["run_id"]

    def test_sse_finally_upsert_preserves_agent_execution_metrics(
        self, client, mock_agent
    ):
        from RxyCode.RxyCode1_1_0.log.logger import get_current_run_id
        from RxyCode.RxyCode1_1_0.log.monitor import run_monitor

        async def run_with_metrics(*_args, **_kwargs):
            run_monitor.record(
                get_current_run_id(),
                "failed",
                1.0,
                metrics={
                    "steps": 5,
                    "replans": 1,
                    "failure_attribution": {"model_error": 1},
                    "token_usage": {"total_tokens": 21},
                },
            )
            return "[model unavailable] provider offline"

        run_monitor.reset()
        mock_agent.run.side_effect = run_with_metrics

        response = client.post(
            "/chat/stream",
            json={"message": "Hello", "mode": "build"},
        )

        done = next(
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and '"type": "done"' in line
        )
        assert done["status"] == "failed"
        runs = client.get("/status").json()["runs"]
        assert runs["total_runs"] == 1
        assert runs["average_steps"] == 5.0
        assert runs["average_replans"] == 1.0
        assert runs["failure_attribution"] == {"model_error": 1}
        assert runs["token_usage"]["total_tokens"] == 21
        run_monitor.reset()


class TestCommandEndpoint:
    def test_memory_mutation_uses_unified_explicit_command_gate(
        self, client, mock_agent
    ):
        response = client.post("/command", json={"command": "/memory add remember this"})

        assert response.json()["action"] == "memory_add"
        mock_agent._execute_tool.assert_awaited_once_with(
            "memory",
            {"operation": "add", "query": "remember this", "limit": 10},
            approval_source="explicit_command",
            mode="build",
        )

    def test_explicit_command_gets_an_isolated_audit_context(
        self, client, mock_agent
    ):
        from RxyCode.RxyCode1_1_0.log.logger import RUN_ID, get_current_run_id

        observed = []

        async def execute(*_args, **_kwargs):
            observed.append(get_current_run_id())
            return "[saved: memory #1]"

        mock_agent._execute_tool.side_effect = execute
        response = client.post(
            "/command", json={"command": "/memory add correlated"}
        )

        assert response.json()["action"] == "memory_add"
        assert len(observed) == 1
        assert observed[0] != RUN_ID
        assert get_current_run_id() == RUN_ID

    @pytest.mark.parametrize(
        ("command", "tool_name", "tool_args", "success_result", "action"),
        [
            (
                "/addskill coding-workflow",
                "download_skill",
                {"name": "coding-workflow", "operation": "install"},
                "Successfully installed skill 'coding-workflow'",
                "skill_installed",
            ),
            (
                "/remove-skill coding-workflow",
                "download_skill",
                {"name": "coding-workflow", "operation": "remove"},
                "Successfully removed skill 'coding-workflow'",
                "skill_removed",
            ),
            (
                "/addmcp files npx -y @mcp/files",
                "download_mcp",
                {
                    "name": "files",
                    "operation": "add",
                    "command": "npx",
                    "args": ["-y", "@mcp/files"],
                },
                "Successfully added MCP server 'files'",
                "mcp_added",
            ),
            (
                "/remove-mcp files",
                "download_mcp",
                {"name": "files", "operation": "remove"},
                "Successfully removed MCP server 'files'",
                "mcp_removed",
            ),
        ],
    )
    def test_management_mutations_use_unified_explicit_command_gate(
        self,
        client,
        mock_agent,
        command,
        tool_name,
        tool_args,
        success_result,
        action,
    ):
        mock_agent._execute_tool.return_value = success_result

        response = client.post("/command", json={"command": command})

        assert response.json()["action"] == action
        mock_agent._execute_tool.assert_awaited_once_with(
            tool_name,
            tool_args,
            approval_source="explicit_command",
            mode="build",
        )

    def test_management_gate_rejection_is_returned_as_error(self, client, mock_agent):
        mock_agent._execute_tool.return_value = (
            "[blocked: download_skill is not available in Plan mode]"
        )
        from RxyCode.RxyCode1_1_0 import api_server
        api_server._state["mode"] = "plan"

        response = client.post(
            "/command", json={"command": "/remove-skill coding-workflow"}
        )

        assert response.json()["action"] == "error"
        assert response.json()["message"].startswith("[blocked:")

    def test_cache_command_returns_structured_application_metrics(self, client):
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        token_stats.record_application_cache("precise", hit=True)
        token_stats.record_application_cache("semantic", bypass=True)

        payload = client.post("/command", json={"command": "/cache"}).json()

        assert payload["action"] == "cache_stats"
        assert payload["application_cache"]["precise"]["hit_rate"] == 100.0
        assert payload["application_cache"]["semantic"]["bypass_rate"] == 100.0
        assert "provider_cache" in payload
        assert "Eligible hit rate" in payload["message"]
        token_stats.reset()

    def test_clear_command(self, client):
        resp = client.post("/command", json={"command": "/clear"})
        assert resp.status_code == 200

    def test_unknown_command_returns_result(self, client):
        resp = client.post("/command", json={"command": "/nonexistent"})
        assert resp.status_code == 200

    def test_model_command(self, client):
        resp = client.post("/command", json={"command": "/models"})
        assert resp.status_code == 200

    def test_save_and_load_restores_complete_exact_history_and_agent_context(
        self, client, mock_agent
    ):
        from RxyCode.RxyCode1_1_0 import api_server

        messages = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"message {index}\n    indented  value  ",
            }
            for index in range(250)
        ]
        api_server._state["chat_history"] = messages.copy()

        saved = client.post("/command", json={"command": "/save-chat exact-250"})
        assert saved.json()["action"] == "chat_saved"
        api_server._state["chat_history"] = []

        loaded = client.post("/command", json={"command": "/load-chat exact-250"})
        payload = loaded.json()

        assert payload["action"] == "chat_loaded"
        assert payload["messages"] == messages
        assert api_server._state["chat_history"] == messages
        mock_agent._memory.clear.assert_called()
        mock_agent._memory.short_term.load_from_dicts.assert_called_once_with(messages)
        assert mock_agent._session_loaded is True

    def test_chat_endpoint_does_not_discard_messages_after_200(self, client):
        from RxyCode.RxyCode1_1_0 import api_server

        api_server._state["chat_history"] = [
            {"role": "user", "content": f"old-{index}"}
            for index in range(200)
        ]

        response = client.post(
            "/chat",
            json={"message": "new question", "mode": "build"},
        )

        assert response.status_code == 200
        assert len(api_server._state["chat_history"]) == 202
        assert api_server._state["chat_history"][0]["content"] == "old-0"
