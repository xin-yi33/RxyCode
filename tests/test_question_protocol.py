"""Contracts for user questions, kept separate from safety approvals."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from RxyCode.RxyCode1_1_0.core.question import (
    QuestionOption,
    QuestionRequest,
    SseQuestionBroker,
    get_question_broker,
    set_question_broker,
)


pytestmark = pytest.mark.asyncio


async def test_choice_answer_crosses_thread_and_owner_loop() -> None:
    broker = SseQuestionBroker(timeout=2)
    published = asyncio.Event()
    event_holder: dict = {}

    def sink(event: dict) -> None:
        event_holder.update(event)
        published.set()

    broker.set_event_sink(sink)
    request = QuestionRequest(
        question="Choose a target",
        header="Runtime",
        options=[
            QuestionOption(label="Development", value="dev"),
            QuestionOption(label="Production", value="prod"),
        ],
    )
    task = asyncio.create_task(broker.ask(request))
    await published.wait()

    resolved: list[bool] = []
    async def resolve_from_another_loop() -> None:
        resolved.append(broker.resolve(request.question_id, "prod"))

    thread = threading.Thread(target=lambda: asyncio.run(resolve_from_another_loop()))
    thread.start()
    await asyncio.to_thread(thread.join)

    response = await task
    assert resolved == [True]
    assert response.answer == "prod"
    assert response.cancelled is False
    assert event_holder == {
        "type": "question_request",
        "question_id": request.question_id,
        "question": "Choose a target",
        "header": "Runtime",
        "options": [
            {"label": "Development", "value": "dev"},
            {"label": "Production", "value": "prod"},
        ],
        "input_type": "choice",
    }
    assert broker._pending == {}
    assert broker._pending_loops == {}
    assert broker._requests == {}
    assert broker._responses == {}


async def test_free_text_cancel_timeout_and_task_cancel_cleanup() -> None:
    free_text = SseQuestionBroker(timeout=2)
    free_text.set_event_sink(lambda _event: None)
    request = QuestionRequest(question="Name this release")
    task = asyncio.create_task(free_text.ask(request))
    await asyncio.sleep(0)
    assert free_text.resolve(request.question_id, "summer release")
    assert (await task).answer == "summer release"

    cancelled = SseQuestionBroker(timeout=2)
    cancelled.set_event_sink(lambda _event: None)
    request = QuestionRequest(question="Continue?")
    task = asyncio.create_task(cancelled.ask(request))
    await asyncio.sleep(0)
    assert cancelled.cancel(request.question_id)
    assert (await task).cancelled is True
    assert cancelled._pending == {}

    timed_out = SseQuestionBroker(timeout=0.01)
    timed_out.set_event_sink(lambda _event: None)
    response = await timed_out.ask(QuestionRequest(question="Too slow?"))
    assert response.timed_out is True
    assert timed_out._pending == {}

    abandoned = SseQuestionBroker(timeout=10)
    abandoned.set_event_sink(lambda _event: None)
    task = asyncio.create_task(abandoned.ask(QuestionRequest(question="Disconnect?")))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert abandoned._pending == {}
    assert abandoned._pending_loops == {}
    assert abandoned._requests == {}

    broken_sink = SseQuestionBroker(timeout=120)
    broken_sink.set_event_sink(
        lambda _event: (_ for _ in ()).throw(RuntimeError("stream closed"))
    )
    started_at = time.monotonic()
    response = await broken_sink.ask(QuestionRequest(question="Anyone there?"))
    assert time.monotonic() - started_at < 1
    assert response.unavailable is True
    assert broken_sink._pending == {}
    assert broken_sink._pending_loops == {}
    assert broken_sink._requests == {}


async def test_choice_rejects_unoffered_values_without_resolving() -> None:
    broker = SseQuestionBroker(timeout=2)
    broker.set_event_sink(lambda _event: None)
    request = QuestionRequest(
        question="Choose",
        options=[QuestionOption(label="One", value="one")],
    )
    task = asyncio.create_task(broker.ask(request))
    await asyncio.sleep(0)
    with pytest.raises(ValueError, match="offered option"):
        broker.resolve(request.question_id, "approved")
    assert not task.done()
    assert broker.cancel(request.question_id)
    assert (await task).cancelled


async def test_stream_disconnect_cleans_its_pending_question() -> None:
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions_async

    class AskingAgent:
        model_config = {"model_name": "test-model"}
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history: list[str] = []

        async def run(self, _message: str, mode: str = "build") -> str:
            return await ask_questions_async([{"question": "Still there?"}])

        def get_thinking_history(self) -> str:
            return ""

    previous_state = dict(api_server._state)
    previous_broker = get_question_broker()
    broker = SseQuestionBroker(timeout=10)
    api_server._state.update(
        {
            "agent": AskingAgent(),
            "tui_proxy": api_server.APIProxyTUI(),
            "busy": False,
            "chat_history": [],
            "mode": "build",
        }
    )
    set_question_broker(broker)
    response = await api_server.chat_stream(
        api_server.ChatRequest(message="ask", mode="build")
    )
    stream = response.body_iterator.__aiter__()
    try:
        first = await asyncio.wait_for(stream.__anext__(), timeout=2)
        assert '"type": "question_request"' in first
        assert broker._pending
        await stream.aclose()
        assert broker._pending == {}
        assert broker._pending_loops == {}
        assert broker._requests == {}
        assert broker._responses == {}
        assert api_server._state["busy"] is False
    finally:
        await stream.aclose()
        set_question_broker(previous_broker)
        api_server._state.clear()
        api_server._state.update(previous_state)


async def test_non_stream_chat_fails_fast_when_question_channel_is_unavailable() -> None:
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions_async

    class AskingAgent:
        model_config = {"model_name": "test-model"}
        _tool_tracer = None
        _thinking_history: list[str] = []

        async def run(self, _message: str, mode: str = "build") -> str:
            return await ask_questions_async([{"question": "No SSE here?"}])

    previous_state = dict(api_server._state)
    previous_broker = get_question_broker()
    api_server._state.update(
        {
            "agent": AskingAgent(),
            "tui_proxy": api_server.APIProxyTUI(),
            "chat_history": [],
            "mode": "build",
        }
    )
    set_question_broker(SseQuestionBroker(timeout=120))
    started_at = time.monotonic()
    try:
        response = await api_server.chat(
            api_server.ChatRequest(message="ask", mode="build")
        )
        assert time.monotonic() - started_at < 1
        assert response.response == "A1: [no input: question channel unavailable]"
        assert get_question_broker()._pending == {}
    finally:
        set_question_broker(previous_broker)
        api_server._state.clear()
        api_server._state.update(previous_state)


async def test_api_question_round_trip_and_bearer_contract() -> None:
    from fastapi.testclient import TestClient
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions_async

    class AskingAgent:
        model_config = {"model_name": "test-model"}
        _stream_mode = False
        _tool_tracer = None
        _last_thinking = ""
        _thinking_history: list[str] = []

        async def run(self, _message: str, mode: str = "build") -> str:
            return await ask_questions_async([
                {
                    "question": "Choose a target",
                    "header": "Runtime",
                    "options": [
                        {"label": "Development", "value": "dev"},
                        {"label": "Production", "value": "prod"},
                    ],
                }
            ])

        def get_thinking_history(self) -> str:
            return ""

    previous_state = dict(api_server._state)
    previous_broker = get_question_broker()
    api_server._state.update(
        {
            "agent": AskingAgent(),
            "tui_proxy": api_server.APIProxyTUI(),
            "busy": False,
            "chat_history": [],
            "mode": "build",
        }
    )
    broker = SseQuestionBroker(timeout=5)
    token = api_server.configure_api_token()
    stream_result: dict[str, object] = {}

    try:
        with TestClient(
            api_server.app,
            client=("127.0.0.1", 50000),
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            # Lifespan installs its own instance; this broker is shared by the
            # stream thread and the response endpoint for the contract test.
            set_question_broker(broker)

            def run_stream() -> None:
                stream_result["response"] = client.post(
                    "/chat/stream",
                    json={"message": "ask", "mode": "build"},
                )

            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()
            deadline = time.monotonic() + 5
            while not broker._pending and time.monotonic() < deadline:
                time.sleep(0.01)
            assert broker._pending, "question never entered pending registry"
            question_id = next(iter(broker._pending))

            unauthorized = client.post(
                "/question/respond",
                json={"question_id": question_id, "answer": "prod"},
                headers={"Authorization": ""},
            )
            assert unauthorized.status_code == 401

            invalid = client.post(
                "/question/respond",
                json={"question_id": question_id, "answer": "approved"},
            )
            assert invalid.status_code == 422
            assert question_id in broker._pending

            accepted = client.post(
                "/question/respond",
                json={"question_id": question_id, "answer": "prod"},
            )
            assert accepted.status_code == 200
            assert accepted.json() == {"ok": True}

            thread.join(timeout=5)
            assert not thread.is_alive()
            response = stream_result["response"]
            assert response.status_code == 200
            assert '"type": "question_request"' in response.text
            assert '"value": "prod"' in response.text
            assert "A1: prod" in response.text
            assert question_id not in broker._pending
            assert broker._responses == {}
    finally:
        set_question_broker(previous_broker)
        api_server._state.clear()
        api_server._state.update(previous_state)
