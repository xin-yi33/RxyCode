from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from appserver.agent_host import AgentHost
from appserver.agent_worker import AgentWorker
from appserver.server import AppServer, _prompt_request_signature
from protocol.version import PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_host_routes_only_path_name_metadata_to_worker(tmp_path):
    host = AgentHost(
        session_id="s1",
        workspace_root=tmp_path,
        stub=True,
        project_root=tmp_path,
        forward_server_request=AsyncMock(),
        main_loop=asyncio.get_running_loop(),
    )
    host._pipe_request = AsyncMock(return_value={"status": "succeeded"})
    attachments = [{"path": str(tmp_path / "image.png"), "name": "photo.png"}]
    await host.run_prompt(
        text="inspect this",
        run_id="r1",
        timeout=5,
        emit=lambda _message: None,
        attachments=attachments,
    )
    params = host._pipe_request.await_args.args[1]
    assert params["attachments"] == attachments


@pytest.mark.asyncio
async def test_worker_passes_attachments_once_to_core_session(tmp_path, monkeypatch):
    worker = AgentWorker()
    worker._agent = object()
    worker._workspace_root = tmp_path
    captured = {}

    class Result:
        status = "succeeded"
        answer = "ok"
        thinking = ""
        input_tokens = 1
        output_tokens = 1
        cache_hit_tokens = 0
        cache_hit_rate = 0.0

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def prompt(self, _agent, _text, **kwargs):
            captured.setdefault("calls", []).append(dict(kwargs))
            return Result()

    monkeypatch.setattr("appserver.agent_worker.Session", FakeSession)
    monkeypatch.setattr("appserver.agent_worker.bind_prompt_context", lambda *_args: (None, None))
    monkeypatch.setattr("appserver.agent_worker.reset_prompt_context", lambda _token: None)
    monkeypatch.setattr("appserver.agent_worker.write_message", AsyncMock())
    attachments = [{"path": str(tmp_path / "notes.txt"), "name": "notes.txt"}]
    await worker._handle_prompt(
        {"text": "read this", "session_id": "s1", "run_id": "r1", "attachments": attachments},
        2,
    )
    assert len(captured["calls"]) == 1
    assert captured["calls"][0]["attachments"] == attachments


@pytest.mark.parametrize("has_attachments", [False, True])
@pytest.mark.asyncio
async def test_worker_preserves_legacy_session_compat_and_rejects_attachment_drop(
    tmp_path, monkeypatch, has_attachments
):
    worker = AgentWorker()
    worker._agent = object()
    worker._workspace_root = tmp_path
    calls = []
    errors = []
    responses = []

    class Result:
        status = "succeeded"
        answer = "ok"
        thinking = ""
        input_tokens = 1
        output_tokens = 1
        cache_hit_tokens = 0
        cache_hit_rate = 0.0

    class LegacySession:
        async def prompt(
            self,
            _agent,
            _text,
            *,
            mode="build",
            run_id=None,
            permission_mode=None,
            tui=None,
        ):
            calls.append(
                {
                    "mode": mode,
                    "run_id": run_id,
                    "permission_mode": permission_mode,
                    "tui": tui,
                }
            )
            return Result()

    session = LegacySession()
    monkeypatch.setattr(worker, "bind_core_session", lambda *_args: session)
    monkeypatch.setattr(
        "appserver.agent_worker.bind_prompt_context", lambda *_args: (None, None)
    )
    monkeypatch.setattr("appserver.agent_worker.reset_prompt_context", lambda _token: None)
    monkeypatch.setattr(worker, "_wind_down_stream", AsyncMock())

    async def capture_error(_request_id, error):
        errors.append(error)

    async def capture_response(response):
        responses.append(response)

    monkeypatch.setattr(worker, "_write_ordered_error", capture_error)
    monkeypatch.setattr(worker, "_write_ordered", capture_response)

    params = {"text": "legacy prompt", "session_id": "s1", "run_id": "r1"}
    if has_attachments:
        params["attachments"] = [
            {"path": str(tmp_path / "notes.txt"), "name": "notes.txt"}
        ]
    await worker._handle_prompt(params, 3)

    if has_attachments:
        assert calls == []
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)
        assert "does not support prompt attachments" in str(errors[0])
        assert responses == []
    else:
        assert len(calls) == 1
        assert errors == []
        assert responses and responses[0]["result"]["text"] == "ok"


@pytest.mark.asyncio
async def test_appserver_prompt_logs_and_restarts_with_metadata_only(tmp_path, monkeypatch):
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path)
    server._initialized = True
    captured = {}
    events = []
    monkeypatch.setattr(server._task_store, "append_event", lambda _sid, event: events.append(event))
    monkeypatch.setattr(server, "_schedule_session_title_for_events", lambda *_args, **_kwargs: None)

    async def fake_run_prompt(**kwargs):
        captured.update(kwargs)
        await server._respond(kwargs["request_id"], {"status": "succeeded", "text": "ok"})

    async def capture_response(_request_id, _result):
        pass

    server._run_prompt = fake_run_prompt
    server._respond = capture_response
    attachment = {"path": str(tmp_path / "photo-uuid.png"), "name": "剪贴板图片.png"}
    await server._handle_prompt(
        {
            "session_id": record.session_id,
            "text": "describe image",
            "request_id": "turn-1",
            "attachments": [attachment],
        },
        1,
    )
    assert captured["attachments"] == [attachment]
    assert captured["request_signature"]
    event = next(item for item in events if item["method"] == "session/prompt")
    assert event["params"]["attachments"] == [attachment]
    assert "base64" not in repr(event)


@pytest.mark.asyncio
async def test_request_id_replay_cannot_reuse_answer_for_different_attachment(tmp_path, monkeypatch):
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path)
    server._initialized = True
    existing = [{"path": str(tmp_path / "first.png"), "name": "first.png"}]
    signature = _prompt_request_signature(
        text="same prompt",
        attachments=existing,
        mode="build",
        permission_mode=None,
        thinking_expanded=None,
        capability=None,
    )
    server._sessions.remember_turn(
        record.session_id,
        "same-turn",
        {"status": "succeeded", "text": "first image answer", "_request_signature": signature},
    )
    responses = []
    errors = []
    async def respond_error(_request_id, code, message, *_args, **_kwargs):
        errors.append((code, message))
    server._respond = AsyncMock(side_effect=lambda _rid, result: responses.append(result))
    server._respond_error = respond_error
    await server._handle_prompt(
        {
            "session_id": record.session_id,
            "text": "same prompt",
            "request_id": "same-turn",
            "attachments": [{"path": str(tmp_path / "second.png"), "name": "second.png"}],
        },
        2,
    )
    assert responses == []
    assert errors and "different prompt body or attachment metadata" in errors[0][1]


@pytest.mark.asyncio
async def test_initialize_advertises_prompt_attachment_capability(monkeypatch):
    server = AppServer(stub=True)
    server._schedule_task = SimpleNamespace(done=lambda: False)
    monkeypatch.setattr(server._recovery, "restore_after_restart", lambda _store: None)
    monkeypatch.setattr(server._recovery, "reclaim_orphans", lambda _ids: None)
    monkeypatch.setattr(server._schedule, "reclaim_orphans", lambda: None)
    monkeypatch.setattr("appserver.server._model_provider_summaries", lambda: [])
    monkeypatch.setattr("appserver.server._permission_profiles", lambda: [])
    payloads = []
    async def respond(_request_id, payload):
        payloads.append(payload)
    server._respond = respond
    server._emit_model = AsyncMock()
    await server._handle_initialize(
        {"client_name": "test", "protocol_version": PROTOCOL_VERSION}, 1
    )
    assert payloads[0]["capabilities"]["prompt_attachments"] is True
