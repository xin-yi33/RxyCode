"""Execute one task with a bounded ReAct tool loop."""

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.prompts import (
    build_user_message,
    get_role_prompt,
    get_system_prompt,
)
from RxyCode.RxyCode1_1_0.core.providers.responses_adapter import (
    finalize_responses_reasoning_message,
    install_langchain_responses_reasoning_patch,
    native_reasoning_scope,
)
from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.core.state import TaskEffect, TaskNode
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

_logger = logging.getLogger(__name__)

#: Content-block types that carry model chain-of-thought (mirrors
#: agent_v2._THINKING_BLOCK_TYPES; duplicated locally to avoid a circular
#: import — agent_v2 already imports execution.tool_orchestrator).
_THINKING_BLOCK_TYPES = frozenset({"thinking", "reasoning", "reasoning_content"})


def _extract_thinking_from_messages(messages: list) -> list[str]:
    """Collect model chain-of-thought from an ainvoke result message list.

    2026-09-23: the graph/team executor consumes ``agent.ainvoke`` whose
    result messages carry the model's reasoning (DeepSeek/Qwen/Kimi
    ``additional_kwargs.reasoning_content``; Anthropic-style thinking content
    blocks), but only ``content`` was read — the chain silently vanished from
    the TUI (用户报告：thought 不是没有，而是无法导出).  Pure helper, no I/O.
    """
    blocks: list[str] = []
    for message in messages or []:
        if not isinstance(message, AIMessage):
            continue
        extra = getattr(message, "additional_kwargs", None) or {}
        reasoning = extra.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            blocks.append(reasoning)
        content = getattr(message, "content", None)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if str(block.get("type") or "") not in _THINKING_BLOCK_TYPES:
                    continue
                text = block.get("thinking") or block.get("text") or ""
                if isinstance(text, str) and text.strip():
                    blocks.append(text)
    return blocks


_DEFAULT_MAX_TOOL_ROUNDS = 200


def _configured_max_tool_rounds(config: dict) -> int:
    """Return the validated per-task ReAct tool-round budget."""
    execution = config.get("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("execution config must be a mapping")

    raw_value = execution.get("max_tool_rounds", _DEFAULT_MAX_TOOL_ROUNDS)
    if isinstance(raw_value, bool):
        raise ValueError("execution.max_tool_rounds must be a positive integer")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "execution.max_tool_rounds must be a positive integer"
        ) from exc
    if value < 1 or (isinstance(raw_value, float) and not raw_value.is_integer()):
        raise ValueError("execution.max_tool_rounds must be a positive integer")
    return value


def _internal_recursion_limit(max_tool_rounds: int) -> int:
    """Give the child graph headroom without using recursion as its limiter."""
    # A create_agent tool cycle currently traverses model, middleware, and tool
    # nodes. The middleware below is the semantic limit; this separate child
    # graph guard only prevents LangGraph's lower default from stopping first.
    return 4 * (max_tool_rounds + 1) + 4


class _ToolRoundLimitMiddleware(AgentMiddleware):
    """Stop before executing the first tool batch beyond the configured limit."""

    def __init__(self, max_tool_rounds: int):
        super().__init__()
        self.max_tool_rounds = max_tool_rounds

    @hook_config(can_jump_to=["end"])
    def after_model(self, state, runtime):
        messages = state.get("messages", [])
        last_ai_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, AIMessage)
            ),
            None,
        )
        if last_ai_message is None or not last_ai_message.tool_calls:
            return None

        proposed_rounds = sum(
            isinstance(message, AIMessage) and bool(message.tool_calls)
            for message in messages
        )
        if proposed_rounds <= self.max_tool_rounds:
            return None

        blocked_messages = [
            ToolMessage(
                content=(
                    "Tool call blocked: execution.max_tool_rounds "
                    f"is {self.max_tool_rounds}."
                ),
                tool_call_id=str(tool_call.get("id") or f"blocked-{index}"),
                name=tool_call.get("name"),
                status="error",
            )
            for index, tool_call in enumerate(last_ai_message.tool_calls)
        ]
        blocked_messages.append(
            AIMessage(
                content=(
                    "[Executor stopped: tool-round limit reached "
                    f"({self.max_tool_rounds}/{self.max_tool_rounds}).]"
                )
            )
        )
        return {"jump_to": "end", "messages": blocked_messages}

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)


class _ResponsesReasoningMiddleware(AgentMiddleware):
    """Collapse LangChain-merged reasoning before the next Responses request."""

    @staticmethod
    def _finalize(response):
        if isinstance(response, AIMessage):
            return finalize_responses_reasoning_message(response)
        result = getattr(response, "result", None)
        if isinstance(result, list):
            response.result = [
                finalize_responses_reasoning_message(item)
                if isinstance(item, AIMessage)
                else item
                for item in result
            ]
        return response

    def wrap_model_call(self, request, handler):
        install_langchain_responses_reasoning_patch()
        with native_reasoning_scope():
            response = handler(request)
        return self._finalize(response)

    async def awrap_model_call(self, request, handler):
        install_langchain_responses_reasoning_patch()
        with native_reasoning_scope():
            response = await handler(request)
        return self._finalize(response)


class Executor:
    """Run a task with an agent-local tool-round budget.

    ``execution.max_tool_rounds`` is enforced by middleware inside this
    executor. It is independent from the outer Plan-and-Execute graph's
    recursion budget.
    """

    def __init__(
        self,
        llm,
        tool_orchestrator: ToolOrchestrator,
        config: dict | None = None,
        event_tui=None,
    ):
        self._llm = llm
        self._tools = tool_orchestrator
        self._config = config or {}
        self._event_tui = event_tui

    async def execute(self, task: TaskNode, task_context: str = "") -> str:
        result, _ = await self.execute_with_evidence(task, task_context)
        return result

    async def execute_with_evidence(
        self,
        task: TaskNode,
        task_context: str = "",
    ) -> tuple[str, list[dict]]:
        event_token = None
        if self._event_tui is not None:
            event_token = self._tools.bind_event_tui(self._event_tui)
        token = self._tools.begin_evidence_capture()
        try:
            if task.effect == TaskEffect.READ:
                available = self._tools.select_safe_tools(
                    task.tools_hint,
                    self._config,
                    max_risk=RiskLevel.READ,
                )
            else:
                available = self._tools.select_safe_tools(
                    task.tools_hint,
                    self._config,
                )
            tool_names = [getattr(tool, "name", str(tool)) for tool in available]
            task_content = (
                f"Task: {task.title}\n"
                f"Description: {task.description}\n"
                f"Context: {task_context or '(no prior context)'}\n"
                f"Available tools: {', '.join(tool_names)}"
            )
            prompt = build_user_message(get_role_prompt("executor"), task_content)
            max_tool_rounds = _configured_max_tool_rounds(self._config)
            agent = create_agent(
                self._llm,
                available,
                system_prompt=get_system_prompt(),
                middleware=[
                    _ResponsesReasoningMiddleware(),
                    _ToolRoundLimitMiddleware(max_tool_rounds),
                ],
            )
            result = await agent.ainvoke(
                {"messages": [("user", prompt)]},
                {"recursion_limit": _internal_recursion_limit(max_tool_rounds)},
            )
            answer = result["messages"][-1].content
            # 2026-09-23: export chain-of-thought dropped at this non-streaming
            # ainvoke boundary — graph/team turns showed zero Thought rows even
            # though the model reasoned (用户报告：thought 无法导出).  Export is
            # observational only; it must never fail or delay the task.
            if self._event_tui is not None:
                try:
                    thinking_blocks = _extract_thinking_from_messages(
                        result.get("messages") or []
                    )
                    write_reasoning = getattr(
                        self._event_tui, "write_reasoning", None
                    )
                    if callable(write_reasoning):
                        for block in thinking_blocks:
                            write_reasoning(block)
                except Exception as exc:  # pragma: no cover - defensive
                    _logger.warning("thinking export failed (ignored): %s", exc)
        finally:
            evidence = self._tools.end_evidence_capture(token)
            if event_token is not None:
                self._tools.reset_event_tui(event_token)
        return str(answer), [item.model_dump() for item in evidence]
