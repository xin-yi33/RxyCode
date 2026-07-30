"""Contracts for the API thinking visibility switch."""

import pytest


@pytest.mark.asyncio
async def test_thinking_toggle_changes_visibility_without_replaying_history(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    class Agent:
        def __init__(self):
            self._last_thinking = "private historical reasoning"
            self.flush_calls = 0

        def _flush_thinking(self, **_kwargs):
            self.flush_calls += 1

    agent = Agent()
    proxy = api_server.APIProxyTUI()
    previous = dict(api_server._state)
    api_server._state.update({"agent": agent, "tui_proxy": proxy})
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.tui.get_tui", lambda: proxy)
    try:
        result = await api_server._execute_command(
            api_server.CommandRequest(command="/thinking")
        )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert result["action"] == "thinking_toggled"
    assert result["expanded"] is True
    assert proxy.get_thinking_expanded() is True
    assert proxy._last_output == []
    assert agent.flush_calls == 0
