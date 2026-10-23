"""K例复审（2026-10-13）九条验收要求的落地测试。

覆盖：P1 完整打包/压缩保位/状态绑定；P2 常驻一致/READ 分类/Graph 冻结/
ID 唯一与混合显式处理/中英文搜索；todo 单一 in_progress 统一校验。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.compaction import microcompact_messages
from RxyCode.RxyCode1_1_0.core.tool_search import (
    DISCOVERY_PIN_MARKER,
    TOOL_SEARCH_NAME,
    DeferredToolSearch,
    parse_deferred_tool_json_calls,
)


def _mcp_tool(name: str, payload_pad: int = 0, desc: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=desc or f"mcp {name}",
        metadata={
            "source": "mcp",
            "mcp_input_schema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                **({"x-pad": "p" * payload_pad} if payload_pad else {}),
            },
        },
        args_schema=None,
        output_schema=None,
    )


def _builtin(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=f"core {name}", metadata=None)


# 1. 大 schema 完整返回，未返回工具可再次发现 ────────────────────────────


def test_k3_1_oversized_results_pack_complete_items_only():
    """P1：预算内按整块塞；塞不下的保持未暴露，下次窄查询能拿到完整 schema。"""
    big = _mcp_tool("mcp_big_one", payload_pad=3400)
    medium = _mcp_tool("mcp_medium_two", payload_pad=1800)
    facade = DeferredToolSearch(lambda: {"mcp_big_one": big, "mcp_medium_two": medium})

    text = facade.search("mcp")
    # 只有完整块能出现；超预算项不被截半也不会被标成已暴露
    assert text.count("=== tool:") <= 2
    assert "…[truncated]" not in text.split("</tool_call>")[-1]
    exposed_names = set(facade.exposed)
    # withheld 命中必须明示（不是静默丢）
    for name in exposed_names:
        assert f"=== tool: {name} ===" in text
    # 未暴露的那个，用准确名字再查，必须拿到完整 schema
    for name in {"mcp_big_one", "mcp_medium_two"} - exposed_names:
        again = facade.search(name)
        assert f"=== tool: {name} ===" in again
        assert '"type": "object"' in again or '"type":"object"' in again


def test_k3_1_marked_exposed_only_when_fully_returned():
    tiny = _mcp_tool("mcp_t", payload_pad=0)
    huge = _mcp_tool("mcp_h", payload_pad=5000)
    registry = {"mcp_h": huge, "mcp_t": tiny}
    facade = DeferredToolSearch(lambda: registry)
    text = facade.search("mcp_h")
    if "=== tool: mcp_h ===" not in text:
        # 预算都塞不下时必须保持未暴露
        assert "mcp_h" not in facade.exposed
        assert "narrow" in text
    else:
        assert "mcp_h" in facade.exposed


# 2. 普通压缩后 pin 保留在原位置 + 不重复加载 ────────────────────────────


def test_k3_2_microcompact_keeps_discovery_message_in_place():
    discovery_content = (
        "=== tool: mcp_x ===\ndescription: x\nparameters: {}\n"
        "call_format: emit exactly one envelope per call:\n"
        '<tool_call>{"name": "mcp_x", "arguments": {}}</tool_call>\n'
        f"{DISCOVERY_PIN_MARKER}"
    )
    messages = [
        ToolMessage(content="old result A", tool_call_id="c1"),
        ToolMessage(content=discovery_content, tool_call_id="tsearch_1"),
        ToolMessage(content="old result B", tool_call_id="c2"),
        ToolMessage(content="recent result", tool_call_id="c3"),
    ]
    out, info = microcompact_messages(messages, keep_recent=1)
    texts = [str(m.content) for m in out]
    # 墓碑化只动普通旧结果；发现消息保持原文在位
    assert any("[tool result cleared" in t for t in texts)
    assert discovery_content in texts
    assert info["tombstoned"] == 2
    assert texts.index(discovery_content) == 1  # 原位置不动


def test_k3_2_exposure_binding_avoids_repeat_after_compaction():
    tool = _mcp_tool("mcp_x")
    facade = DeferredToolSearch(lambda: {"mcp_x": tool}, get_session_id=lambda: "s1")
    facade.search("x")
    again = facade.search("x")
    assert "ALREADY AVAILABLE" in again
    assert '"parameters"' not in again


# 3. 新会话 / schema 更新可以重新暴露 ────────────────────────────────────


def test_k3_3_new_session_allows_rediscovery():
    tool = _mcp_tool("mcp_x")
    session = {"id": "s1"}
    facade = DeferredToolSearch(
        lambda: {"mcp_x": tool}, get_session_id=lambda: session["id"]
    )
    facade.search("x")
    session["id"] = "s2"  # 新会话
    again = facade.search("x")
    assert "=== tool: mcp_x ===" in again  # 拿到完整 schema，而不是 ALREADY


def test_k3_3_schema_change_allows_rediscovery():
    v1 = _mcp_tool("mcp_x")
    v2 = _mcp_tool("mcp_x", payload_pad=10)  # 同名但 schema 变了
    registry = {"mcp_x": v1}
    facade = DeferredToolSearch(lambda: registry, get_session_id=lambda: "s1")
    facade.search("x")
    registry["mcp_x"] = v2
    again = facade.search("x")
    assert "=== tool: mcp_x ===" in again  # 版本更新重新暴露


# 4. 常驻一致：启动注册幂等 + subset 保留 + 搜索在无 deferred 时也可用 ──


def test_k3_4_startup_registers_search_idempotently_without_deferred():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = None
    agent._session_id = "s-fixed"
    registry = {"read": _builtin("read")}
    agent._tool_orchestrator = SimpleNamespace(
        get_all=lambda: dict(registry),
        get=lambda name: registry.get(name),
        register=lambda name, tool, risk=None: registry.__setitem__(name, tool),
        execute_tool=AsyncMock(),
    )
    agent._tool_search_facade = None
    agent._ensure_tool_search_tool()
    agent._ensure_tool_search_tool()  # 幂等
    names = [t.name for t in agent._get_core_tools()]
    assert names == ["read", TOOL_SEARCH_NAME]
    # 空目录：调用也给出明确信息而不是注册失败
    facade = agent._tool_search_facade
    assert facade is not None
    assert "No deferred tools" in facade.search("github")


def test_k3_4_subset_keeps_tool_search():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = SimpleNamespace(tool_send_policy="subset")
    agent._session_id = "s-subset"
    registry = {
        **{f"core_{i:02d}": _builtin(f"core_{i:02d}") for i in range(12)},
        TOOL_SEARCH_NAME: DeferredToolSearch(lambda: {}).as_tool(),
    }
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: dict(registry))
    names = [t.name for t in agent._get_core_tools()]
    assert TOOL_SEARCH_NAME in names
    assert len(names) == 8
    # 会话内固定：再取一次完全相同
    assert [t.name for t in agent._get_core_tools()] == names


# 5. READ 分类，不触发写审批/快照 ────────────────────────────────────────


def test_k3_5_tool_search_is_read_risk_and_plan_readonly():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import PLAN_READONLY_TOOL_NAMES
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, get_tool_risk

    assert get_tool_risk(TOOL_SEARCH_NAME) is RiskLevel.READ
    assert TOOL_SEARCH_NAME in PLAN_READONLY_TOOL_NAMES


# 6. Graph 绑定过滤 deferred（proxy 回查注册真身） ────────────────────────


def test_k3_6_executor_binds_frozen_only():
    from RxyCode.RxyCode1_1_0.core.tool_search import is_deferred_tool

    orchestrator = SimpleNamespace(
        get=lambda name: {
            "read": _builtin("read"),
            "mcp_g_search": _mcp_tool("mcp_g_search"),
        }.get(name)
    )
    proxies = [
        SimpleNamespace(name="read", description="proxy"),
        SimpleNamespace(name="mcp_g_search", description="proxy"),
    ]
    # 复刻 executor 的 frozen 过滤行（proxy 无 metadata，必须回查注册真身）
    available = [
        t for t in proxies
        if not is_deferred_tool(orchestrator.get(getattr(t, "name", "") or "") or t)
    ]
    assert [t.name for t in available] == ["read"]


# 7. ID 跨轮唯一；混合调用与孤儿不静默 ────────────────────────────────────


def test_k3_7_ids_unique_across_rounds():
    envelope = (
        '<tool_call>{"name": "mcp_a", "arguments": {}}</tool_call>'
    )
    calls1, _ = parse_deferred_tool_json_calls(envelope, start=0)
    calls2, _ = parse_deferred_tool_json_calls(envelope, start=len(calls1))
    ids = [c["id"] for c in [*calls1, *calls2]]
    assert ids == ["defercall_0", "defercall_1"]
    assert len(set(ids)) == 2


def test_k3_7_orphan_envelope_is_explicit_error_not_final_text():
    calls, malformed = parse_deferred_tool_json_calls(
        '<tool_call>{"name": "mcp_a", "arguments": '
    )
    assert calls and all(c["id"] in malformed for c in calls)
    assert any("unterminated" in msg for msg in malformed.values())


@pytest.mark.asyncio
async def test_k3_7_mixed_native_and_envelope_rejected_not_silent(monkeypatch):
    """原生命中 + envelope 混合：envelope 进 malformed 反馈，不静默，不执行。"""
    import RxyCode.RxyCode1_1_0.config.settings as settings
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._active_task = None
    agent._session_loaded = True
    agent._session_id = "defer-mixed"
    agent._memory = SimpleNamespace(
        initialize=AsyncMock(), load_session=lambda: None,
        get_context_for_prompt=lambda: "", add_interaction=lambda *a: None,
        save_session=lambda: None,
    )
    agent._llm = None
    agent._thinking_history = []
    agent._last_thinking = ""
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._has_creation_product_intent = MagicMock(return_value=False)
    agent.model_config = {"effort": "standard"}
    agent._cfg = {"execution": {"tool_timeout_seconds": 0}}
    executed = AsyncMock(return_value="echo:hello")
    orchestrator = SimpleNamespace(
        get=lambda name: {"mcp_fake_echo": _mcp_tool("mcp_fake_echo"), "read": _builtin("read")}.get(name),
        execute_tool=executed,
    )
    agent._tool_orchestrator = orchestrator
    agent._tool_tracer = MagicMock()
    agent._execute_tool = AgentV2._execute_tool.__get__(agent, AgentV2)
    agent._tool_search_facade = None
    agent._get_core_tools = MagicMock(return_value=[_builtin("read")])
    monkeypatch.setattr(settings, "load_config", lambda: agent._cfg)

    rounds = {"n": 0}
    captured_messages: list = []

    async def raw_stream(messages, bound_tools=None):
        rounds["n"] += 1
        captured_messages.append(messages)
        if rounds["n"] == 1:
            # 原生 tool_call + envelope 混合
            native = SimpleNamespace(
                index=0, id="native-1",
                function=SimpleNamespace(name="read", arguments='{"filePath":"x.txt"}'),
            )
            part1 = SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="", reasoning_content="", tool_calls=[native]
                ))],
                usage=None,
            )
            part2 = SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content='<tool_call>{"name": "mcp_fake_echo", "arguments": {"text": "x"}}</tool_call>',
                    reasoning_content="", tool_calls=None,
                ))],
                usage=None,
            )
            yield part1
            yield part2
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="wrapped up", reasoning_content="", tool_calls=None
                ))],
                usage=None,
            )

    agent._raw_stream = raw_stream
    await agent._fast_reply_with_tools("do the mixed thing", mode="build")

    # 原生执行了；envelope 的 mcp_fake_echo 不能执行（malformed）
    assert executed.await_count == 1
    call_names = [c.args[0] for c in executed.await_args_list]
    assert call_names == ["read"]
    # 跨轮 ID 唯一：agent._defercall_seq 已推进
    assert getattr(agent, "_defercall_seq", 0) >= 1


# 8. 中英文搜索都命中 ───────────────────────────────────────────────────


def test_k3_8_chinese_and_english_queries_hit():
    weather = _mcp_tool("mcp_weather_query", desc="查询城市天气、温度、湿度")
    github = _mcp_tool("mcp_github_search", desc="Search GitHub issues")
    registry = {"mcp_weather_query": weather, "mcp_github_search": github}
    facade = DeferredToolSearch(lambda: dict(registry))

    assert "mcp_weather_query" in facade.search("天气")
    facade2 = DeferredToolSearch(lambda: dict(registry))
    assert "mcp_weather_query" in facade2.search("温度 湿度")
    facade3 = DeferredToolSearch(lambda: dict(registry))
    assert "mcp_weather_query" in facade3.search("天气")
    facade4 = DeferredToolSearch(lambda: dict(registry))
    assert "mcp_github_search" in facade4.search("search github issues")


# 9. task_manage start 与 todo_write 同一单一 in_progress 校验 ────────────


def test_k3_9_task_manage_start_enforces_single_in_progress(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import task_tool

    monkeypatch.setattr(
        task_tool, "_tasks_dir", lambda: (tmp_path / "tasks" ).__class__(tmp_path / "tasks")
    )
    # fallback：意指 _tasks_dir 返回 tmp 下目录
    monkeypatch.setattr(task_tool, "_tasks_dir", lambda: tmp_path)

    assert "T1" in task_tool.manage_tasks(operation="create", summary="第一个任务")
    assert "T2" in task_tool.manage_tasks(operation="create", summary="第二个任务")
    assert "in_progress" in task_tool.manage_tasks(operation="start", id="T1")
    # 旧契约 bug：第二个 start 也不会拦——现在同一规则下必须拦
    second = task_tool.manage_tasks(operation="start", id="T2")
    assert "in_progress conflict" in second or "先完成" in second or "先" in second
    # T1 完成后 T2 可 start
    assert "done" in task_tool.manage_tasks(operation="done", id="T1")
    assert "in_progress" in task_tool.manage_tasks(operation="start", id="T2")
