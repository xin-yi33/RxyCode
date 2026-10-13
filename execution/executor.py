"""Execute one task with a bounded ReAct tool loop."""

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
from RxyCode.RxyCode1_1_0.core.safety.policy import (
    RiskLevel,
    canonical_tool_name,
    get_tool_risk,
)
from RxyCode.RxyCode1_1_0.core.state import TaskEffect, TaskNode
from RxyCode.RxyCode1_1_0.core.tool_search import (
    TOOL_SEARCH_NAME,
    current_disclosure_context_id,
    is_deferred_tool,
    parse_deferred_tool_json_calls,
    push_disclosure_context,
    release_finished_disclosure_context,
    reset_disclosure_context,
)
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


class _DeferredEnvelopeDispatchMiddleware(AgentMiddleware):
    """2026-10-13 K例复审（P2c）：Graph 路径与 Fast 同层——

    * request schema 冻结（executor 侧已筛走 deferred 工具）；
    * 模型对 tool_search 发现的工具输出的 ``<tool_call>``自由形式，在这里
      解析成 dispatch 并经**同一个 orchestrator** 执行（审批/风险/journal
      与 fast 路径一致，不经 ToolNode）；
    * 结果以 ToolMessage 追加；AIMessage 以同 id 更新（add_messages reducer
      同 id 覆盖）把 tool_calls 骨架补上，保持 OpenAI 消息配对有效；
    * ID 用中间件构件序号，跨轮唯一。
    """

    def __init__(
        self,
        orchestrator: ToolOrchestrator,
        config: dict | None = None,
        *,
        max_risk: RiskLevel | None = None,
        round_limit: int | None = None,
    ):
        """#1：max_risk 是子任务只读边界（READ 任务拒绝 WRITE/DANGER envelope）。

        #2：round_limit 与原生一致——执行**前**检查，不允许"先执行再补拒"。"""
        super().__init__()
        self._tools = orchestrator
        self._config = config or {}
        self._max_risk = max_risk
        self._round_limit = round_limit
        self._seq = 0
        self._mixed_hint: str | None = None
        self._mixed_last_call_id: str | None = None

    def after_model(self, state, runtime):
        # 同步路径不被 Executor 的 ainvoke 使用；若误用于 sync 图，显式放行
        # 原生执行，绝不静默吞 envelope。
        return None

    def _deferred_gate_reason(self, name: str) -> str | None:
        """#1：envelope 执行前套用子任务权限约束；无限制时全放行。"""
        if self._max_risk is None:
            return None
        canonical = canonical_tool_name(name)
        risk = max(
            get_tool_risk(canonical),
            self._tools._risk_overrides.get(canonical, RiskLevel.READ),
        )
        if risk > self._max_risk:
            return (
                f"[deferred gate] READ-only task: tool {name!r} is {risk.name} "
                "and was NOT executed"
            )
        return None

    async def aafter_model(self, state, runtime):
        messages = state.get("messages", [])
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            None,
        )
        if last_ai is None:
            return None
        content = last_ai.content
        text = content if isinstance(content, str) else str(content or "")
        has_envelope = "<tool_call" in text
        if last_ai.tool_calls:
            # 混合调用：先让原生 tool_calls 执行。提示放在那些结果之后，
            # 不能插在 assistant 和 ToolMessage 中间，否则消息对不合法。
            if has_envelope:
                ids = [
                    c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                    for c in last_ai.tool_calls
                ]
                ids = [str(item) for item in ids if item]
                self._mixed_last_call_id = ids[-1] if ids else None
                self._mixed_hint = (
                    "[protocol] <tool_call> envelopes in a reply that "
                    "ALSO contains native tool calls were NOT executed; "
                    "re-emit the envelope as the only tool call(s) of "
                    "a round."
                )
            return None
        if not has_envelope:
            return None

        calls, bad = parse_deferred_tool_json_calls(text, start=self._seq)
        self._seq += len(calls)
        if not calls:
            return None

        # 回合数只数历史里已经带 tool_calls 的 AIMessage。当前这条 envelope
        # 还没补进历史，只再加 1。补进之后下一轮自然计到，不再另记一份。
        rounds_used = sum(
            1
            for m in messages
            if isinstance(m, AIMessage) and bool(getattr(m, "tool_calls", None))
        )
        call_skeletons = [
            {"name": c["name"], "args": c["args"], "id": c["id"], "type": "tool_call"}
            for c in calls
        ]
        if self._round_limit is not None and rounds_used + 1 > self._round_limit:
            blocked = [
                ToolMessage(
                    content=(
                        "Tool call blocked: execution.max_tool_rounds "
                        f"is {self._round_limit}."
                    ),
                    tool_call_id=str(call["id"]),
                    name=call.get("name"),
                    status="error",
                )
                for call in calls
            ]
            blocked.append(
                AIMessage(
                    content=(
                        "[Executor stopped: tool-round limit reached "
                        f"({self._round_limit}/{self._round_limit}).]"
                    )
                )
            )
            return {
                "jump_to": "end",
                "messages": [self._with_tool_calls(last_ai, call_skeletons), *blocked],
            }

        result_messages: list = []
        for call in calls:
            call_id = call["id"]
            if call_id in bad:
                result_messages.append(
                    ToolMessage(
                        content=f"[tool argument parse error] {bad[call_id]}",
                        tool_call_id=call_id,
                        status="error",
                    )
                )
                continue
            name = call["name"]
            gate_reason = self._deferred_gate_reason(name)
            if gate_reason is not None:
                # #1：任务约束拒绝；不改变工具本身在全局层级的风险分类。
                result_messages.append(
                    ToolMessage(
                        content=gate_reason,
                        tool_call_id=call_id,
                        status="error",
                    )
                )
                continue
            if self._tools.get(name) is None:
                result_messages.append(
                    ToolMessage(
                        content=(
                            f"[error] unknown or un-registered tool {name!r}. "
                            "Call tool_search first for the exact name and schema."
                        ),
                        tool_call_id=call_id,
                        status="error",
                    )
                )
                continue
            try:
                outcome = await self._tools.execute_tool(
                    name,
                    call["args"],
                    config=self._config,
                    mode=(
                        "plan"
                        if self._max_risk is not None and self._max_risk <= RiskLevel.READ
                        else "build"
                    ),
                    call_id=call_id,
                )
                result_messages.append(
                    ToolMessage(content=str(outcome), tool_call_id=call_id)
                )
            except Exception as exc:  # 失败不静默——进轨迹继续下一轮
                result_messages.append(
                    ToolMessage(
                        content=f"[error: {exc}]",
                        tool_call_id=call_id,
                        status="error",
                    )
                )

        # LangChain 消息契约：工具结果必须跟在带 tool_calls 的 assistant 后。
        # add_messages reducer 同 id 覆盖 → 把 skeleton 补回 AI 消息。
        return {
            "messages": [
                self._with_tool_calls(last_ai, call_skeletons),
                *result_messages,
            ]
        }

    @staticmethod
    def _with_tool_calls(message, skeletons: list) -> AIMessage:
        try:
            return message.model_copy(update={"tool_calls": skeletons})
        except Exception:
            return message

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        call_id = str((getattr(request, "tool_call", None) or {}).get("id") or "")
        if (
            self._mixed_hint
            and call_id
            and call_id == self._mixed_last_call_id
        ):
            hint = self._mixed_hint
            self._mixed_hint = None
            self._mixed_last_call_id = None
            note = HumanMessage(content=hint)
            if isinstance(result, list):
                return [*result, note]
            return [result, note]
        return result



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
        disclosure = push_disclosure_context()
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
            # 2026-10-13 K例复审（P2c）：Graph 与 Fast 同一层——deferred（MCP/插件）
            # 工具不进 create_agent 的 schema；发现的工具经
            # _DeferredEnvelopeDispatchMiddleware 派发，执行走同一 orchestrator。
            # 注意：select_safe_tools 返回的是代理 StructuredTool，from_function
            # 不带 metadata——按原名回查 orchestrator 注册真身再判 deferred。
            # orchestrator 替身夹具（tests/test_execution/_OrchestratorStub）只有
            # select_safe_tools/execute_tool——没有 .get 时按代理自身判 deferred。
            _lookup = getattr(self._tools, "get", None)

            def _deferred_flag(tool_obj) -> bool:
                if callable(_lookup):
                    return is_deferred_tool(
                        _lookup(getattr(tool_obj, "name", "") or "") or tool_obj
                    )
                return is_deferred_tool(tool_obj)

            available = [tool for tool in available if not _deferred_flag(tool)]
            # #4：hint 限定子集后也必须保留 tool_search——hint 只约束**调用
            # 范围**，发现入口永远在场（否则 deferred 工具无入口可达）。
            task_limit = RiskLevel.READ if task.effect == TaskEffect.READ else None
            has_search_meta = (
                callable(_lookup) and _lookup(TOOL_SEARCH_NAME) is not None
            )
            if (
                has_search_meta
                and TOOL_SEARCH_NAME not in [getattr(t, "name", "") for t in available]
            ):
                available.extend(
                    self._tools.select_safe_tools(
                        [TOOL_SEARCH_NAME],
                        self._config,
                        max_risk=task_limit,
                    )
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
                    _DeferredEnvelopeDispatchMiddleware(
                        self._tools,
                        self._config,
                        max_risk=task_limit,
                        round_limit=max_tool_rounds,
                    ),
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
            # ContextVar 会复位，但 facade 里的记录不会跟着消失。只删本任务的 key。
            try:
                release_finished_disclosure_context(current_disclosure_context_id())
            finally:
                reset_disclosure_context(disclosure)
            evidence = self._tools.end_evidence_capture(token)
            if event_token is not None:
                self._tools.reset_event_tui(event_token)
        return str(answer), [item.model_dump() for item in evidence]
