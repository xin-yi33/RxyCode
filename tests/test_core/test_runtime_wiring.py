"""Cross-module tests proving runtime infrastructure is on live call paths."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fixed_rate_limiter():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitPolicy,
    )

    return AsyncTokenBucketRateLimiter(
        default_policy=RateLimitPolicy(
            requests_per_period=10,
            tokens_per_period=20,
            period_seconds=1000,
            request_burst=10,
            token_burst=20,
        ),
        clock=lambda: 0.0,
    )


@pytest.mark.asyncio
async def test_usage_tracking_llm_acquires_governed_capacity_before_model_call():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    order = []
    grant = object()
    limiter = SimpleNamespace(
        acquire=AsyncMock(
            side_effect=lambda *args, **kwargs: order.append("limit") or grant
        ),
        reconcile=MagicMock(),
    )
    response = SimpleNamespace(content="ok", response_metadata={})

    async def invoke(_messages, **_kwargs):
        order.append("model")
        return response

    underlying = SimpleNamespace(ainvoke=invoke)
    llm = UsageTrackingLLM(
        underlying,
        rate_limiter=limiter,
        rate_provider="provider",
        rate_model="model",
        rate_timeout=2,
    )

    await llm.ainvoke([SimpleNamespace(type="human", content="hello")])

    assert order == ["limit", "model"]
    limiter.acquire.assert_awaited_once()
    limiter.reconcile.assert_called_once()


@pytest.mark.asyncio
async def test_usage_tracking_refunds_output_reservation_on_provider_error():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

    limiter = _fixed_rate_limiter()
    reconcile = MagicMock(wraps=limiter.reconcile)
    limiter.reconcile = reconcile
    inner = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=ConnectionError("provider down"))
    )
    llm = UsageTrackingLLM(
        inner,
        rate_limiter=limiter,
        rate_provider="provider",
        rate_model="model",
        reserved_output_tokens=10,
    )

    with patch.object(cb_mod, "circuit_breaker_enabled", return_value=False):
        with pytest.raises(ConnectionError, match="provider down"):
            await llm.ainvoke([])

    snapshot = limiter.snapshot("provider", "model")
    assert snapshot.remaining_requests == 9
    assert snapshot.remaining_tokens == 20
    assert reconcile.call_count == 1


@pytest.mark.asyncio
async def test_usage_tracking_refunds_output_reservation_when_breaker_is_open():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

    limiter = _fixed_rate_limiter()
    reconcile = MagicMock(wraps=limiter.reconcile)
    limiter.reconcile = reconcile
    inner = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=ConnectionError("provider down"))
    )
    llm = UsageTrackingLLM(
        inner,
        rate_limiter=limiter,
        rate_provider="provider",
        rate_model="model",
        reserved_output_tokens=10,
    )
    breaker = cb_mod.LLMCircuitBreaker(fail_max=1, reset_timeout=60)

    with (
        patch.object(cb_mod, "circuit_breaker_enabled", return_value=True),
        patch.object(cb_mod, "get_default_breaker", return_value=breaker),
    ):
        with pytest.raises(ConnectionError, match="provider down"):
            await llm.ainvoke([])
        # The first logical call may make several inner attempts because
        # transient transport errors (ConnectionError) are retried by
        # _call_with_transport_retry; that amplification is orthogonal to the
        # breaker contract under test here.
        count_after_failure = inner.ainvoke.await_count
        unavailable = await llm.ainvoke([])

    assert "unavailable" in unavailable.content.lower()
    # Breaker is now open: the second call MUST be short-circuited without
    # touching the provider. Assert the short-circuit added zero further inner
    # calls (robust to the transport-retry budget) instead of pinning an
    # absolute count.
    assert inner.ainvoke.await_count == count_after_failure
    snapshot = limiter.snapshot("provider", "model")
    assert snapshot.remaining_requests == 8
    assert snapshot.remaining_tokens == 20
    assert reconcile.call_count == 2


@pytest.mark.asyncio
async def test_usage_tracking_reconciles_stream_error_and_cancellation_once():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

    error_limiter = _fixed_rate_limiter()
    error_reconcile = MagicMock(wraps=error_limiter.reconcile)
    error_limiter.reconcile = error_reconcile

    async def failing_stream(_messages, **_kwargs):
        yield SimpleNamespace(content="")
        raise ConnectionError("stream interrupted")

    failing = UsageTrackingLLM(
        SimpleNamespace(astream=failing_stream),
        rate_limiter=error_limiter,
        rate_provider="provider",
        rate_model="model",
        reserved_output_tokens=10,
    )
    with patch.object(cb_mod, "circuit_breaker_enabled", return_value=False):
        with pytest.raises(ConnectionError, match="stream interrupted"):
            _ = [chunk async for chunk in failing.astream([])]

    error_snapshot = error_limiter.snapshot("provider", "model")
    assert error_snapshot.remaining_requests == 9
    assert error_snapshot.remaining_tokens == 20
    assert error_reconcile.call_count == 1

    cancel_limiter = _fixed_rate_limiter()
    cancel_reconcile = MagicMock(wraps=cancel_limiter.reconcile)
    cancel_limiter.reconcile = cancel_reconcile
    blocked = asyncio.Event()

    async def blocked_stream(_messages, **_kwargs):
        yield SimpleNamespace(content="")
        blocked.set()
        await asyncio.Event().wait()

    cancellable = UsageTrackingLLM(
        SimpleNamespace(astream=blocked_stream),
        rate_limiter=cancel_limiter,
        rate_provider="provider",
        rate_model="model",
        reserved_output_tokens=10,
    )

    async def consume():
        with patch.object(cb_mod, "circuit_breaker_enabled", return_value=False):
            return [chunk async for chunk in cancellable.astream([])]

    operation = asyncio.create_task(consume())
    await blocked.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation

    cancel_snapshot = cancel_limiter.snapshot("provider", "model")
    assert cancel_snapshot.remaining_requests == 9
    assert cancel_snapshot.remaining_tokens == 20
    assert cancel_reconcile.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["error", "cancel"])
async def test_raw_stream_refunds_unused_output_reservation(terminal):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

    limiter = _fixed_rate_limiter()
    reconcile = MagicMock(wraps=limiter.reconcile)
    limiter.reconcile = reconcile
    blocked = asyncio.Event()

    async def stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content="", reasoning_content="", tool_calls=None,
            ))],
            usage=None,
        )
        if terminal == "error":
            raise ConnectionError("raw stream interrupted")
        blocked.set()
        await asyncio.Event().wait()

    agent = AgentV2.__new__(AgentV2)
    agent._llm = SimpleNamespace()
    agent._openai_client = MagicMock(
        return_value=SimpleNamespace(create=MagicMock(return_value=stream()))
    )
    agent._rate_limiter = limiter
    agent._rate_reserved_output_tokens = 10
    agent._rate_limit_timeout = 0
    agent.model_config = {
        "base_url": "https://api.openai.com/v1",
        "model_name": "raw-model",
        "temperature": 0,
        "max_tokens": 32,
    }

    async def consume():
        return [chunk async for chunk in AgentV2._raw_stream(agent, [])]

    with patch.object(cb_mod, "circuit_breaker_enabled", return_value=False):
        if terminal == "error":
            with pytest.raises(ConnectionError, match="raw stream interrupted"):
                await consume()
        else:
            operation = asyncio.create_task(consume())
            await blocked.wait()
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation

    provider = agent._provider_name(agent.model_config)
    snapshot = limiter.snapshot(provider, "raw-model")
    assert snapshot.remaining_requests == 9
    assert snapshot.remaining_tokens == 20
    assert reconcile.call_count == 1


def test_graph_resolves_declared_model_roles_through_router():
    from RxyCode.RxyCode1_1_0.core.governance import ModelRouter
    from RxyCode.RxyCode1_1_0.core.graph import _model_for

    default = object()
    planner = object()
    executor = object()
    reflection = object()
    router = ModelRouter(default)
    router.register("planner", planner)
    router.register("executor", executor)
    router.register("reflection", reflection)
    state = {"_llm": default, "_model_router": router}

    assert _model_for(state, "planner") is planner
    assert _model_for(state, "executor") is executor
    assert _model_for(state, "reflection") is reflection
    assert _model_for(state, "default") is default


@pytest.mark.asyncio
async def test_graph_node_emits_registered_before_and_after_hooks():
    from RxyCode.RxyCode1_1_0.core.graph import observed_node
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry

    phases = []
    hooks = HookRegistry()
    hooks.register("before", lambda context: phases.append(context.phase.value))
    hooks.register("after", lambda context: phases.append(context.phase.value))
    audit = []

    async def node(_state):
        return {"phase": "done"}

    await observed_node("unit", node)(
        {
            "session_id": "s",
            "phase": "executing",
            "_tracer": None,
            "_hooks": hooks,
            "_hook_audit": audit,
            "_checkpoint_store": None,
        }
    )

    assert phases == ["before", "after"]
    assert [item["subject"] for item in audit] == ["graph_node", "graph_node"]


@pytest.mark.asyncio
async def test_graph_node_writes_request_local_durable_trajectory():
    from RxyCode.RxyCode1_1_0.core.graph import observed_node

    trajectory = MagicMock()

    async def node(_state):
        return {
            "phase": "executing",
            "reflection_action": "replan",
            "replan_count": 1,
        }

    await observed_node("reflection", node)(
        {
            "session_id": "s",
            "phase": "validating",
            "_tracer": None,
            "_trajectory": trajectory,
            "_hooks": None,
            "_checkpoint_store": None,
        }
    )

    assert [call.args[0] for call in trajectory.record.call_args_list] == [
        "graph.node.started",
        "graph.node.completed",
    ]
    completed = trajectory.record.call_args_list[-1].args[1]
    assert completed["reflection_action"] == "replan"
    assert completed["replan_count"] == 1


@pytest.mark.asyncio
async def test_tool_entry_emits_hooks_and_retries_only_transient_read_failure():
    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    attempts = 0

    async def flaky_read(path: str) -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return f"read {path}"

    tool = StructuredTool.from_function(
        coroutine=flaky_read,
        name="read",
        description="read",
    )
    orchestrator = ToolOrchestrator()
    orchestrator.register("read", tool)
    phases = []
    hooks = HookRegistry()
    hooks.register("before", lambda context: phases.append(context.phase.value))
    hooks.register("after", lambda context: phases.append(context.phase.value))
    audit = []
    token = orchestrator.bind_event_hooks(hooks, audit)
    try:
        result = await orchestrator.execute_tool(
            "read",
            {"path": "a.txt"},
            config={
                "safety": {"enabled": False},
                "execution": {
                    "tool_retry_attempts": 3,
                    "tool_retry_wait_multiplier": 0,
                },
            },
        )
    finally:
        orchestrator.reset_event_hooks(token)

    assert result == "read a.txt"
    assert attempts == 3
    assert phases == ["before", "after"]
    assert [item["subject"] for item in audit] == ["tool_call", "tool_call"]


@pytest.mark.asyncio
async def test_tool_entry_persists_arguments_and_cleaned_result_to_trajectory():
    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    async def read(path: str) -> str:
        return f"api_key=secret-value read {path}"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "read",
        StructuredTool.from_function(coroutine=read, name="read", description="read"),
    )
    trajectory = MagicMock()
    token = orchestrator.bind_event_trajectory(trajectory)
    try:
        result = await orchestrator.execute_tool(
            "read",
            {"path": "a.txt"},
            config={"safety": {"enabled": False}},
            call_id="call-1",
        )
    finally:
        orchestrator.reset_event_trajectory(token)

    assert "secret-value" not in result
    assert [call.args[0] for call in trajectory.record.call_args_list] == [
        "tool.started",
        "tool.completed",
    ]
    assert trajectory.record.call_args_list[0].args[1]["arguments"] == {
        "path": "a.txt"
    }
    assert "secret-value" not in trajectory.record.call_args_list[1].args[1][
        "result"
    ]


@pytest.mark.asyncio
async def test_agent_run_creates_and_finishes_real_trajectory(isolated_runtime):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.trajectory import read_trajectory

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "runtime-session"
    agent._tool_tracer = None
    agent._hooks = None
    agent._run_impl = AsyncMock(return_value="The plan has three steps.")

    result = await agent._run_observed(
        "explain the plan",
        "build",
        "runtime-trajectory",
    )

    assert result == "The plan has three steps."
    events = read_trajectory("runtime-trajectory")
    assert [event["event_type"] for event in events] == [
        "run.started",
        "run.result",
        "run.finished",
    ]
    assert events[-1]["payload"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_agent_run_binds_session_and_attributes_terminal_verification_failure(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.session_runtime import current_session_id

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "isolated-run-session"
    agent._tool_tracer = None
    agent._hooks = None

    async def run_impl(_user_input, _mode):
        assert current_session_id() == "isolated-run-session"
        return "[Build incomplete: final evidence did not verify]"

    agent._run_impl = run_impl

    result = await agent._run_observed(
        "implement the plan",
        "build",
        "runtime-attribution",
    )

    assert result.startswith("[Build incomplete")
    assert agent._last_failure_attribution == {"verification_error": 1}


@pytest.mark.asyncio
async def test_agent_run_attributes_cancellation(isolated_runtime):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "cancelled-session"
    agent._tool_tracer = None
    agent._hooks = None
    agent._run_impl = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await agent._run_observed("cancel me", "build", "runtime-cancelled")

    assert agent._last_failure_attribution == {"cancelled": 1}


def test_unified_tool_output_contract_redacts_controls_and_bounds_text():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    output = "api_key=super-secret\x00\n" + ("x" * 2000)
    cleaned = ToolOrchestrator._clean_tool_output(
        output,
        {"context": {"max_tool_output_chars": 1000}},
    )

    assert "super-secret" not in cleaned
    assert "api_key=***" in cleaned
    assert "\x00" not in cleaned
    assert "tool output truncated" in cleaned
    assert len(cleaned) < 1100
