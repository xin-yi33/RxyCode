from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_run_lifecycle_serializes_operations_in_submission_order():
    from RxyCode.RxyCode1_1_0.core.run_lifecycle import RunLifecycle

    lifecycle = RunLifecycle(poll_interval=0)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first():
        events.append("first-start")
        first_started.set()
        await release_first.wait()
        events.append("first-end")
        return 1

    async def second():
        events.append("second-start")
        return 2

    first_task = asyncio.create_task(lifecycle.run(first, kind="chat"))
    await first_started.wait()
    second_task = asyncio.create_task(lifecycle.run(second, kind="command"))
    await asyncio.sleep(0)
    assert lifecycle.active_kind == "chat"
    assert events == ["first-start"]

    release_first.set()
    assert await first_task == 1
    assert await second_task == 2
    assert events == ["first-start", "first-end", "second-start"]
    assert lifecycle.busy is False


@pytest.mark.asyncio
async def test_run_lifecycle_cancel_handle_cancels_active_run_and_releases_slot():
    from RxyCode.RxyCode1_1_0.core.run_lifecycle import RunLifecycle

    lifecycle = RunLifecycle(poll_interval=0)
    started = asyncio.Event()

    async def blocking():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(lifecycle.run(blocking, kind="command"))
    await started.wait()
    assert lifecycle.cancel() is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await lifecycle.run(lambda: _value("next"), kind="chat") == "next"
    assert lifecycle.busy is False


async def _value(value: str) -> str:
    return value
