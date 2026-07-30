"""Execute one task with a bounded ReAct tool loop."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.prompts import (
    build_user_message,
    get_role_prompt,
    get_system_prompt,
)
from RxyCode.RxyCode1_1_0.core.state import TaskNode
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator


_DEFAULT_MAX_TOOL_ROUNDS = 10


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
            from RxyCode.RxyCode1_1_0.core.state import TaskEffect
            from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

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
                middleware=[_ToolRoundLimitMiddleware(max_tool_rounds)],
            )
            result = await agent.ainvoke(
                {"messages": [("user", prompt)]},
                {"recursion_limit": _internal_recursion_limit(max_tool_rounds)},
            )
            answer = result["messages"][-1].content
        finally:
            evidence = self._tools.end_evidence_capture(token)
            if event_token is not None:
                self._tools.reset_event_tui(event_token)
        return str(answer), [item.model_dump() for item in evidence]
