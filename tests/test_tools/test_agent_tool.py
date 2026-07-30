import asyncio
import inspect
from unittest.mock import MagicMock

import pytest


def _install_fakes(monkeypatch, fake_agent):
    import RxyCode.RxyCode1_1_0.core.agent_v2 as agent_module
    import RxyCode.RxyCode1_1_0.utils.tui as tui_module

    tui = MagicMock()
    monkeypatch.setattr(agent_module, "AgentV2", lambda: fake_agent)
    monkeypatch.setattr(tui_module, "get_tui", lambda: tui)
    return tui


def test_agent_tool_exposes_a_native_async_entry_point():
    from RxyCode.RxyCode1_1_0.tools.agent_tool import agent_tool

    assert inspect.iscoroutinefunction(agent_tool.coroutine)


@pytest.mark.asyncio
async def test_agent_tool_propagates_cancellation_to_the_child(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools.agent_tool import run_agent_async

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class FakeAgent:
        async def run(self, prompt, mode):
            assert (prompt, mode) == ("research", "compose")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    _install_fakes(monkeypatch, FakeAgent())
    task = asyncio.create_task(run_agent_async("research"))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


def test_sync_agent_entry_runs_without_a_background_executor(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools.agent_tool import run_agent

    class FakeAgent:
        async def run(self, prompt, mode):
            assert (prompt, mode) == ("summarize", "compose")
            return "complete"

    tui = _install_fakes(monkeypatch, FakeAgent())

    assert run_agent("summarize") == "complete"
    tui.write_success.assert_called_once_with("Sub-agent completed")
