"""Lifecycle hook registry tests."""

from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_sync_and_async_hooks_run_in_registration_order():
    from RxyCode.RxyCode1_1_0.core.hooks import HookPhase, HookRegistry, HookStatus

    registry = HookRegistry(default_timeout_seconds=1)
    calls = []

    def first(context):
        calls.append(("first", context.subject, context.payload["step"]))

    async def second(context):
        await asyncio.sleep(0)
        calls.append(("second", context.subject, context.payload["step"]))

    def third(context):
        calls.append(("third", context.subject, context.payload["step"]))

    registry.register(HookPhase.BEFORE, first, name="first")
    registry.register("before", second, name="second")
    registry.register("before", third, name="third")

    results = await registry.emit("before", "executor", {"step": 3})

    assert calls == [
        ("first", "executor", 3),
        ("second", "executor", 3),
        ("third", "executor", 3),
    ]
    assert [result.hook_name for result in results] == ["first", "second", "third"]
    assert all(result.status is HookStatus.SUCCEEDED for result in results)


@pytest.mark.asyncio
async def test_before_after_and_error_hooks_are_isolated_by_phase():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry

    registry = HookRegistry()
    calls = []
    for phase in ("before", "after", "error"):
        registry.register(
            phase,
            lambda context, phase=phase: calls.append((phase, context.phase.value)),
            name=phase,
        )

    before = await registry.emit("before", "tool")
    after = await registry.emit("after", "tool")
    error = await registry.emit("error", "tool", error="boom")

    assert calls == [("before", "before"), ("after", "after"), ("error", "error")]
    assert [before[0].phase.value, after[0].phase.value, error[0].phase.value] == [
        "before",
        "after",
        "error",
    ]


@pytest.mark.asyncio
async def test_timeout_is_per_hook_and_does_not_block_later_hooks():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry, HookStatus

    registry = HookRegistry(default_timeout_seconds=1)
    calls = []

    async def slow(_context):
        await asyncio.sleep(1)

    async def fast(_context):
        calls.append("fast")

    registry.register("before", slow, name="slow", timeout_seconds=0.01)
    registry.register("before", fast, name="fast")

    results = await registry.emit("before", "planner")

    assert [result.status for result in results] == [
        HookStatus.TIMED_OUT,
        HookStatus.SUCCEEDED,
    ]
    assert results[0].error_type == "TimeoutError"
    assert calls == ["fast"]


@pytest.mark.asyncio
async def test_sync_hook_is_dispatched_off_loop_and_can_time_out():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry, HookStatus

    registry = HookRegistry()
    calls = []

    def blocking(_context):
        time.sleep(0.05)

    async def after(_context):
        calls.append("after")

    registry.register("after", blocking, timeout_seconds=0.005)
    registry.register("after", after)

    results = await registry.emit("after", "validator")

    assert results[0].status is HookStatus.TIMED_OUT
    assert results[1].status is HookStatus.SUCCEEDED
    assert calls == ["after"]


@pytest.mark.asyncio
async def test_exception_is_audited_and_next_hook_still_runs():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry, HookStatus

    registry = HookRegistry()
    calls = []

    def broken(_context):
        raise RuntimeError("audit-safe failure")

    def healthy(_context):
        calls.append("healthy")

    registry.register("error", broken, name="broken")
    registry.register("error", healthy, name="healthy")

    results = await registry.emit("error", "executor", task_id="t1")

    assert results[0].status is HookStatus.FAILED
    assert results[0].error_type == "RuntimeError"
    assert results[0].error == "audit-safe failure"
    assert results[1].status is HookStatus.SUCCEEDED
    assert calls == ["healthy"]


@pytest.mark.asyncio
async def test_unregister_removes_hook_from_future_emits():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry

    registry = HookRegistry()
    calls = []
    hook_id = registry.register("before", lambda _context: calls.append("called"))

    assert registry.unregister(hook_id) is True
    assert registry.unregister(hook_id) is False
    assert await registry.emit("before", "planner") == []
    assert calls == []


@pytest.mark.asyncio
async def test_callable_returning_awaitable_is_supported():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry, HookStatus

    registry = HookRegistry()
    calls = []

    class CallableHook:
        def __call__(self, context):
            async def finish():
                calls.append(context.subject)

            return finish()

    registry.register("after", CallableHook())
    results = await registry.emit("after", "synthesizer")

    assert calls == ["synthesizer"]
    assert results[0].status is HookStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_audit_result_is_json_friendly_and_payload_is_read_only():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry

    registry = HookRegistry()

    def inspect_context(context):
        with pytest.raises(TypeError):
            context.payload["changed"] = True

    hook_id = registry.register("before", inspect_context, name="inspector")
    result = (await registry.emit("before", "tool:read", {"path": "a.txt"}))[0]
    audit = result.to_dict()

    assert audit["hook_id"] == hook_id
    assert audit["hook_name"] == "inspector"
    assert audit["phase"] == "before"
    assert audit["subject"] == "tool:read"
    assert audit["status"] == "succeeded"
    assert isinstance(audit["duration_ms"], float)
    assert audit["started_at"].endswith("+00:00")


def test_invalid_registration_arguments_are_rejected():
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry

    with pytest.raises(ValueError, match="default_timeout_seconds"):
        HookRegistry(default_timeout_seconds=0)

    registry = HookRegistry()
    with pytest.raises(ValueError, match="phase"):
        registry.register("unknown", lambda _context: None)
    with pytest.raises(TypeError, match="callable"):
        registry.register("before", object())
    with pytest.raises(ValueError, match="timeout_seconds"):
        registry.register("before", lambda _context: None, timeout_seconds=0)
