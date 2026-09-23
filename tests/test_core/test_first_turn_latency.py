"""First-turn latency and cache: travel-plan / small-game / no-tool prompts.

Live GUI CDP hung >120s on 「成都两日游」 because:
1. tool-aware fast path always bypassed application caches
2. creation requests fell through to LangGraph
3. run() scheduled a competing prewarm (90s) beside the user LLM call
4. run() awaited MCP refresh even when a background refresh was in flight
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.request_routing import (
    RoutingDirective,
    declines_tools,
    has_creation_product_intent,
)


CHENGDU = "用三句话规划成都两日美食游，不要改文件，不要调用工具。"
CHENGDU_AGAIN = "再用三句话规划成都两日美食游，同样不要改文件不要调用工具。"
CODE_TASK_FROZEN = "给这个项目补一套单元测试并跑一遍。"
SNAKE = "做个贪吃蛇小游戏"


class _Memory:
    async def initialize(self):
        return None

    def load_session(self):
        return None

    def get_context_for_prompt(self):
        return ""

    def add_interaction(self, *_args):
        return None

    def save_session(self):
        return None


def _run_agent() -> AgentV2:
    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._active_task = None
    agent._session_loaded = True
    agent._session_id = "first-turn"
    agent._memory = _Memory()
    agent._llm = None
    agent._tool_orchestrator = None
    agent._tool_tracer = None
    agent._thinking_history = []
    agent._last_thinking = ""
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._is_simple_query = AgentV2._is_simple_query.__get__(agent, AgentV2)
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)
    agent._has_creation_product_intent = AgentV2._has_creation_product_intent.__get__(
        agent, AgentV2
    )
    agent._should_request_parallel_execution = MagicMock(return_value=False)
    agent._fast_reply = AsyncMock(return_value="cached itinerary")
    agent._fast_reply_with_tools = AsyncMock(return_value="tool path")
    agent._graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"final_response": "graph answer"})
    )
    return agent


def test_fast_reply_does_not_force_thinking_off():
    """First-round tool thinking stays on unless this is approved-plan implement."""
    tools_src = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "_thinking_disabled_this_turn = False" in tools_src
    live_gate = tools_src.split("# 废弃代码")[0]
    assert 'model_config.get("effort") == "fast"' not in live_gate


def test_chengdu_itinerary_declines_tools():
    assert declines_tools(CHENGDU) is True
    assert declines_tools(CHENGDU_AGAIN) is True
    assert declines_tools(SNAKE) is False
    assert declines_tools("帮我写一个跑酷小游戏") is False


def test_declines_tools_is_chat_prefix():
    """FX6: declines/social route to ChatPrefix; the allowlist resolver is
    execution-layer legacy and must never shape API schema."""
    from RxyCode.RxyCode1_1_0.core.turn_router import route

    d = route(CHENGDU, "build", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "chat"


def test_small_game_is_creation_not_full_project():
    assert has_creation_product_intent(SNAKE) is True
    assert has_creation_product_intent("帮我写一个跑酷小游戏") is True


@pytest.mark.parametrize(
    "prompt",
    [
        "Create T04-travel as an interactive webpage with a budget CSV.",
        "Create T06-market-bi as an interactive BI dashboard with source data.",
        "Create T07-ev as a five-year decision system with sliders and tables.",
        "Create T09-coffee as a Java Spring full-stack project with MySQL.",
    ],
)
def test_real_artifact_requests_use_creation_product_routing(prompt: str):
    """Artifact prompts must not idle in planner+decomposer before tools."""
    assert has_creation_product_intent(prompt) is True


def test_long_research_artifact_prompt_stays_on_creation_routing():
    prompt = (
        "Create T04-travel in the current workspace. First call datetime and "
        "record the date. Plan transport, lodging, tickets, food and styling; "
        "use websearch and webfetch, record sources and uncertainty, and keep "
        "the budget within the hard limit. Deliver all documentation and an "
        "interactive webpage with filters, a timetable, and a budget view."
    )
    assert has_creation_product_intent(prompt) is True


@pytest.mark.asyncio
async def test_no_tool_itinerary_uses_cacheable_fast_reply():
    agent = _run_agent()
    result = await agent._run_impl(CHENGDU, mode="build")
    assert result == "cached itinerary"
    agent._fast_reply.assert_awaited_once_with(CHENGDU)
    agent._fast_reply_with_tools.assert_not_awaited()
    agent._graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_small_game_uses_tool_fast_path_not_langgraph():
    agent = _run_agent()
    result = await agent._run_impl(SNAKE, mode="build")
    assert result == "tool path"
    agent._fast_reply_with_tools.assert_awaited_once_with(SNAKE)
    agent._graph.ainvoke.assert_not_awaited()
    agent._fast_reply.assert_not_awaited()


REFACTOR = "帮我重构整个项目的认证模块，把代码整理干净。"
CODE_TASK = "分析当前目录的代码并修复 calc.py 里的 bug。"


@pytest.mark.asyncio
async def test_complex_code_task_uses_stream_loop_not_langgraph():
    agent = _run_agent()
    result = await agent._run_impl(REFACTOR, mode="build")
    assert result == "tool path"
    agent._fast_reply_with_tools.assert_awaited_once_with(REFACTOR)
    agent._graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_code_project_sentence_does_not_enter_graph():
    agent = _run_agent()
    result = await agent._run_impl(CODE_TASK, mode="build")
    assert result == "tool path"
    agent._graph.ainvoke.assert_not_awaited()
    agent._fast_reply_with_tools.assert_awaited_once_with(CODE_TASK)


@pytest.mark.asyncio
async def test_full_directive_still_enters_langgraph():
    agent = _run_agent()
    result = await agent._run_impl("/full " + REFACTOR, mode="build")
    assert result == "graph answer"
    agent._graph.ainvoke.assert_awaited_once()
    agent._fast_reply_with_tools.assert_not_awaited()


def test_run_does_not_schedule_competing_prewarm():
    src = inspect.getsource(AgentV2.run)
    assert "_schedule_prewarm" not in src


def test_worker_bootstrap_does_not_prewarm_on_open():
    from appserver.agent_worker import AgentWorker

    src = inspect.getsource(AgentWorker._handle_bootstrap)
    assert "_schedule_prewarm" not in src


def test_worker_schedules_prewarm_after_first_prompt():
    from appserver.agent_worker import AgentWorker

    src = inspect.getsource(AgentWorker._handle_prompt)
    assert "_cancel_background_prewarm" in src
    assert "_schedule_prewarm" in src


def test_worker_idle_prefix_warm_after_bootstrap():
    from appserver.agent_worker import AgentWorker

    src = inspect.getsource(AgentWorker._handle_bootstrap)
    assert "_arm_idle_prefix_warm" in src
    arm = inspect.getsource(AgentWorker._arm_idle_prefix_warm)
    assert "_schedule_prewarm" in arm
    assert "_preconnect_provider" in arm


def test_run_does_not_await_mcp_refresh():
    src = inspect.getsource(AgentV2.run) + inspect.getsource(AgentV2._run_user_turn_body)
    assert "_schedule_mcp_refresh" in src
    assert "asyncio.to_thread" not in src


def test_declines_tools_skips_mcp_refresh_on_turn():
    agent = object.__new__(AgentV2)
    assert agent._should_skip_mcp_refresh(CHENGDU) is True
    assert agent._should_skip_mcp_refresh("读取 src/main.py") is False


def test_declines_tools_skips_analyze_progress():
    agent = object.__new__(AgentV2)
    assert agent._should_emit_analyze_progress(CHENGDU) is False
    assert agent._should_emit_analyze_progress("帮我重构整个项目") is True


@pytest.mark.asyncio
async def test_agent_tools_frozen_across_encoding_turns():
    """FX6: the tools bound for encoding turns must not change with user
    text — two different encoding tasks bind the same full core set."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from RxyCode.RxyCode1_1_0.core.prefix_profile import digest_tools

    agent = _run_agent()
    captured = []

    async def _raw(msgs, tools=None, max_tokens=None):
        captured.append(tools)
        if False:  # pragma: no cover
            yield None

    agent._raw_stream = _raw
    agent._get_core_tools = lambda: [
        SimpleNamespace(name="bash", args_schema={}),
        SimpleNamespace(name="read", args_schema={}),
    ]
    agent._resolve_fast_reply_tool_allowlist = lambda u, a: frozenset()
    agent._session_loaded = True
    agent.model_config = {"model_name": "test-model", "effort": "balanced"}
    agent._memory.get_context_for_prompt = MagicMock(return_value="")
    agent._fast_reply_with_tools = AgentV2._fast_reply_with_tools.__get__(
        agent, AgentV2
    )
    agent._is_social_chat = AgentV2._is_social_chat.__get__(agent, AgentV2)

    await agent._fast_reply_with_tools(REFACTOR)
    await agent._fast_reply_with_tools(CODE_TASK_FROZEN)

    assert len(captured) >= 2  # master post-merge: multi-round loop calls _raw_stream per round
    digests = {digest_tools(t) for t in captured}
    assert len(digests) == 1  # frozen across ALL rounds and both inputs
    assert [t.name for t in captured[0]] == ["bash", "read"]
