"""2026-10-13 检索式分层（deferred tool discovery）分层冻结 + 派发回归。

工具 schema 层级（AI-Agents-in-Depth 图 4-4 模式）：
- 内置核心工具字节冻结进 request schema（前缀缓存不动）；
- deferred（MCP/plugin）工具绝不进 schema，经 tool_search 在轨迹中暴露；
- 发现的工具以 <tool_call> 自由形式派发，走同一审批/审计执行路径；
- 同一消息上下文里不重复加载 schema。换会话、清空或重建历史后重新给定义。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.tool_search import (
    DeferredToolSearch,
    TOOL_SEARCH_NAME,
    deferred_names,
    is_deferred_tool,
    parse_deferred_tool_json_calls,
)


def _builtin_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=f"core {name}", metadata=None)


def _mcp_tool(name: str, desc: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=desc or f"mcp {name}",
        metadata={"source": "mcp", "mcp_input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}},
        args_schema=None,
        output_schema=None,
    )


# ── 分层冻结 ──────────────────────────────────────────────────────────


def test_deferred_detection_and_partition():
    assert not is_deferred_tool(_builtin_tool("bash"))
    assert is_deferred_tool(_mcp_tool("mcp_g_x"))
    registry = {"bash": _builtin_tool("bash"), "mcp_g_x": _mcp_tool("mcp_g_x")}
    assert deferred_names(registry) == ["mcp_g_x"]


def test_get_core_tools_excludes_deferred_and_is_byte_stable():
    agent = object.__new__(AgentV2)
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = None

    registry = {
        "write": _builtin_tool("write"),
        "read": _builtin_tool("read"),
        "bash": _builtin_tool("bash"),
        "mcp_g_search": _mcp_tool("mcp_g_search"),
        "mcp_g_pull": _mcp_tool("mcp_g_pull"),
    }
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: dict(registry))

    tools = agent._get_core_tools()
    names = [t.name for t in tools]
    assert names == ["bash", "read", "write"]  # 按名排序的冻结核心集
    assert "mcp_g_search" not in names and "mcp_g_pull" not in names

    # 重复调用 schema 字节必须一致（前缀缓存不变）
    dump1 = json.dumps([t.name for t in agent._get_core_tools()], sort_keys=True)
    dump2 = json.dumps([t.name for t in agent._get_core_tools()], sort_keys=True)
    assert dump1 == dump2


def test_tool_search_adapter_registers_once_and_stays_in_core():
    agent = object.__new__(AgentV2)
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = None

    registry = {
        "read": _builtin_tool("read"),
        "mcp_g_search": _mcp_tool("mcp_g_search"),
    }

    def fake_get(name):
        return registry.get(name)

    register_calls: list[tuple] = []
    orchestrator = SimpleNamespace(
        get_all=lambda: dict(registry),
        get=fake_get,
        register=lambda name, tool, risk=None: (
            register_calls.append((name, tool, risk)),
            registry.__setitem__(name, tool),
        )[0],
    )
    agent._tool_orchestrator = orchestrator

    assert TOOL_SEARCH_NAME not in [t.name for t in agent._get_core_tools()]
    agent._ensure_tool_search_tool()
    tool = registry.get(TOOL_SEARCH_NAME)
    assert tool is not None
    assert tool.description  # 冻结描述非空
    assert register_calls[0][0] == TOOL_SEARCH_NAME
    assert register_calls[0][2] == "read"

    # 幂等：再次 ensure 不再重复注册；之后 get_core_tools 恒定含该元工具
    agent._ensure_tool_search_tool()
    assert len(register_calls) == 1
    for _ in range(3):
        names = [t.name for t in agent._get_core_tools()]
        assert names == ["read", TOOL_SEARCH_NAME]


# ── 搜索 + 去重 ────────────────────────────────────────────────────────


def _search_facade(registry: dict):
    return DeferredToolSearch(lambda: dict(registry))


def test_search_ranks_by_name_and_description():
    registry = {
        "mcp_github_search": _mcp_tool("mcp_github_search", "Search GitHub issues and PRs"),
        "mcp_github_create": _mcp_tool("mcp_github_create", "Create GitHub issue"),
        "mcp_weather_now": _mcp_tool("mcp_weather_now", "Current weather in a city"),
    }
    facade = _search_facade(registry)
    text = facade.search("github search")
    first_block = text.split("\n\n")[0] if "\n\n" in text else text
    assert "mcp_github_search" in first_block
    assert "parameters:" in text
    # K例复审修订：发现块必须显式声明"不在 function-calling 列表里、
    # 普通调用不会执行"，否则真实模型会反复重查 tool_search（实测 deepseek-v4-flash）。
    assert "IMPORTANT" in text and "<tool_call>" in text


def test_search_no_match_and_empty_catalog():
    registry = {"mcp_github_search": _mcp_tool("mcp_github_search")}
    facade = _search_facade(registry)
    assert "No deferred tool matches" in facade.search("tplone zzz")
    empty = DeferredToolSearch(lambda: {})
    assert "No deferred tools are available" in empty.search("anything")


def test_search_dedups_already_exposed_schemas():
    registry = {"mcp_github_search": _mcp_tool("mcp_github_search")}
    facade = _search_facade(registry)
    first = facade.search("github")
    assert "parameters:" in first
    second = facade.search("github")
    assert "ALREADY AVAILABLE" in second
    assert "parameters:" not in second


# ── 自由形式解析 ───────────────────────────────────────────────────────


def test_parse_valid_envelope_with_nested_args():
    answer = (
        "我来调用搜索工具。\n"
        '<tool_call>{"name": "mcp_g_search", "arguments": {"q": "kimi", "opts": {"limit": 3, "tags": ["a","b"]}}}</tool_call>'
    )
    calls, malformed = parse_deferred_tool_json_calls(answer)
    assert malformed == {}
    assert len(calls) == 1
    assert calls[0]["name"] == "mcp_g_search"
    assert calls[0]["args"]["opts"]["limit"] == 3
    assert calls[0]["id"].startswith("defercall_")


def test_parse_multiple_and_malformed():
    answer = (
        '<tool_call>{"name": "mcp_a", "arguments": {}}</tool_call>'
        '<tool_call>{"name": "mcp_b", "arguments": {"x": 1}}</tool_call>'
        '<tool_call>{"not json at all…}</tool_call>'
    )
    calls, malformed = parse_deferred_tool_json_calls(answer)
    assert [c["name"] for c in calls if c["name"] != "<invalid>"] == ["mcp_a", "mcp_b"]
    assert len(malformed) == 1  # 坏 JSON 进 malformed，不静默丢


def test_parse_rejects_non_dict_arguments_and_missing_name():
    calls, malformed = parse_deferred_tool_json_calls(
        '<tool_call>{"name": "mcp_a", "arguments": [1,2]}</tool_call>'
        '<tool_call>{"arguments": {}}</tool_call>'
    )
    assert len(malformed) == 2
    assert all(c["args"] == {} for c in calls if c["name"] == "mcp_a")


# ── 快路径 E2E：自由形式派发 + schema 不被污染 ────────────────────────


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


@pytest.mark.asyncio
async def test_fast_path_deferred_dispatch_via_envelope(monkeypatch):
    """模型输出 <tool_call> 自由形式 → 同一执行路径；request tools 数组
    每一轮都只有冻结核心 + tool_search（deferred 名字绝不出现）。"""
    import RxyCode.RxyCode1_1_0.config.settings as settings

    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._active_task = None
    agent._session_loaded = True
    agent._session_id = "defer-dispatch"
    agent._memory = _Memory()
    agent._llm = None
    agent._thinking_history = []
    agent._last_thinking = ""
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._has_creation_product_intent = MagicMock(return_value=False)
    agent.model_config = {"effort": "standard"}
    agent._cfg = {"execution": {"tool_timeout_seconds": 0}}

    registry = {
        "read": _builtin_tool("read"),
        "mcp_fake_echo": _mcp_tool("mcp_fake_echo", "echo text back"),
    }
    executed = AsyncMock(return_value="echo: hello")
    orchestrator = SimpleNamespace(
        get_all=lambda: dict(registry),
        get=lambda name: registry.get(name),
        register=lambda name, tool, risk=None: registry.__setitem__(name, tool),
        execute_tool=executed,
    )
    agent._tool_orchestrator = orchestrator
    agent._tool_tracer = MagicMock()
    agent._execute_tool = AgentV2._execute_tool.__get__(agent, AgentV2)
    agent._tool_search_facade = None
    agent._ensure_tool_search_tool()  # 启动即常驻；这里补登记，不依赖 MCP 落地

    monkeypatch.setattr(settings, "load_config", lambda: agent._cfg)

    bound_names: list[list[str]] = []
    rounds = 0

    async def raw_stream(_messages, bound_tools=None):
        nonlocal rounds
        rounds += 1
        bound_names.append([t.name for t in (bound_tools or [])])
        if rounds == 1:
            envelope = (
                '<tool_call>{"name": "mcp_fake_echo", '
                '"arguments": {"text": "hello"}}</tool_call>'
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=envelope, reasoning_content="", tool_calls=None
                ))],
                usage=None,
            )
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="found it: echo: hello", reasoning_content="", tool_calls=None
                ))],
                usage=None,
            )

    agent._raw_stream = raw_stream

    result = await agent._fast_reply_with_tools("use the echo tool", mode="build")

    assert "echo: hello" in result or "found it" in result
    executed.assert_awaited_once_with(
        "mcp_fake_echo",
        {"text": "hello"},
        config=agent._cfg,
        mode="build",
        call_id="defercall_0",
    )
    # 关键不变量：request schema 每轮都只有 read + tool_search
    assert bound_names, "raw_stream 应至少收到一轮请求"
    for names in bound_names:
        assert names == ["read", TOOL_SEARCH_NAME]
        assert "mcp_fake_echo" not in names
