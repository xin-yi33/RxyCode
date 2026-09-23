"""2026-09-23: graph/team executor must export model chain-of-thought.

用户报告：Build/团队轮次 thought 不是没有，而是无法导出。根因：
``execution/executor.py`` 走非流式 ``agent.ainvoke``，结果消息里的
reasoning（DeepSeek/Qwen/Kimi ``additional_kwargs.reasoning_content``、
Anthropic 风格 thinking content blocks）被丢弃，只读了 ``content``。
修复后经 ``event_tui.write_reasoning`` 导出到会话 TUI。
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.state import TaskNode
from RxyCode.RxyCode1_1_0.execution.executor import (
    Executor,
    _extract_thinking_from_messages,
)


class _ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _OrchestratorStub:
    def select_safe_tools(self, hints, config, **kwargs):
        return []

    def bind_event_tui(self, tui):
        return object()

    def reset_event_tui(self, token):
        return None

    def begin_evidence_capture(self):
        return object()

    def end_evidence_capture(self, token):
        return []


class _RecordingTui:
    def __init__(self):
        self.reasoning: list[str] = []

    def write_reasoning(self, text: str) -> None:
        self.reasoning.append(str(text))


# ---------------------------------------------------------------------------
# 纯函数提取
# ---------------------------------------------------------------------------


def test_extract_reasoning_content_str():
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="答案", additional_kwargs={"reasoning_content": "先分析"}),
    ]
    assert _extract_thinking_from_messages(messages) == ["先分析"]


def test_extract_anthropic_thinking_blocks():
    messages = [
        AIMessage(
            content=[
                {"type": "thinking", "thinking": "检查边界条件"},
                {"type": "text", "text": "答案"},
            ]
        ),
    ]
    assert _extract_thinking_from_messages(messages) == ["检查边界条件"]


def test_extract_skips_non_ai_and_empty():
    messages = [
        ToolMessage(content="ok", tool_call_id="1"),
        AIMessage(content="无思维链"),
        AIMessage(content="x", additional_kwargs={"reasoning_content": "  "}),
    ]
    assert _extract_thinking_from_messages(messages) == []
    assert _extract_thinking_from_messages([]) == []
    assert _extract_thinking_from_messages(None) == []


# ---------------------------------------------------------------------------
# 端到端：Executor 经 event_tui 导出
# ---------------------------------------------------------------------------


async def test_executor_exports_thinking_to_event_tui():
    response = AIMessage(
        content="最终答案",
        additional_kwargs={"reasoning_content": "先拆解需求，再实现"},
    )
    model = _ToolCallingModel(responses=[response])
    tui = _RecordingTui()
    executor = Executor(model, _OrchestratorStub(), config={}, event_tui=tui)

    answer, _evidence = await executor.execute_with_evidence(
        TaskNode(title="t", description="d"), ""
    )

    assert answer == "最终答案"
    assert tui.reasoning == ["先拆解需求，再实现"]


async def test_executor_without_reasoning_exports_nothing():
    model = _ToolCallingModel(responses=[AIMessage(content="普通回答")])
    tui = _RecordingTui()
    executor = Executor(model, _OrchestratorStub(), config={}, event_tui=tui)

    answer, _ = await executor.execute_with_evidence(TaskNode(title="t"), "")

    assert answer == "普通回答"
    assert tui.reasoning == []


async def test_executor_no_event_tui_never_breaks():
    """无 event_tui（旧调用方）时导出逻辑完全不触发，任务照常完成。"""
    model = _ToolCallingModel(
        responses=[
            AIMessage(
                content="ok", additional_kwargs={"reasoning_content": "内部推理"}
            )
        ]
    )
    executor = Executor(model, _OrchestratorStub(), config={})
    answer, _ = await executor.execute_with_evidence(TaskNode(title="t"), "")
    assert answer == "ok"
