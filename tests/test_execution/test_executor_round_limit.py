"""Tests for the executor-local ReAct tool-round budget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

import RxyCode.RxyCode1_1_0.execution.executor as executor_module
from RxyCode.RxyCode1_1_0.core.state import TaskNode
from RxyCode.RxyCode1_1_0.execution.executor import (
    Executor,
    _configured_max_tool_rounds,
    _internal_recursion_limit,
)


class _ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _OrchestratorStub:
    def __init__(self, tools):
        self.tools = tools

    def select_safe_tools(self, hints, config):
        return self.tools

    def begin_evidence_capture(self):
        return object()

    def end_evidence_capture(self, token):
        return []


def _tool_call(call_id: str, value: int) -> dict:
    return {
        "name": "record_value",
        "args": {"value": value},
        "id": call_id,
        "type": "tool_call",
    }


def _recording_tool(calls: list[int]) -> StructuredTool:
    def record_value(value: int) -> str:
        """Record a value for the test."""
        calls.append(value)
        return str(value)

    return StructuredTool.from_function(record_value)


def _executor(responses, calls, max_tool_rounds: int) -> Executor:
    model = _ToolCallingModel(responses=responses)
    orchestrator = _OrchestratorStub([_recording_tool(calls)])
    return Executor(
        model,
        orchestrator,
        config={"execution": {"max_tool_rounds": max_tool_rounds}},
    )


@pytest.mark.asyncio
async def test_executor_stops_before_tool_batch_beyond_configured_limit():
    calls: list[int] = []
    executor = _executor(
        [
            AIMessage(content="", tool_calls=[_tool_call("call-1", 1)]),
            AIMessage(content="", tool_calls=[_tool_call("call-2", 2)]),
            AIMessage(content="", tool_calls=[_tool_call("call-3", 3)]),
            AIMessage(content="unreachable"),
        ],
        calls,
        max_tool_rounds=2,
    )

    result = await executor.execute(TaskNode(title="bounded task"))

    assert calls == [1, 2]
    assert result == "[Executor stopped: tool-round limit reached (2/2).]"


@pytest.mark.asyncio
async def test_parallel_tool_calls_count_as_one_tool_round():
    calls: list[int] = []
    executor = _executor(
        [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call("parallel-1", 1),
                    _tool_call("parallel-2", 2),
                ],
            ),
            AIMessage(content="", tool_calls=[_tool_call("blocked", 3)]),
        ],
        calls,
        max_tool_rounds=1,
    )

    result = await executor.execute(TaskNode(title="parallel task"))

    assert sorted(calls) == [1, 2]
    assert result == "[Executor stopped: tool-round limit reached (1/1).]"


@pytest.mark.asyncio
async def test_executor_returns_normal_answer_before_round_limit():
    calls: list[int] = []
    executor = _executor(
        [
            AIMessage(content="", tool_calls=[_tool_call("call-1", 1)]),
            AIMessage(content="completed normally"),
        ],
        calls,
        max_tool_rounds=2,
    )

    result = await executor.execute(TaskNode(title="normal task"))

    assert calls == [1]
    assert result == "completed normally"


@pytest.mark.asyncio
async def test_executor_wires_config_to_agent_local_limit(monkeypatch):
    graph = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value={"messages": [AIMessage(content="completed")]}
        )
    )
    create_agent = MagicMock(return_value=graph)
    monkeypatch.setattr(executor_module, "create_agent", create_agent)
    orchestrator = _OrchestratorStub([])
    executor = Executor(
        object(),
        orchestrator,
        config={"execution": {"max_tool_rounds": 3}},
    )

    result = await executor.execute(TaskNode(title="configured task"))

    assert result == "completed"
    middleware = create_agent.call_args.kwargs["middleware"]
    assert len(middleware) == 1
    assert middleware[0].max_tool_rounds == 3
    invocation_config = graph.ainvoke.await_args.args[1]
    assert invocation_config == {"recursion_limit": _internal_recursion_limit(3)}


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 10),
        ({"execution": {}}, 10),
        ({"execution": {"max_tool_rounds": 1}}, 1),
        ({"execution": {"max_tool_rounds": "4"}}, 4),
    ],
)
def test_max_tool_round_config_boundaries(config, expected):
    assert _configured_max_tool_rounds(config) == expected


@pytest.mark.parametrize(
    "config",
    [
        {"execution": None},
        {"execution": {"max_tool_rounds": 0}},
        {"execution": {"max_tool_rounds": -1}},
        {"execution": {"max_tool_rounds": True}},
        {"execution": {"max_tool_rounds": 1.5}},
        {"execution": {"max_tool_rounds": "invalid"}},
        {"execution": {"max_tool_rounds": None}},
    ],
)
def test_invalid_max_tool_round_config_fails_closed(config):
    with pytest.raises(ValueError, match="positive integer|must be a mapping"):
        _configured_max_tool_rounds(config)
