"""Startup latency: greetings must not wait on MCP or 'Analyzing' chrome."""

from __future__ import annotations

import inspect

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def _agent() -> AgentV2:
    return object.__new__(AgentV2)


def test_agent_init_does_not_block_on_mcp_connect():
    src = inspect.getsource(AgentV2.__init__)
    assert "_refresh_mcp_tools(force=True)" not in src


def test_run_does_not_await_mcp_on_user_turn():
    src = inspect.getsource(AgentV2.run)
    assert "asyncio.to_thread" not in src
    assert "_schedule_mcp_refresh" in src


def test_pure_greeting_skips_analyze_progress():
    agent = _agent()
    assert agent._should_emit_analyze_progress("你好") is False
    assert agent._should_emit_analyze_progress("hello") is False
    assert agent._should_emit_analyze_progress("帮我重构整个项目") is True


def test_pure_greeting_skips_mcp_refresh_on_turn():
    agent = _agent()
    assert agent._should_skip_mcp_refresh("你好") is True
    assert agent._should_skip_mcp_refresh("读取 src/main.py") is False
