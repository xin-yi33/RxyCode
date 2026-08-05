"""Worker-side thinking toggle persistence (fixes dead toggle between prompts)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from appserver.agent_worker import AgentWorker


class _FakeResult:
    status = "succeeded"
    answer = "hi"
    thinking = ""
    input_tokens = 1
    output_tokens = 1


def _make_worker(monkeypatch) -> tuple[AgentWorker, dict]:
    worker = AgentWorker()
    worker._agent = object()

    captured: dict = {}

    def fake_bind(session_id, tui):
        captured["tui"] = tui
        return (None, None)

    def fake_reset(tokens):
        return None

    class FakeSession:
        def __init__(self, **kwargs):
            captured["session_kwargs"] = kwargs
            self.prompt = AsyncMock(return_value=_FakeResult())

    monkeypatch.setattr("appserver.agent_worker.bind_prompt_context", fake_bind)
    monkeypatch.setattr("appserver.agent_worker.reset_prompt_context", fake_reset)
    monkeypatch.setattr("appserver.agent_worker.Session", FakeSession)
    messages: list[dict] = []
    monkeypatch.setattr(
        "appserver.agent_worker.write_message",
        AsyncMock(side_effect=lambda msg: messages.append(msg)),
    )
    return worker, captured


@pytest.mark.asyncio
async def test_toggle_between_prompts_persists_and_seeds_next_tui(monkeypatch):
    worker, captured = _make_worker(monkeypatch)

    await worker._handle_set_thinking_expanded({"expanded": True}, 1)

    await worker._handle_prompt(
        {"text": "hi", "session_id": "s", "run_id": "r1"}, 2
    )

    assert worker._thinking_expanded is True
    assert captured["tui"].get_thinking_expanded() is True


@pytest.mark.asyncio
async def test_prompt_param_overrides_stored_value(monkeypatch):
    worker, captured = _make_worker(monkeypatch)
    worker._thinking_expanded = True

    await worker._handle_prompt(
        {"text": "hi", "session_id": "s", "thinking_expanded": False}, 2
    )

    assert worker._thinking_expanded is False
    assert captured["tui"].get_thinking_expanded() is False


@pytest.mark.asyncio
async def test_toggle_during_active_prompt_applies_to_active_tui(monkeypatch):
    worker, _captured = _make_worker(monkeypatch)
    worker._thinking_expanded = False
    worker._active_tui = _dummy_tui()

    await worker._handle_set_thinking_expanded({"expanded": True}, 1)

    assert worker._thinking_expanded is True
    assert worker._active_tui.get_thinking_expanded() is True


def _dummy_tui():
    from appserver.tui import ProtocolTui

    return ProtocolTui("s", lambda _n: None)
