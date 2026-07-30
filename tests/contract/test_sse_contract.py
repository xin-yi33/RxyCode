from __future__ import annotations

import asyncio
import json

import httpx


def _events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


async def test_sse_stream_preserves_unicode_and_correlates_terminal_events(
    isolated_runtime,
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    class ScriptedAgent:
        _stream_mode = False
        _tool_tracer = None

        async def run(self, message: str, mode: str) -> str:
            get_tui().stream_token("\u4f60")
            get_tui().stream_token("\u597d \U0001F9EE")
            return "\u4f60\u597d \U0001F9EE"

        def get_thinking_history(self):
            return ""

    previous = dict(api_server._state)
    api_server._state.update(
        {"agent": ScriptedAgent(), "busy": False, "chat_history": []}
    )
    try:
        token = api_server.configure_api_token()
        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = await client.post(
                "/chat/stream", json={"message": "unicode", "mode": "build"}
            )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [event["text"] for event in events if event["type"] == "token"] == [
        "\u4f60",
        "\u597d \U0001F9EE",
    ]
    final = next(event for event in events if event["type"] == "final")
    done = next(event for event in events if event["type"] == "done")
    assert final["text"] == "\u4f60\u597d \U0001F9EE"
    assert final["run_id"] == done["run_id"]
    assert done["status"] == "succeeded"


async def test_sse_run_id_is_used_by_tool_audit(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.core.safety.audit import AuditLogger
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

    audit_path = isolated_runtime.data_dir / "logs" / "request-audit.jsonl"
    audit = AuditLogger(path=audit_path)

    class AuditedAgent:
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            audit.log(
                tool="read",
                risk=RiskLevel.READ,
                args={"path": "contract.txt"},
                approval="auto",
                result="ok",
            )
            return "audited response"

    previous = dict(api_server._state)
    api_server._state.update({
        "agent": AuditedAgent(),
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
    })
    try:
        response = await api_server.chat_stream(
            api_server.ChatRequest(message="audit", mode="build")
        )
        body = "".join([chunk async for chunk in response.body_iterator])
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    done = next(event for event in _events(body) if event["type"] == "done")
    record = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert record["run_id"] == done["run_id"]


async def test_streamed_session_save_load_round_trips_all_roles_without_truncation(
    isolated_runtime,
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.memory.chat_storage import (
        CHAT_SCHEMA_VERSION,
        chat_storage,
    )
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    full_output = "begin\n" + ("tool-output-" * 200) + "\nend"

    class StreamingAgent:
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            tui = get_tui()
            tui.write_reasoning("full reasoning")
            tui.write_tool_call("bash", {"cmd": "run tests"})
            tui.write_tool_result(full_output, "success")
            tui.stream_token("complete")
            return "complete"

    previous = dict(api_server._state)
    previous_storage_dir = chat_storage._storage_dir
    chats_dir = isolated_runtime.data_dir / "chats"
    chats_dir.mkdir()
    monkeypatch.setattr(chat_storage, "_storage_dir", chats_dir)
    api_server._state.update({
        "agent": StreamingAgent(),
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
    })
    try:
        response = await api_server.chat_stream(
            api_server.ChatRequest(message="persist this", mode="build")
        )
        body = "".join([chunk async for chunk in response.body_iterator])
        events = _events(body)
        assert next(event for event in events if event["type"] == "final")[
            "session_schema_version"
        ] == CHAT_SCHEMA_VERSION

        streamed_history = list(api_server._state["chat_history"])
        assert [message["role"] for message in streamed_history] == [
            "user", "thinking", "tool", "assistant"
        ]
        assert streamed_history[1]["content"] == "full reasoning"
        assert streamed_history[2]["content"] == full_output
        assert streamed_history[2]["toolStdout"] == full_output
        assert len(streamed_history[2]["toolStdout"]) > 500

        api_server._state["agent"] = None
        saved = await api_server.command(
            api_server.CommandRequest(command="/save-chat streamed-exact")
        )
        assert saved["schema_version"] == CHAT_SCHEMA_VERSION
        api_server._state["chat_history"] = []
        loaded = await api_server.command(
            api_server.CommandRequest(command="/load-chat streamed-exact")
        )
        assert loaded["schema_version"] == CHAT_SCHEMA_VERSION
        assert loaded["messages"] == streamed_history
        assert api_server._state["chat_history"] == streamed_history
    finally:
        chat_storage._storage_dir = previous_storage_dir
        api_server._state.clear()
        api_server._state.update(previous)


async def test_stream_thinking_is_scoped_to_the_current_turn(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    class AccumulatingAgent:
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            self._last_thinking = f"reason-{message}"
            self._thinking_history.append(self._last_thinking)
            get_tui().stream_token(message)
            return f"answer-{message}"

    agent = AccumulatingAgent()
    previous = dict(api_server._state)
    api_server._state.update({
        "agent": agent,
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
    })
    try:
        first = await api_server.chat_stream(
            api_server.ChatRequest(message="one", mode="build")
        )
        first_events = _events(await _consume_body(first))
        second = await api_server.chat_stream(
            api_server.ChatRequest(message="two", mode="build")
        )
        second_events = _events(await _consume_body(second))

        assert next(event for event in first_events if event["type"] == "final")[
            "thinking"
        ] == "reason-one"
        assert next(event for event in second_events if event["type"] == "final")[
            "thinking"
        ] == "reason-two"
        thinking = [
            message["content"]
            for message in api_server._state["chat_history"]
            if message["role"] == "thinking"
        ]
        assert thinking == ["reason-one", "reason-two"]
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


async def test_non_stream_thinking_is_scoped_to_the_current_turn(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server

    class AccumulatingAgent:
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            self._last_thinking = f"reason-{message}"
            self._thinking_history.append(self._last_thinking)
            return f"answer-{message}"

    previous = dict(api_server._state)
    api_server._state.update({
        "agent": AccumulatingAgent(),
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
    })
    try:
        first = await api_server.chat(
            api_server.ChatRequest(message="one", mode="build")
        )
        second = await api_server.chat(
            api_server.ChatRequest(message="two", mode="build")
        )

        assert first.thinking == "reason-one"
        assert second.thinking == "reason-two"
    finally:
        api_server._state.clear()
        api_server._state.update(previous)


async def test_non_stream_chat_correlates_context_and_tool_tracer(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.log.logger import RUN_ID, get_current_run_id

    observed = {}

    class ContextAgent:
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            observed["context"] = get_current_run_id()
            observed["trace"] = self._tool_tracer.run_id
            return f"{mode}:{message}"

    agent = ContextAgent()
    previous = dict(api_server._state)
    api_server._state.update({
        "agent": agent,
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
    })
    try:
        response = await api_server.chat(
            api_server.ChatRequest(message="context", mode="build")
        )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert response.response == "build:context"
    assert observed["context"] == observed["trace"]
    assert observed["context"] != RUN_ID
    assert get_current_run_id() == RUN_ID
    assert agent._tool_tracer is None


async def test_invalid_mode_uses_error_then_done_contract(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server

    previous = dict(api_server._state)
    api_server._state["agent"] = object()
    api_server._state["busy"] = False
    try:
        token = api_server.configure_api_token()
        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = await client.post(
                "/chat/stream", json={"message": "hello", "mode": "invalid"}
            )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    events = _events(response.text)
    assert [event["type"] for event in events] == ["error", "done"]


async def test_fastapi_lifespan_installs_sse_approval_broker(
    isolated_runtime,
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        SseApproval,
        get_approval_broker,
    )

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    async with api_server.app.router.lifespan_context(api_server.app):
        await asyncio.sleep(0)
        assert isinstance(get_approval_broker(), SseApproval)


async def test_client_disconnect_cancels_agent_and_records_terminal_status(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        SseApproval,
        get_approval_broker,
        set_approval_broker,
    )
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    cancelled = asyncio.Event()

    class BlockingAgent:
        _stream_mode = False
        _tool_tracer = None

        async def run(self, message: str, mode: str) -> str:
            get_tui().stream_token("started")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def get_thinking_history(self):
            return ""

    previous = dict(api_server._state)
    previous_broker = get_approval_broker()
    previous_tui = get_tui()
    broker = SseApproval(timeout=1)
    original_sink = lambda _event: None
    broker.set_event_sink(original_sink)
    set_approval_broker(broker)
    api_server._state.update(
        {"agent": BlockingAgent(), "busy": False, "chat_history": []}
    )
    response = await api_server.chat_stream(
        api_server.ChatRequest(message="disconnect", mode="build")
    )
    stream = response.body_iterator.__aiter__()

    try:
        first = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert json.loads(first.removeprefix("data: "))["type"] == "token"
        await stream.aclose()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        for _ in range(10):
            if not api_server._state["busy"]:
                break
            await asyncio.sleep(0)

        snapshot = run_monitor.snapshot()
        assert api_server._state["busy"] is False
        assert not api_server._chat_lock.locked()
        assert broker._sink is original_sink
        assert get_tui() is previous_tui
        assert snapshot["status_counts"]["cancelled"] == 1
        assert snapshot["last_run"]["status"] == "cancelled"
    finally:
        await stream.aclose()
        set_approval_broker(previous_broker)
        api_server._state.clear()
        api_server._state.update(previous)


async def test_agent_exception_restores_stream_process_state(isolated_runtime):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        SseApproval,
        get_approval_broker,
        set_approval_broker,
    )
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    class FailingAgent:
        _stream_mode = False
        _tool_tracer = None

        async def run(self, message: str, mode: str) -> str:
            raise RuntimeError("scripted stream failure")

        def get_thinking_history(self):
            return ""

    previous = dict(api_server._state)
    previous_broker = get_approval_broker()
    previous_tui = get_tui()
    broker = SseApproval(timeout=1)
    original_sink = lambda _event: None
    broker.set_event_sink(original_sink)
    set_approval_broker(broker)
    api_server._state.update(
        {"agent": FailingAgent(), "busy": False, "chat_history": []}
    )
    try:
        response = await api_server.chat_stream(
            api_server.ChatRequest(message="fail", mode="build")
        )
        body = "".join([chunk async for chunk in response.body_iterator])

        events = _events(body)
        assert [event["type"] for event in events] == ["error", "done"]
        assert events[-1]["status"] == "failed"
        assert api_server._state["busy"] is False
        assert not api_server._chat_lock.locked()
        assert broker._sink is original_sink
        assert get_tui() is previous_tui
    finally:
        set_approval_broker(previous_broker)
        api_server._state.clear()
        api_server._state.update(previous)


async def test_slash_command_waits_for_chat_and_shared_cancel_handle_releases_it(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui

    chat_started = asyncio.Event()
    command_started = asyncio.Event()
    release_chat = asyncio.Event()
    observed: list[tuple[str, str | None]] = []

    class SharedAgent:
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history = []

        async def run(self, message: str, mode: str) -> str:
            observed.append(("chat", self._tool_tracer.run_id))
            get_tui().stream_token("started")
            chat_started.set()
            await release_chat.wait()
            return "chat complete"

        async def _execute_tool(self, name, args, **kwargs):
            observed.append(("command", self._tool_tracer.run_id))
            command_started.set()
            return "memory added"

    agent = SharedAgent()
    previous = dict(api_server._state)
    api_server._state.update({
        "agent": agent,
        "tui_proxy": api_server.APIProxyTUI(),
        "busy": False,
        "chat_history": [],
        "mode": "build",
    })
    try:
        response = await api_server.chat_stream(
            api_server.ChatRequest(message="blocking", mode="build")
        )
        consume_task = asyncio.create_task(
            _consume_body(response)
        )
        await asyncio.wait_for(chat_started.wait(), timeout=1)

        command_task = asyncio.create_task(api_server.command(
            api_server.CommandRequest(command="/memory add remembered")
        ))
        await asyncio.sleep(0.05)
        assert not command_started.is_set()
        assert api_server._api_run_lifecycle.active_kind == "chat_stream"

        cancel_result = await api_server.cancel_active_run()
        assert cancel_result["cancelled"] is True
        await asyncio.wait_for(consume_task, timeout=1)
        command_result = await asyncio.wait_for(command_task, timeout=1)

        assert command_result["action"] == "memory_add"
        assert command_started.is_set()
        assert [kind for kind, _run_id in observed] == ["chat", "command"]
        assert observed[0][1] != observed[1][1]
        assert agent._tool_tracer is None
        assert api_server._api_run_lifecycle.busy is False
    finally:
        release_chat.set()
        api_server._state.clear()
        api_server._state.update(previous)


async def _consume_body(response) -> str:
    return "".join([chunk async for chunk in response.body_iterator])
