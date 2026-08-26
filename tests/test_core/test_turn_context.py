"""FX8 · public append_turn_context seam (PHASE-FIX §5 FX8).

EKO-style context can only append to the user suffix after the prefix is
frozen. ChatPrefix ignores it. Empty blocks are byte-identical to a no-op.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def _ctx_agent() -> AgentV2:
    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._active_task = None
    agent._session_loaded = True
    agent._session_id = "turn-context"
    agent._memory = SimpleNamespace(
        get_context_for_prompt=MagicMock(return_value="MEMORY-BASE"),
        add_interaction=MagicMock(),
        save_session=MagicMock(),
    )
    agent._llm = None
    agent.model_config = {}
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
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)
    return agent


def test_zero_blocks_leave_memory_ctx_empty():
    """append([]) / no call must both produce an empty suffix — the user
    message stays byte-identical to the untouched call."""
    from unittest.mock import patch
    from datetime import datetime
    from RxyCode.RxyCode1_1_0.core.prompts.registry import build_user_message

    agent = _ctx_agent()
    assert agent._turn_context_suffix() == ""
    agent.append_turn_context([])
    assert agent._turn_context_suffix() == ""
    fixed = datetime(2026, 1, 1, 12, 0, 0)
    with patch("RxyCode.RxyCode1_1_0.core.prompts.registry.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        msg_a = build_user_message("", "hi", "")
        msg_b = build_user_message("", "hi", agent._turn_context_suffix())
    assert msg_a == msg_b
    agent.append_turn_context([{"kind": "eko", "text": "  "}])
    assert agent._turn_context_suffix() == ""


def test_rejects_system_and_tools_kinds():
    agent = _ctx_agent()
    with pytest.raises(ValueError):
        agent.append_turn_context([{"kind": "system", "text": "x"}])
    with pytest.raises(ValueError):
        agent.append_turn_context([{"kind": "tools", "text": "x"}])
    agent.append_turn_context([{"kind": "eko", "text": "y"}])
    agent.append_turn_context([{"kind": "note", "text": "z"}])
    assert "y" in agent._turn_context_suffix()
    assert "z" in agent._turn_context_suffix()


@pytest.mark.asyncio
async def test_chat_path_ignores_blocks(monkeypatch):
    """append eko then route 你好 → _fast_reply receives empty memory_ctx."""
    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_v2_module

    captured = {}
    original = agent_v2_module.build_user_message

    def _spy(role_instruction, user_content, memory_context="", locale=None):
        captured["memory_context"] = memory_context
        return original(role_instruction, user_content, memory_context, locale)

    monkeypatch.setattr(agent_v2_module, "build_user_message", _spy)
    agent = _ctx_agent()
    agent._fast_reply = AgentV2._fast_reply.__get__(agent, AgentV2)
    agent._fast_reply_with_tools = AsyncMock(return_value="tool path")
    async_calls = {"n": 0}

    async def _raw(msgs, tools=None, max_tokens=None):
        async_calls["n"] += 1
        if False:  # pragma: no cover
            yield None

    agent._raw_stream = _raw
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)
    agent._memory.get_context_for_prompt = MagicMock(return_value="")
    agent.append_turn_context([{"kind": "eko", "text": "EKO-CONTEXT"}])
    await agent._run_impl("你好", mode="build")
    assert captured["memory_context"] == ""


@pytest.mark.asyncio
async def test_agent_path_appends_after_memory(monkeypatch):
    """agent path: memory_context = base memory + suffix, suffix after."""
    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_v2_module

    captured = {}
    original = agent_v2_module.build_user_message

    def _spy(role_instruction, user_content, memory_context="", locale=None):
        captured["memory_context"] = memory_context
        return original(role_instruction, user_content, memory_context, locale)

    monkeypatch.setattr(agent_v2_module, "build_user_message", _spy)
    agent = _ctx_agent()
    agent._fast_reply_with_tools = AgentV2._fast_reply_with_tools.__get__(
        agent, AgentV2
    )
    agent._raw_stream = AsyncMock()

    async def _raw(msgs, tools=None, max_tokens=None):
        if False:  # pragma: no cover
            yield None

    agent._raw_stream = _raw
    agent._get_core_tools = lambda: [
        SimpleNamespace(name="bash", args_schema={}),
    ]
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)
    agent.model_config = {"model_name": "test-model", "effort": "balanced"}
    agent.append_turn_context([{"kind": "eko", "text": "EKO-CONTEXT"}])
    await agent._fast_reply_with_tools("帮我写个排序函数。")
    assert "EKO-CONTEXT" in captured["memory_context"]
    assert captured["memory_context"].endswith("EKO-CONTEXT")
    assert "MEMORY-BASE" in captured["memory_context"]


def test_clear_turn_context_removes_suffix():
    agent = _ctx_agent()
    agent.append_turn_context([{"kind": "eko", "text": "A"}])
    assert "A" in agent._turn_context_suffix()
    agent.clear_turn_context()
    assert agent._turn_context_suffix() == ""


@pytest.mark.asyncio
async def test_empty_blocks_byte_identical_through_agent_path(monkeypatch):
    """append([]) / all-blank text through the REAL agent path must pass the
    same memory_context to build_user_message as no call at all."""
    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_v2_module

    captured = []
    original = agent_v2_module.build_user_message

    def _spy(role_instruction, user_content, memory_context="", locale=None):
        captured.append(memory_context)
        return original(role_instruction, user_content, memory_context, locale)

    monkeypatch.setattr(agent_v2_module, "build_user_message", _spy)

    agent = _ctx_agent()
    agent._fast_reply_with_tools = AgentV2._fast_reply_with_tools.__get__(
        agent, AgentV2
    )

    async def _raw(msgs, tools=None, max_tokens=None):
        if False:  # pragma: no cover
            yield None

    agent._raw_stream = _raw
    agent._get_core_tools = lambda: [SimpleNamespace(name="bash", args_schema={})]
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)
    agent.model_config = {"model_name": "test-model", "effort": "balanced"}

    await agent._fast_reply_with_tools("帮我写个排序函数。")
    agent.append_turn_context([])
    await agent._fast_reply_with_tools("帮我写个排序函数。")
    agent.append_turn_context([{"kind": "eko", "text": "   "}])
    await agent._fast_reply_with_tools("帮我写个排序函数。")

    assert len(captured) == 3
    assert captured[0] == "MEMORY-BASE"
    # Later turns ride the frozen AgentPrefix; empty FX8 blocks still must
    # not change the new-suffix memory_context relative to each other.
    assert captured[1] == captured[2]
