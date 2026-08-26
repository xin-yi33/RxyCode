"""FX3 · ChatPrefix skip_await (PHASE-FIX §5 FX3).

Greeting turns must not pay memory.initialize / session.load before the
first model token; encoding paths still load history.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

HELLO = "你好"
CODE_TASK = "分析当前目录的代码并修复 calc.py 里的 bug。"


class _Memory:
    def __init__(self) -> None:
        self.load_session = MagicMock()
        self.initialize = AsyncMock()

    def save_session(self) -> None:
        return None


def _chat_agent() -> AgentV2:
    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._active_task = None
    agent._session_loaded = False
    agent._session_id = "chat-skip-await"
    agent._memory = _Memory()
    agent._llm = None
    agent._tool_orchestrator = None
    agent._tool_tracer = None
    agent._thinking_history = []
    agent._last_thinking = ""
    agent._side_effecting_tool_attempted = False
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._should_request_parallel_execution = MagicMock(return_value=False)
    agent._fast_reply = AsyncMock(return_value="fast")
    agent._fast_reply_with_tools = AsyncMock(return_value="tool path")
    agent._run_plan_only = AsyncMock(return_value="plan only")
    agent._graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"final_response": "graph answer"})
    )
    return agent


@pytest.mark.asyncio
async def test_chat_turn_emits_thinking_liveness_before_llm(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import agent_v2 as mod

    class _Tui:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def write_turn_liveness(self, text: str) -> None:
            self.seen.append(text)

    tui = _Tui()
    monkeypatch.setattr(mod, "get_tui", lambda: tui)
    agent = _chat_agent()
    before = {"ok": False}

    async def _guard(*_args, **_kwargs):
        before["ok"] = tui.seen == ["思考中..."]
        return "fast"

    agent._fast_reply = AsyncMock(side_effect=_guard)
    result = await agent._run_impl(HELLO, mode="build")
    assert result == "fast"
    assert before["ok"] is True


@pytest.mark.asyncio
async def test_chat_turn_skips_initialize_and_defers_load_session():
    agent = _chat_agent()
    load_before_reply = {"called": False}

    async def _guard(*_args, **_kwargs):
        load_before_reply["called"] = agent._memory.load_session.called
        return "fast"

    agent._fast_reply = AsyncMock(side_effect=_guard)
    result = await agent._run_impl(HELLO, mode="build")
    assert result == "fast"
    agent._fast_reply.assert_awaited_once_with(HELLO)
    agent._memory.initialize.assert_not_awaited()
    assert load_before_reply["called"] is False
    assert agent._session_loaded is True


@pytest.mark.asyncio
async def test_encoding_path_still_loads_session():
    agent = _chat_agent()
    result = await agent._run_impl(CODE_TASK, mode="build")
    assert result == "tool path"
    agent._fast_reply_with_tools.assert_awaited_once_with(CODE_TASK)
    agent._memory.initialize.assert_awaited_once()
    agent._memory.load_session.assert_called()
