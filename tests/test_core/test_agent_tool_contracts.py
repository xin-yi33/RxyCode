"""Regression tests for AgentV2 tool routing and failure boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


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
    agent._session_id = "tool-contract-test"
    agent._memory = _Memory()
    agent._llm = None
    agent._tool_orchestrator = None
    agent._tool_tracer = None
    agent._thinking_history = []
    agent._last_thinking = ""
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._is_simple_query = MagicMock(return_value=False)
    agent._should_use_subagents = MagicMock(return_value=False)
    agent._fast_reply = AsyncMock(return_value="unsafe fallback")
    agent._fast_reply_with_tools = AsyncMock(return_value="fast answer")
    agent._graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"final_response": "graph answer"})
    )
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_name", "expected_args"),
    [
        ({"op": "list", "path": "C:/work"}, "ls", {"path": "C:/work"}),
        (
            {"op": "read", "path": "C:/work/a.txt"},
            "read",
            {"filePath": "C:/work/a.txt"},
        ),
        (
            {"op": "write", "path": "C:/work/a.txt", "content": "hello"},
            "write",
            {"filePath": "C:/work/a.txt", "content": "hello"},
        ),
    ],
)
async def test_direct_file_operations_use_the_unified_tool_entry(
    operation, expected_name, expected_args
):
    agent = object.__new__(AgentV2)
    agent._execute_tool = AsyncMock(return_value="tool result")

    result = await agent._handle_file_operation(operation, mode="build")

    assert result == "tool result"
    agent._execute_tool.assert_awaited_once_with(expected_name, expected_args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "write file C:/work/a.txt content: hello",
        "run bash command: echo hello",
        "download https://example.test/archive.zip",
    ],
)
async def test_plan_mode_is_globally_non_executing(prompt):
    agent = _run_agent()
    agent._run_plan_only = AsyncMock(return_value="plan-only answer")
    agent._execute_tool = AsyncMock(return_value="[blocked]")

    result = await agent.run(prompt, mode="plan")

    assert result == "plan-only answer"
    agent._run_plan_only.assert_awaited_once_with(prompt)
    agent._execute_tool.assert_not_awaited()
    agent._fast_reply_with_tools.assert_not_awaited()
    agent._graph.ainvoke.assert_not_awaited()
    agent._detect_file_operation.assert_not_called()
    agent._detect_download_intent.assert_not_called()


@pytest.mark.asyncio
async def test_plan_only_exposes_readonly_tools_and_executes_read(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.tools.registry import registry

    agent = _run_agent()
    agent._fast_reply_with_tools = AgentV2._fast_reply_with_tools.__get__(
        agent, AgentV2
    )
    tools = [
        SimpleNamespace(name="read"),
        SimpleNamespace(name="ls"),
        SimpleNamespace(name="bash"),
        SimpleNamespace(name="download_file"),
    ]
    agent._get_core_tools = MagicMock(return_value=tools)
    config = {"execution": {"tool_timeout_seconds": 0}}
    orchestrated = AsyncMock(return_value="file contents")
    monkeypatch.setattr(settings, "load_config", lambda: config)
    monkeypatch.setattr(registry, "get", MagicMock(return_value=object()))
    agent._tool_orchestrator = SimpleNamespace(execute_tool=orchestrated)
    agent._tool_tracer = MagicMock()
    agent._execute_tool = AgentV2._execute_tool.__get__(agent, AgentV2)
    agent._llm = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(content="tool-free implementation")
        )
    )
    bound_names = []
    calls = 0

    async def raw_stream(_messages, bound_tools=None):
        nonlocal calls
        calls += 1
        bound_names.append([tool.name for tool in (bound_tools or [])])
        if calls == 1:
            tool_call = SimpleNamespace(
                index=0,
                id="read-1",
                function=SimpleNamespace(
                    name="read",
                    arguments='{"filePath":"notes.txt"}',
                ),
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="", reasoning_content="", tool_calls=[tool_call]
                ))],
                usage=None,
            )
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="plan complete", reasoning_content="", tool_calls=None
                ))],
                usage=None,
            )

    agent._raw_stream = raw_stream

    result = await agent._run_plan_only("inspect notes.txt and make a plan")

    assert result.startswith("plan complete")
    assert "切换到 **Build**" in result or "switch to **Build**" in result
    assert bound_names == [["read", "ls"], ["read", "ls"]]
    orchestrated.assert_awaited_once_with(
        "read",
        {"filePath": "notes.txt"},
        config=config,
        mode="plan",
        call_id="read-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["write", "bash", "download_file", "open_file"])
async def test_plan_only_rejects_unexposed_tool_calls(tool_name, monkeypatch):
    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_v2_module

    agent = _run_agent()
    agent._fast_reply_with_tools = AgentV2._fast_reply_with_tools.__get__(
        agent, AgentV2
    )
    tools = [SimpleNamespace(name="read"), SimpleNamespace(name=tool_name)]
    agent._get_core_tools = MagicMock(return_value=tools)
    agent._execute_tool = AsyncMock(return_value="must not run")
    agent._llm = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="tool-free"))
    )
    tui = MagicMock()
    monkeypatch.setattr(agent_v2_module, "get_tui", lambda: tui)
    bound_names = []
    calls = 0

    async def raw_stream(_messages, bound_tools=None):
        nonlocal calls
        calls += 1
        bound_names.append([tool.name for tool in (bound_tools or [])])
        if calls == 1:
            tool_call = SimpleNamespace(
                index=0,
                id="blocked-1",
                function=SimpleNamespace(name=tool_name, arguments="{}"),
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="", reasoning_content="", tool_calls=[tool_call]
                ))],
                usage=None,
            )
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="plan complete", reasoning_content="", tool_calls=None
                ))],
                usage=None,
            )

    agent._raw_stream = raw_stream

    result = await agent._run_plan_only("make a plan")

    assert result.startswith("plan complete")
    assert "切换到 **Build**" in result or "switch to **Build**" in result
    assert all(tool_name not in names for names in bound_names)
    agent._execute_tool.assert_awaited_once_with(
        tool_name,
        {},
        mode="plan",
        call_id="blocked-1",
    )


def _tool_agent(monkeypatch, execute_tool, config):
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.tools.registry import registry

    monkeypatch.setattr(settings, "load_config", lambda: config)
    monkeypatch.setattr(registry, "get", MagicMock(return_value=object()))
    agent = object.__new__(AgentV2)
    agent._tool_tracer = None
    agent._tool_orchestrator = SimpleNamespace(execute_tool=execute_tool)
    return agent


@pytest.mark.asyncio
async def test_zero_tool_timeout_does_not_install_a_unified_deadline(monkeypatch):
    execute_tool = AsyncMock(return_value="ok")
    agent = _tool_agent(
        monkeypatch,
        execute_tool,
        {"execution": {"tool_timeout_seconds": 0}},
    )
    wait_for = MagicMock(side_effect=AssertionError("wait_for must not be used"))
    monkeypatch.setattr(asyncio, "wait_for", wait_for)

    result = await agent._execute_tool("read", {"filePath": "a.txt"})

    assert result == "ok"
    execute_tool.assert_awaited_once()
    wait_for.assert_not_called()


@pytest.mark.asyncio
async def test_positive_tool_timeout_is_owned_by_orchestrator(monkeypatch):
    timeout_result = "[error: tool 'read' timed out after 0.01s]"
    execute_tool = AsyncMock(return_value=timeout_result)
    config = {"execution": {"tool_timeout_seconds": 0.01}}
    agent = _tool_agent(
        monkeypatch,
        execute_tool,
        config,
    )
    wait_for = MagicMock(side_effect=AssertionError("AgentV2 must not install a deadline"))
    monkeypatch.setattr(asyncio, "wait_for", wait_for)

    result = await agent._execute_tool("read", {"filePath": "a.txt"})

    assert result == timeout_result
    execute_tool.assert_awaited_once_with(
        "read",
        {"filePath": "a.txt"},
        config=config,
    )
    wait_for.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_timeout_has_one_failed_correlated_lifecycle(
    monkeypatch, tmp_path
):
    import json

    from langchain_core.tools import StructuredTool

    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_module
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.core.safety.audit import AuditLogger
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.registry import registry

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def wait_forever(filePath: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return filePath

    raw_tool = StructuredTool.from_function(
        coroutine=wait_forever,
        name="read",
        description="Cancellable read",
    )
    audit_path = tmp_path / "audit.jsonl"
    orchestrator = ToolOrchestrator()
    orchestrator.register("read", raw_tool)
    orchestrator.set_audit_logger(AuditLogger(path=audit_path))
    config = {
        "execution": {"tool_timeout_seconds": 0.01},
        "safety": {"enabled": False},
    }
    monkeypatch.setattr(settings, "load_config", lambda: config)
    monkeypatch.setattr(registry, "get", MagicMock(return_value=raw_tool))

    events = []

    class EventSink:
        def write_tool_call(self, name, args, call_id=None):
            events.append(("call", call_id, name, args))
            return call_id

        def write_tool_result(self, result, status, call_id=None):
            events.append(("result", call_id, status, result))

    monkeypatch.setattr(agent_module, "get_tui", lambda: EventSink())
    agent = _run_agent()
    agent._tool_orchestrator = orchestrator

    evidence_token = orchestrator.begin_evidence_capture()
    try:
        result = await agent._execute_tool(
            "read",
            {"filePath": "a.txt"},
            call_id="fast-call-1",
        )
    finally:
        evidence = orchestrator.end_evidence_capture(evidence_token)

    expected = "[error: tool 'read' timed out after 0.01s]"
    assert started.is_set()
    assert cancelled.is_set()
    assert result == expected
    assert events == [
        ("call", "fast-call-1", "read", {"filePath": "a.txt"}),
        ("result", "fast-call-1", "timeout", expected),
    ]
    assert len(evidence) == 1
    assert evidence[0].status == "failed"
    assert evidence[0].executed is True
    assert evidence[0].detail == expected
    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["approval"] == "safety_disabled"
    assert records[0]["result"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected_span_status"),
    [
        ("tool output", "ok"),
        ("[blocked: write path not allowed]", "error"),
        ("[rejected by user: write]", "error"),
        ("[dry-run] write was not executed", "error"),
        ("[error executing read: boom]", "error"),
        ("[error: formatter timed out (30s)]", "timeout"),
        ("[workflow cancelled]", "cancelled"),
    ],
)
async def test_tool_return_value_sets_truthful_span_status(
    monkeypatch, result, expected_span_status
):
    execute_tool = AsyncMock(return_value=result)
    agent = _tool_agent(
        monkeypatch,
        execute_tool,
        {"execution": {"tool_timeout_seconds": 0}},
    )
    tracer = MagicMock()
    span = object()
    tracer.start_span.return_value = span
    agent._tool_tracer = tracer

    actual = await agent._execute_tool("read", {"filePath": "a.txt"})

    assert actual == result
    tracer.end_span.assert_called_once()
    assert tracer.end_span.call_args.args[0] is span
    assert tracer.end_span.call_args.kwargs["status"] == expected_span_status


@pytest.mark.asyncio
async def test_tool_cancellation_propagates_to_the_caller(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def cancellable(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    agent = _tool_agent(
        monkeypatch,
        cancellable,
        {"execution": {"tool_timeout_seconds": 0}},
    )
    task = asyncio.create_task(agent._execute_tool("read", {"filePath": "a.txt"}))
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


def test_legacy_code_extraction_has_no_filesystem_or_open_side_effects(
    tmp_path, monkeypatch
):
    import os

    from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_and_save_code

    output_dir = tmp_path / "output"
    opener = MagicMock()
    monkeypatch.setenv("RXYCODE_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(os, "startfile", opener, raising=False)

    result = _extract_and_save_code(
        "```python\ndef build_value():\n    return 42\n```",
        "write me a Python file",
    )

    assert result is None
    assert not output_dir.exists()
    opener.assert_not_called()


@pytest.mark.asyncio
async def test_agent_cancel_cancels_the_active_plan_await():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    agent = _run_agent()

    async def plan_only(_prompt):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    agent._run_plan_only = plan_only
    task = asyncio.create_task(agent.run("make a plan", mode="plan"))
    await started.wait()

    assert agent.cancel() is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled.is_set()
    assert agent._active_task is None


@pytest.mark.asyncio
async def test_agent_cancel_cleans_up_the_active_graph_task(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def graph_run(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {"execution": {"heartbeat_interval_seconds": 0.1}},
    )
    agent = _run_agent()
    agent._graph.ainvoke = graph_run
    task = asyncio.create_task(agent.run("perform a complex build", mode="build"))
    await started.wait()

    assert agent.cancel() is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled.is_set()
    assert agent._active_task is None


@pytest.mark.asyncio
async def test_explicit_parallel_build_uses_validated_graph_not_legacy_subagents(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {"execution": {"heartbeat_interval_seconds": 0.1}},
    )
    agent = _run_agent()
    agent._should_use_subagents.return_value = True
    agent._run_with_subagents = AsyncMock(side_effect=AssertionError("legacy bypass"))

    result = await agent.run(
        "analyze these modules in parallel and report the results",
        mode="build",
    )

    assert result == "graph answer"
    agent._run_with_subagents.assert_not_awaited()
    initial_state = agent._graph.ainvoke.await_args.args[0]
    assert initial_state["parallel_requested"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "expected_name", "expected_args"),
    [
        (
            ("file", "https://example.test/archive.zip", ""),
            "download_file",
            {"url": "https://example.test/archive.zip"},
        ),
        (("skill", "coding-workflow", ""), "download_skill", {"name": "coding-workflow"}),
        (
            ("mcp", "filesystem", "@modelcontextprotocol/server-filesystem"),
            "download_mcp",
            {
                "name": "filesystem",
                "package": "@modelcontextprotocol/server-filesystem",
            },
        ),
    ],
)
async def test_download_intents_use_registered_tools(intent, expected_name, expected_args):
    agent = object.__new__(AgentV2)
    agent._execute_tool = AsyncMock(return_value="downloaded")

    result = await agent._handle_download_intent(intent)

    assert result == "downloaded"
    agent._execute_tool.assert_awaited_once_with(expected_name, expected_args)


@pytest.mark.asyncio
async def test_side_effecting_fast_path_failure_does_not_start_graph_fallback():
    agent = _run_agent()
    agent._is_simple_query.return_value = True

    async def fail_after_write(_user_input):
        agent._side_effecting_tool_attempted = True
        raise RuntimeError("stream failed after write")

    agent._fast_reply_with_tools = AsyncMock(side_effect=fail_after_write)

    result = await agent.run("summarize and save the result", mode="build")

    assert "not repeated" in result.lower()
    assert "stream failed after write" in result
    agent._graph.ainvoke.assert_not_awaited()
    agent._fast_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_fast_path_side_effect_claim_without_tool_evidence_fails_closed(
    isolated_runtime,
):
    agent = _run_agent()
    agent._is_simple_query.return_value = True
    agent._fast_reply_with_tools = AsyncMock(
        return_value="Implemented authentication successfully."
    )

    result = await agent.run("Implement authentication", mode="build")

    assert result.startswith("[evidence failed:")
    assert agent._last_evidence == []
    assert agent._last_failure_attribution == {"verification_error": 1}
    agent._fast_reply_with_tools.assert_awaited_once_with("Implement authentication")
    agent._graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Who built the Eiffel Tower?", "Built by Gustave Eiffel's company."),
        ("Which tasks are completed?", "Completed tasks: documentation."),
    ],
)
async def test_fast_path_readonly_answers_are_not_upgraded_to_side_effects(
    isolated_runtime,
    question,
    answer,
):
    agent = _run_agent()
    agent._is_simple_query.return_value = True
    agent._fast_reply_with_tools = AsyncMock(return_value=answer)

    result = await agent.run(question, mode="build")

    assert result == answer
    assert agent._last_evidence == []
    assert agent._last_failure_attribution == {}


@pytest.mark.asyncio
async def test_fast_path_read_composite_evidence_cannot_prove_side_effect(
    isolated_runtime,
):
    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    async def search_memory(operation: str = "search") -> str:
        return f"memory {operation} complete"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "memory",
        StructuredTool.from_function(
            coroutine=search_memory,
            name="memory",
            description="Search memory",
        ),
    )
    agent = _run_agent()
    agent._is_simple_query.return_value = True

    async def scripted_fast_path(_user_input: str) -> str:
        await orchestrator.execute_tool(
            "memory",
            {"operation": "search"},
            config={"safety": {"enabled": False}},
        )
        return "Implemented authentication successfully."

    agent._fast_reply_with_tools = AsyncMock(side_effect=scripted_fast_path)

    result = await agent.run("Implement authentication", mode="build")

    assert result.startswith("[evidence failed:")
    assert agent._last_evidence[0]["tool"] == "memory"
    assert agent._last_evidence[0]["risk"] == "READ"
    assert agent._last_failure_attribution == {"verification_error": 1}


@pytest.mark.asyncio
async def test_fast_path_verified_write_evidence_allows_side_effect_result(
    isolated_runtime,
    tmp_path,
):
    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    target = tmp_path / "authentication.txt"

    async def write_file(filePath: str, content: str) -> str:
        Path(filePath).write_text(content, encoding="utf-8")
        return f"written: {filePath}"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "write",
        StructuredTool.from_function(
            coroutine=write_file,
            name="write",
            description="Write a file",
        ),
    )
    agent = _run_agent()
    agent._is_simple_query.return_value = True

    async def scripted_fast_path(_user_input: str) -> str:
        await orchestrator.execute_tool(
            "write",
            {"filePath": str(target), "content": "enabled=true"},
            config={"safety": {"enabled": False}},
        )
        return "Implemented authentication successfully."

    agent._fast_reply_with_tools = AsyncMock(side_effect=scripted_fast_path)

    result = await agent.run("Implement authentication", mode="build")

    assert result == "Implemented authentication successfully."
    assert target.read_text(encoding="utf-8") == "enabled=true"
    assert agent._last_evidence[0]["tool"] == "write"
    assert agent._last_evidence[0]["risk"] == "WRITE"
    assert agent._last_failure_attribution == {}


@pytest.mark.asyncio
async def test_graph_exception_never_calls_tool_free_fallback(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {"execution": {"heartbeat_interval_seconds": 0.1}},
    )
    agent = _run_agent()
    agent._graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph exploded"))

    result = await agent.run("perform a complex build", mode="build")

    assert "graph exploded" in result
    assert "not repeated" in result.lower()
    agent._fast_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_graph_final_never_calls_tool_free_fallback(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {"execution": {"heartbeat_interval_seconds": 0.1}},
    )
    agent = _run_agent()
    agent._graph.ainvoke = AsyncMock(return_value={"final_response": None})

    result = await agent.run("perform a complex build", mode="build")

    assert "no final response" in result.lower()
    assert "not repeated" in result.lower()
    agent._fast_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_run_surfaces_failed_artifact_evidence(tmp_path):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor

    class WriteArgs(BaseModel):
        filePath: str
        content: str

    def write_invalid_html(filePath: str, content: str) -> str:
        Path(filePath).write_text(content, encoding="utf-8")
        return f"written: {filePath}"

    target = tmp_path / "broken.html"
    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "write",
        StructuredTool.from_function(
            func=write_invalid_html,
            name="write",
            description="Write an HTML artifact",
            args_schema=WriteArgs,
        ),
    )
    agent = _run_agent()
    agent._tool_orchestrator = orchestrator

    async def direct_run(_user_input, _mode):
        return await orchestrator.execute_tool(
            "write",
            {"filePath": str(target), "content": "<div>broken</div>"},
            config={"safety": {"enabled": False}},
        )

    agent._run_impl = AsyncMock(side_effect=direct_run)
    result = await agent.run("write invalid HTML", mode="build")
    snapshot = run_monitor.snapshot()

    assert result.startswith("[evidence failed:")
    assert agent._last_evidence[0]["status"] == "failed"
    assert snapshot["total_runs"] == 1
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["tool_evidence"] == {"total": 1, "failed": 1}
    assert snapshot["artifact_evidence"] == {"total": 1, "failed": 1}
