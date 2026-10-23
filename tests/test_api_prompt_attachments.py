from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


class _FakeAgent:
    model_config = {"model_name": "test-model"}
    _thinking_history: list[str] = []
    _last_thinking = ""
    _session_loaded = False
    _tool_tracer = None

    def set_session(self, _session_id):
        pass


class _FakePromptSession:
    def __init__(self, captured):
        self.captured = captured

    async def prompt(self, _agent, text, **kwargs):
        self.captured.append({"text": text, **kwargs})
        return SimpleNamespace(
            answer="ok",
            status="succeeded",
            detail="",
            thinking="",
        )


def test_http_status_advertises_prompt_attachment_capability():
    from RxyCode.RxyCode1_1_0 import api_server

    old_state = dict(api_server._state)
    old_token = api_server.get_api_token()
    api_server._state.update(
        {
            "agent": _FakeAgent(),
            "mode": "build",
        }
    )
    token = api_server.configure_api_token()
    try:
        with TestClient(
            api_server.app,
            client=("127.0.0.1", 50001),
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = client.get("/status")
        assert response.status_code == 200
        assert response.json()["capabilities"]["prompt_attachments"] is True
    finally:
        api_server._state.clear()
        api_server._state.update(old_state)
        api_server.configure_api_token(old_token)


@pytest.mark.asyncio
async def test_http_chat_and_sse_share_session_prompt_attachment_contract(monkeypatch, tmp_path):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.core import session as core_session

    old_state = dict(api_server._state)
    captured = []
    history = []
    fake_session = _FakePromptSession(captured)
    monkeypatch.setattr(
        core_session,
        "reuse_or_create_session",
        lambda *_args, **_kwargs: fake_session,
    )

    async def run_direct(operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(api_server._api_run_lifecycle, "run", run_direct)
    api_server._state.update(
        {
            "agent": _FakeAgent(),
            "tui_proxy": api_server.APIProxyTUI(),
            "chat_history": history,
            "chat_histories": {"latest": history},
            "active_session_id": "latest",
            "core_sessions": {},
            "busy": False,
            "mode": "build",
        }
    )
    attachment = {"path": str(tmp_path / "clip-unique.png"), "name": "剪贴板图片.png"}
    try:
        request = api_server.ChatRequest(
            message="describe this",
            session_id="latest",
            attachments=[attachment],
        )
        response = await api_server.chat(request)
        assert response.response == "ok"

        stream_response = await api_server.chat_stream(request)
        stream_body = "".join([
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            async for chunk in stream_response.body_iterator
        ])
        assert '"type": "done"' in stream_body or '"type":"done"' in stream_body

        assert len(captured) == 2
        assert all(call["attachments"] == [attachment] for call in captured)
        user_messages = [item for item in history if item.get("role") == "user"]
        assert len(user_messages) == 2
        assert all(item["attachments"] == [attachment] for item in user_messages)
        assert "base64" not in repr(user_messages)
    finally:
        api_server._state.clear()
        api_server._state.update(old_state)
