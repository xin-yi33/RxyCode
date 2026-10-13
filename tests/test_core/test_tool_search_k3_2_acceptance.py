"""K3-2 复审（2026-10-13）七条缺口的行为级验收。

与 test_tool_search_discovery_k3.py 区分：本文件全部是**行为级**测试——
真实中间件、真实内置工具、真实 fold 路径、真实 executor 绑定过滤，不是
复制生产表达式的样子货。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity
from RxyCode.RxyCode1_1_0.core.tool_search import (
    DISCOVERY_PIN_MARKER,
    TOOL_SEARCH_DESCRIPTION,
    DeferredToolSearch,
    parse_deferred_tool_json_calls,
    push_disclosure_context,
    reset_disclosure_context,
)
from RxyCode.RxyCode1_1_0.execution.executor import _DeferredEnvelopeDispatchMiddleware


def _mcp_write_tool(name: str) -> SimpleNamespace:
    """metadata 标 deferred + 默认 WRITE 的 MCP 形状工具替身。"""
    return SimpleNamespace(
        name=name,
        description=f"mcp {name} write",
        metadata={"source": "mcp", "mcp_input_schema": {"type": "object", "properties": {}}},
        args_schema=None,
        output_schema=None,
    )


def _orch_stub(registry: dict, execute_result: str = "ok"):
    stub = SimpleNamespace()
    stub.get = lambda name: registry.get(name)
    stub.execute_tool = AsyncMock(return_value=execute_result)
    stub._risk_overrides = {}
    stub.begin_evidence_capture = lambda: object()
    stub.end_evidence_capture = lambda token: []
    return stub


def _ai_state(content: str, *, tool_calls=None) -> dict:
    ai = AIMessage(content=content)
    if tool_calls:
        ai = ai.model_copy(update={"tool_calls": tool_calls})
    return {"messages": [HumanMessage(content="task"), ai]}


# ## 1：READ 子任务 envelope 拒 WRITE/DANGER ────────────────────────────


@pytest.mark.asyncio
async def test_k3_2_1_read_task_rejects_write_envelope():
    orchestrator = _orch_stub({"mcp_wipe": _mcp_write_tool("mcp_wipe")})
    middleware = _DeferredEnvelopeDispatchMiddleware(
        orchestrator, {}, max_risk=RiskLevel.READ, round_limit=None
    )
    state = _ai_state(
        '<tool_call>{"name": "mcp_wipe", "arguments": {"path": "/x"}}</tool_call>'
    )
    result = await middleware.aafter_model(state, None)
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert orchestrator.execute_tool.await_count == 0
    assert any("READ-only" in str(m.content) for m in tool_msgs)


@pytest.mark.asyncio
async def test_k3_2_1_read_task_allows_read_classified_envelope():
    """gate 是下限语义：分类表 READ 的工具放行（override 只能升不能降）。"""
    read_tool = SimpleNamespace(name="read", description="readonly lookup", metadata={"source": "mcp"})
    orchestrator = _orch_stub({"read": read_tool})
    middleware = _DeferredEnvelopeDispatchMiddleware(
        orchestrator, {}, max_risk=RiskLevel.READ, round_limit=None
    )
    state = _ai_state(
        '<tool_call>{"name": "read", "arguments": {"filePath": "a.txt"}}</tool_call>'
    )
    result = await middleware.aafter_model(state, None)
    assert orchestrator.execute_tool.await_count == 1
    assert orchestrator.execute_tool.await_args.args[0] == "read"
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs and "READ-only" not in str(tool_msgs[0].content)


# # 2：回合预算执行前生效（不再先执行再补拒绝） ─────────────────────────


@pytest.mark.asyncio
async def test_k3_2_2_round_limit_blocks_before_execution():
    orchestrator = _orch_stub({"mcp_echo": _mcp_write_tool("mcp_echo")})
    orchestrator._risk_overrides = {"mcp_echo": RiskLevel.WRITE}
    middleware = _DeferredEnvelopeDispatchMiddleware(
        orchestrator, {}, max_risk=None, round_limit=1
    )
    envelope = '<tool_call>{"name": "mcp_echo", "arguments": {}}</tool_call>'
    # 第 1 轮：执行
    result1 = await middleware.aafter_model(_ai_state(envelope), None)
    assert orchestrator.execute_tool.await_count == 1
    assert any("ok" == str(m.content) for m in result1["messages"] if isinstance(m, ToolMessage))
    # 第 2 轮（新 AI，含 envelope，轨迹里已有带 tool_calls 的 AIMessage）
    ai1 = result1["messages"][0]
    bag = result1["messages"] + [ai1]
    state2 = {"messages": [*bag, AIMessage(content=envelope)]}
    result2 = await middleware.aafter_model(state2, None)
    assert orchestrator.execute_tool.await_count == 1  # 没有再执行
    assert result2.get("jump_to") == "end"
    assert any(
        "max_tool_rounds" in str(m.content)
        for m in result2["messages"]
        if isinstance(m, ToolMessage)
    )


# # 3：fold 折叠保留 pin 单元及调用配对 ────────────────────────────────


def test_k3_2_3_fold_keeps_discovery_pair_in_place():
    from RxyCode.RxyCode1_1_0.core.compaction import compact_messages

    discovery_text = (
        "=== tool: mcp_x ===\nparameters: {\"type\": \"object\"}\n"
        "IMPORTANT: x\n<tool_call>{\"name\":\"mcp_x\",\"arguments\":{}}</tool_call>\n"
        + DISCOVERY_PIN_MARKER
    )
    search_call_ai = AIMessage(
        content="",
        tool_calls=[{"name": "tool_search", "args": {"query": "x"}, "id": "ts_1", "type": "tool_call"}],
    )
    messages = [
        HumanMessage(content="build something"),
        search_call_ai,
        ToolMessage(content=discovery_text, tool_call_id="ts_1"),
        HumanMessage(content="continue " + "填充 " * 200),
        AIMessage(content="work " + "进行中 " * 200),
        HumanMessage(content="next step please"),
        AIMessage(content="final tail answer"),
    ]
    out = compact_messages(messages, tail_turns=1, return_telemetry=False)
    contents = [str(getattr(m, "content", "") or "") for m in out]
    # 发现 ToolMessage 原文到位（不被折进摘要）
    assert any(DISCOVERY_PIN_MARKER in c for c in contents)
    pinned_idx = next(i for i, c in enumerate(contents) if DISCOVERY_PIN_MARKER in c)
    # 配对：钉住的发现 TM 前面紧邻着发起 tool_search 的 AI 调用（同单元保留）
    parent_ai_idx = next(
        i
        for i, m in enumerate(out)
        if getattr(m, "tool_calls", None)
        and any(tc.get("name") == "tool_search" for tc in m.tool_calls)
    )
    assert parent_ai_idx + 1 == pinned_idx
    # 折叠确实发生（摘要消息在流里）
    assert any(
        (getattr(m, "additional_kwargs", None) or {}).get("is_compaction_summary")
        for m in out
    )


# # 4：tools_hint 限定后仍保留 tool_search（真实 executor 绑定） ───────


@pytest.mark.asyncio
async def test_k3_2_4_hint_keeps_tool_search_in_bound_list(monkeypatch):
    import RxyCode.RxyCode1_1_0.execution.executor as executor_module
    from RxyCode.RxyCode1_1_0.core.state import TaskNode

    registry = {
        "mcp_echo": _mcp_write_tool("mcp_echo"),
        "tool_search": DeferredToolSearch(lambda: {}).as_tool(),
    }
    captured: dict[str, list[str]] = {}

    def fake_select(hints, config, max_risk=None):
        names = [
            name for name in registry
            if any(h.lower() in name.lower() for h in (hints or []))
        ]
        captured["select_hints"] = list(hints or [])
        return [registry[n] for n in names]

    stub = SimpleNamespace(
        get=lambda name: registry.get(name),
        select_safe_tools=fake_select,
        begin_evidence_capture=lambda: object(),
        end_evidence_capture=lambda token: [],
    )

    graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="done")]})
    )
    create_agent = MagicMock(return_value=graph)
    monkeypatch.setattr(executor_module, "create_agent", create_agent)

    from RxyCode.RxyCode1_1_0.execution.executor import Executor

    executor = Executor(object(), stub, config={"execution": {"max_tool_rounds": 3}})
    await executor.execute_with_evidence(
        TaskNode(title="t", description="d", tools_hint=["mcp_echo"]), ""
    )

    bound_names = [t.name for t in create_agent.call_args.args[1]]
    # hint 命中的 deferred 工具被过滤；tool_search 一定在场
    assert "mcp_echo" not in bound_names
    assert "tool_search" in bound_names
    assert captured["select_hints"] == ["tool_search"]


# # 5：真实内置按需工具返回真 schema ────────────────────────────────────


def test_k3_2_5_real_builtin_deferred_tools_return_json_schema():
    from RxyCode.RxyCode1_1_0.tools.download_tool import (
        download_mcp_tool,
        download_skill_tool,
    )
    try:
        from RxyCode.RxyCode1_1_0.tools.team_install_tool import (
            team_install_tool,
        )
    except ImportError:
        team_install_tool = None

    registry = {
        "download_skill": download_skill_tool,
        "download_mcp": download_mcp_tool,
    }
    if team_install_tool is not None:
        registry[team_install_tool.name] = team_install_tool
    for name in registry:
        text = DeferredToolSearch(lambda: dict(registry)).search(name)
        assert f"=== tool: {name} ===" in text
        assert '"properties"' in text
        assert "<class '" not in text.split("parameters:", 1)[-1][:800]
    # 真实参数字段能被模型读到（新 facade，不与上段共用暴露记录）
    skill_text = DeferredToolSearch(lambda: dict(registry)).search("download_skill")
    assert "operation" in skill_text or "package" in skill_text or "url" in skill_text


# # 6：单个大 schema 完整取得（不超过硬上限） ──────────────────────────


def test_k3_2_6_single_oversized_tool_fully_discoverable():
    pad = "x" * 5200
    huge = SimpleNamespace(
        name="mcp_huge",
        description="huge single tool",
        metadata={
            "source": "mcp",
            "mcp_input_schema": {
                "type": "object",
                "properties": {"pad": {"type": "string", "description": pad}},
            },
        },
        args_schema=None,
    )
    facade = DeferredToolSearch(lambda: {"mcp_huge": huge})
    text = facade.search("mcp_huge")
    assert "=== tool: mcp_huge ===" in text
    assert pad[-20:] in text  # 完整取得，含末尾
    assert DISCOVERY_PIN_MARKER in text
    assert "mcp_huge" in facade.exposed


# # 7：解析严格性 + graph 混合显式拒 ────────────────────────────────────


def test_k3_2_7_trailing_second_json_inside_envelope_rejected():
    calls, malformed = parse_deferred_tool_json_calls(
        '<tool_call>{"name": "mcp_a", "arguments": {}} {"name": "mcp_b"}</tool_call>'
    )
    assert calls and len(calls) == 1
    assert calls[0]["id"] in malformed
    assert "trailing" in malformed[calls[0]["id"]]


def test_k3_2_7_overflow_envelopes_explicitly_rejected():
    answer = "".join(
        f'<tool_call>{{"name": "mcp_{i}", "arguments": {{}}}}</tool_call>'
        for i in range(9)
    )
    calls, malformed = parse_deferred_tool_json_calls(answer)
    assert len(calls) == 9  # 8 合法 + 1 超限拒收行
    assert any(
        "limit" in malformed[c["id"]] or "NOT executed" in malformed[c["id"]]
        for c in calls
        if c["name"] == "<invalid>"
    )


def test_isolated_disclosure_contexts_do_not_share_already_available():
    registry = {"mcp_echo": _mcp_write_tool("mcp_echo")}
    facade = DeferredToolSearch(lambda: registry, get_session_id=lambda: "same-session")
    first_token = push_disclosure_context("ctx-a")
    try:
        first = facade.search("echo")
    finally:
        reset_disclosure_context(first_token)
    second_token = push_disclosure_context("ctx-b")
    try:
        second = facade.search("echo")
        third = facade.search("echo")
    finally:
        reset_disclosure_context(second_token)
    assert "parameters:" in first and "parameters:" in second
    assert "ALREADY AVAILABLE" in third
    assert "ctx-a" in facade._exposed["mcp_echo"]
    assert "ctx-b" in facade._exposed["mcp_echo"]


async def _invoke_search(orchestrator, tool, context_id: str) -> str:
    token = push_disclosure_context(context_id)
    try:
        return await orchestrator._invoke_async(tool, {"query": "echo", "top_k": 5})
    finally:
        reset_disclosure_context(token)


@pytest.mark.asyncio
async def test_orchestrator_async_path_keeps_disclosure_context():
    """同步 tool 会进线程池并丢掉 ContextVar。必须走真实 _invoke_async。"""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    registry = {"mcp_echo": _mcp_write_tool("mcp_echo")}
    facade = DeferredToolSearch(lambda: registry, get_session_id=lambda: "same-session")
    tool = facade.as_tool()
    assert tool.coroutine is not None
    assert tool.name == "tool_search"
    assert tool.description == TOOL_SEARCH_DESCRIPTION
    orchestrator = ToolOrchestrator(max_workers=2, tool_registry=SimpleNamespace())
    try:
        first = await _invoke_search(orchestrator, tool, "ctx-a")
        second = await _invoke_search(orchestrator, tool, "ctx-b")
        third = await _invoke_search(orchestrator, tool, "ctx-b")
        assert "parameters:" in first and "parameters:" in second
        assert "ALREADY AVAILABLE" in third
        assert "session:same-session" not in facade._exposed["mcp_echo"]

        fresh = DeferredToolSearch(lambda: registry, get_session_id=lambda: "same-session")
        fresh_tool = fresh.as_tool()
        concurrent = await asyncio.gather(
            _invoke_search(orchestrator, fresh_tool, "ctx-c"),
            _invoke_search(orchestrator, fresh_tool, "ctx-d"),
        )
        assert all("parameters:" in text for text in concurrent)
        assert "ctx-c" in fresh._exposed["mcp_echo"]
        assert "ctx-d" in fresh._exposed["mcp_echo"]
    finally:
        orchestrator.shutdown_sync_executor(wait=True)


def test_reset_session_rotates_fast_disclosure_without_wiping_other_contexts(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_mod

    monkeypatch.setattr(agent_mod, "clear_session_runtime", lambda _sid: 0)
    monkeypatch.setattr(agent_mod, "clear_session_tasks", lambda _sid: 0)
    monkeypatch.setattr(agent_mod, "clear_session_workflows", lambda _sid: 0)

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "same-session"
    agent._active_task = None
    agent._checkpoint_store = None
    agent._attempt_store = None
    agent._memory = SimpleNamespace(
        long_term=SimpleNamespace(clear_session=lambda: 0),
        experience=SimpleNamespace(delete_session=lambda _sid: 0),
        short_term=SimpleNamespace(clear=lambda: None),
        invalidate_code_context=lambda: None,
    )
    registry = {"mcp_echo": _mcp_write_tool("mcp_echo")}
    agent._tool_search_facade = None
    agent._tool_orchestrator = SimpleNamespace(
        get_all=lambda: dict(registry),
        get=lambda name: registry.get(name),
        register=lambda name, tool, risk=None: registry.__setitem__(name, tool),
    )
    agent._ensure_tool_search_tool()
    facade = agent._tool_search_facade
    first = facade.search("echo")
    repeat = facade.search("echo")
    assert "ALREADY AVAILABLE" in repeat
    token = push_disclosure_context("other-task")
    try:
        other = facade.search("echo")
    finally:
        reset_disclosure_context(token)
    assert "parameters:" in first and "parameters:" in other
    before = agent._disclosure_message_context_id

    result = agent.reset_session()

    assert result["session_id"] == "same-session"
    assert agent._disclosure_message_context_id != before
    again = facade.search("echo")
    assert "parameters:" in again
    assert "ALREADY AVAILABLE" not in again
    token = push_disclosure_context("other-task")
    try:
        other_again = facade.search("echo")
    finally:
        reset_disclosure_context(token)
    assert "ALREADY AVAILABLE" in other_again
    assert "other-task" in facade._exposed["mcp_echo"]


@pytest.mark.asyncio
async def test_deferred_rounds_follow_history_not_a_second_counter():
    tool = _mcp_write_tool("mcp_echo")
    orchestrator = _orch_stub({"mcp_echo": tool})
    middleware = _DeferredEnvelopeDispatchMiddleware(
        orchestrator, {}, round_limit=2
    )
    envelope = '<tool_call>{"name": "mcp_echo", "arguments": {}}</tool_call>'
    first = await middleware.aafter_model(_ai_state(envelope), None)
    assert first is not None and "jump_to" not in first
    assert orchestrator.execute_tool.await_count == 1
    updated = first["messages"][0]
    follow = {
        "messages": [
            HumanMessage(content="task"),
            updated,
            ToolMessage(content="ok", tool_call_id=updated.tool_calls[0]["id"]),
            AIMessage(content=envelope),
        ]
    }
    second = await middleware.aafter_model(follow, None)
    assert second is not None and "jump_to" not in second
    assert orchestrator.execute_tool.await_count == 2
    third_ai = AIMessage(content=envelope)
    third = await middleware.aafter_model(
        {"messages": [*follow["messages"][:3], second["messages"][0], second["messages"][1], third_ai]},
        None,
    )
    assert third.get("jump_to") == "end"
    assert orchestrator.execute_tool.await_count == 2
    chain = [third_ai, *third["messages"]]
    # The returned list replaces/overlays the assistant, then tool results.
    paired = [third["messages"][0], *third["messages"][1:-1]]
    assert tool_pair_integrity(paired) is True
    assert any(isinstance(m, ToolMessage) and "max_tool_rounds" in str(m.content) for m in third["messages"])


def test_pinned_discovery_is_not_prefetched_for_summary():
    from RxyCode.RxyCode1_1_0.core.compaction import plan_compaction

    pinned = ToolMessage(
        content=f"full schema {DISCOVERY_PIN_MARKER}",
        tool_call_id="s1",
        name="tool_search",
    )
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="find a tool"),
        AIMessage(
            content="",
            tool_calls=[{"name": "tool_search", "args": {}, "id": "s1", "type": "tool_call"}],
        ),
        pinned,
    ]
    plan = plan_compaction(
        messages,
        context_window=100,
        reserved=0,
        force=True,
        count=lambda text: max(1, len(text or "")),
    )
    assert plan["rung"] == "fold"
    assert plan["fold_msgs"] == []


def test_k3_2_7_empty_envelope_is_a_parse_error():
    calls, malformed = parse_deferred_tool_json_calls("<tool_call></tool_call>")
    assert len(calls) == 1
    assert calls[0]["id"] in malformed
    assert "empty" in malformed[calls[0]["id"]]


def test_k3_2_7_overflow_and_orphan_do_not_share_an_id():
    closed = "".join(
        f'<tool_call>{{"name": "mcp_{i}", "arguments": {{}}}}</tool_call>'
        for i in range(9)
    )
    calls, malformed = parse_deferred_tool_json_calls(closed + "<tool_call>{")
    ids = [call["id"] for call in calls]
    assert len(ids) == len(set(ids))
    assert len(calls) == 10
    assert sum("unterminated" in text for text in malformed.values()) == 1
    assert sum("limit" in text for text in malformed.values()) == 1


def test_k3_2_7_non_dict_payload_is_malformed_not_final():
    calls, malformed = parse_deferred_tool_json_calls("<tool_call>[]</tool_call>")
    assert calls and all(c["id"] in malformed for c in calls)


@pytest.mark.asyncio
async def test_k3_2_7_graph_mixed_native_and_envelope_explicit_note():
    orchestrator = _orch_stub({})
    middleware = _DeferredEnvelopeDispatchMiddleware(orchestrator, {})
    ai = AIMessage(
        content='先原生再包装 <tool_call>{"name":"mcp_x","arguments":{}}</tool_call>',
        tool_calls=[{"name": "read", "args": {}, "id": "n1", "type": "tool_call"}],
    )
    result = await middleware.aafter_model({"messages": [HumanMessage(content="t"), ai]}, None)
    assert result is None
    assert orchestrator.execute_tool.await_count == 0

    async def handler(_request):
        return ToolMessage(content="file text", tool_call_id="n1", name="read")

    class _Req:
        tool_call = {"name": "read", "id": "n1", "args": {}}

    wrapped = await middleware.awrap_tool_call(_Req(), handler)
    assert isinstance(wrapped, list)
    chain = [ai, *wrapped]
    assert tool_pair_integrity(chain) is True
    assert isinstance(chain[-1], HumanMessage)
    assert "NOT executed" in str(chain[-1].content)
