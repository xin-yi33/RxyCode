"""DeepSeek/OpenAI Responses chunk normalization."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _construct_responses_api_input,
    _convert_responses_chunk_to_generation_chunk,
)
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseReasoningItem,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningTextDeltaEvent,
)

from core.providers import responses_adapter as responses_adapter_mod
from core.providers.responses_adapter import (
    accumulate_reasoning_items,
    assistant_content_for_responses_replay,
    astream_with_native_reasoning_events,
    build_responses_replay_input,
    convert_responses_sdk_event,
    finalize_responses_reasoning_item,
    install_langchain_responses_reasoning_patch,
    reasoning_item_for_replay,
    responses_stream_as_chat_chunks,
)


@pytest.mark.asyncio
async def test_adapter_reads_deepseek_reasoning_text_parts():
    async def source():
        yield SimpleNamespace(
            content=[
                {
                    "id": "rs_1",
                    "type": "reasoning",
                    "status": "completed",
                    "content": [
                        {"type": "reasoning_text", "text": "first thought"}
                    ],
                },
                {"type": "output_text", "text": "answer"},
            ],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position=None,
        )
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    chunks = [chunk async for chunk in responses_stream_as_chat_chunks(source())]
    assert chunks[0].choices[0].delta.reasoning_content == "first thought"
    assert chunks[0].choices[0].delta.content == "answer"
    assert chunks[0]._rxy_reasoning_items[0]["id"] == "rs_1"
    assert chunks[0]._rxy_reasoning_items[0]["type"] == "reasoning"


@pytest.mark.asyncio
async def test_adapter_still_reads_openai_reasoning_summary():
    async def source():
        yield SimpleNamespace(
            content=[
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "brief"}],
                }
            ],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position=None,
        )
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    chunks = [chunk async for chunk in responses_stream_as_chat_chunks(source())]
    assert chunks[0].choices[0].delta.reasoning_content == "brief"


def test_responses_replay_input_is_reasoning_then_function_call_then_output():
    items = []
    accumulate_reasoning_items(
        items,
        [
            {
                "id": "rs_1",
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "plan"}],
            }
        ],
    )
    content = assistant_content_for_responses_replay(items, "")
    messages = [
        HumanMessage(content="weather?"),
        AIMessage(
            content=content,
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "Hangzhou"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
            additional_kwargs={"responses_reasoning_items": items},
        ),
        ToolMessage(content="24C", tool_call_id="call_1"),
    ]
    wire = build_responses_replay_input(messages)
    assert [item["type"] for item in wire] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert wire[1]["id"] == "rs_1"
    assert wire[2]["call_id"] == "call_1"
    assert wire[3]["output"] == "24C"


@pytest.mark.asyncio
async def test_streamed_reasoning_fragments_replay_as_one_item_with_id():
    """First fragment has id+index; later summary deltas usually have only index."""
    events = [
        ResponseOutputItemAddedEvent(
            item=ResponseReasoningItem(id="rs_1", type="reasoning", summary=[]),
            output_index=0,
            sequence_number=1,
            type="response.output_item.added",
        ),
        ResponseReasoningSummaryTextDeltaEvent(
            delta="Plan first.",
            item_id="rs_1",
            output_index=0,
            sequence_number=2,
            summary_index=0,
            type="response.reasoning_summary_text.delta",
        ),
        ResponseReasoningSummaryTextDeltaEvent(
            delta=" Then read.",
            item_id="rs_1",
            output_index=0,
            sequence_number=3,
            summary_index=0,
            type="response.reasoning_summary_text.delta",
        ),
        ResponseOutputItemAddedEvent(
            item=ResponseFunctionToolCall(
                arguments="",
                call_id="call_1",
                name="read",
                type="function_call",
                id="fc_1",
                status="in_progress",
            ),
            output_index=1,
            sequence_number=4,
            type="response.output_item.added",
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            delta='{"p":"x"}',
            item_id="fc_1",
            output_index=1,
            sequence_number=5,
            type="response.function_call_arguments.delta",
        ),
    ]
    index = output_index = sub_index = 0
    fragments = []
    for event in events:
        index, output_index, sub_index, generation = (
            _convert_responses_chunk_to_generation_chunk(
                event,
                index,
                output_index,
                sub_index,
            )
        )
        if generation is not None:
            fragments.append(generation.message)

    async def source():
        for fragment in fragments:
            yield fragment
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    store: list[dict] = []
    async for chunk in responses_stream_as_chat_chunks(source()):
        accumulate_reasoning_items(
            store,
            getattr(chunk, "_rxy_reasoning_items", None) or [],
        )

    content = assistant_content_for_responses_replay(store, "")
    messages = [
        HumanMessage(content="q"),
        AIMessage(
            content=content,
            tool_calls=[
                {
                    "name": "read",
                    "args": {"p": "x"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="ok", tool_call_id="call_1"),
    ]
    wire = _construct_responses_api_input(messages)
    reasoning_items = [item for item in wire if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 1
    assert reasoning_items[0]["id"] == "rs_1"
    assert reasoning_items[0]["summary"] == [
        {"type": "summary_text", "text": "Plan first. Then read."}
    ]
    assert "index" not in reasoning_items[0]
    assert "content" not in reasoning_items[0]
    assert [item.get("type") for item in wire] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]


def test_langchain_responses_input_replays_reasoning_items_before_tools():
    reasoning = {
        "id": "rs_1",
        "type": "reasoning",
        "content": [{"type": "reasoning_text", "text": "plan"}],
    }
    messages = [
        HumanMessage(content="weather?"),
        AIMessage(
            content=assistant_content_for_responses_replay([reasoning], ""),
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "Hangzhou"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="24C", tool_call_id="call_1"),
    ]
    wire = _construct_responses_api_input(messages)
    assert [item.get("type") for item in wire] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]


def test_langchain_converter_drops_native_reasoning_text_events():
    delta = ResponseReasoningTextDeltaEvent(
        content_index=0,
        delta="Plan first.",
        item_id="rs_1",
        output_index=0,
        sequence_number=2,
        type="response.reasoning_text.delta",
    )
    done = ResponseOutputItemDoneEvent(
        item=ResponseReasoningItem(
            id="rs_1",
            type="reasoning",
            summary=[],
            status="completed",
            content=[{"type": "reasoning_text", "text": "Plan first."}],
        ),
        output_index=0,
        sequence_number=3,
        type="response.output_item.done",
    )
    _, _, _, delta_generation = _convert_responses_chunk_to_generation_chunk(
        delta, 0, 0, 0
    )
    _, _, _, done_generation = _convert_responses_chunk_to_generation_chunk(
        done, 0, 0, 0
    )
    assert delta_generation is None
    assert done_generation is None


def test_sdk_event_converter_keeps_native_reasoning_text_events():
    added = ResponseOutputItemAddedEvent(
        item=ResponseReasoningItem(id="rs_1", type="reasoning", summary=[]),
        output_index=0,
        sequence_number=1,
        type="response.output_item.added",
    )
    delta = ResponseReasoningTextDeltaEvent(
        content_index=0,
        delta="Plan first.",
        item_id="rs_1",
        output_index=0,
        sequence_number=2,
        type="response.reasoning_text.delta",
    )
    done = ResponseOutputItemDoneEvent(
        item=ResponseReasoningItem(
            id="rs_1",
            type="reasoning",
            summary=[],
            status="completed",
            content=[{"type": "reasoning_text", "text": "Plan first."}],
        ),
        output_index=0,
        sequence_number=3,
        type="response.output_item.done",
    )
    index = output_index = sub_index = -1
    generations = []
    for event in (added, delta, done):
        index, output_index, sub_index, generation = convert_responses_sdk_event(
            event, index, output_index, sub_index
        )
        if generation is not None:
            generations.append(generation.message.content)
    assert generations[0][0]["id"] == "rs_1"
    assert generations[1][0]["content"][0]["text"] == "Plan first."
    assert generations[2][0]["status"] == "completed"
    assert generations[2][0]["id"] == "rs_1"


@pytest.mark.parametrize(
    ("field", "part_type", "segments"),
    [
        (
            "content",
            "reasoning_text",
            ["Plan first.", " Then read."],
        ),
        (
            "content",
            "reasoning_text",
            ["Plan first.", " Then read.", " Then write."],
        ),
        (
            "summary",
            "summary_text",
            ["Plan first.", " Then read."],
        ),
        (
            "summary",
            "summary_text",
            ["Plan first.", " Then read.", " Then write."],
        ),
    ],
)
def test_finalize_uses_done_snapshot_instead_of_prefix_guess(field, part_type, segments):
    joined = "".join(segments)
    delta_parts = [
        {"index": index, "type": part_type, "text": text}
        for index, text in enumerate(segments)
    ]
    snapshot_parts = [{"type": part_type, "text": text} for text in segments]
    block = {
        "id": "rs_1",
        "type": "reasoning",
        "status": "completed",
        "_rxy_reasoning_snapshot": True,
        field: [*delta_parts, *snapshot_parts],
    }
    out = finalize_responses_reasoning_item(block)
    parts = out.get(field) or []
    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    assert text == joined
    for segment in segments:
        assert text.count(segment) == 1
    assert "_rxy_reasoning_snapshot" not in out


def test_finalize_collapses_concatenated_snapshot_appended_to_indexed_deltas():
    block = {
        "id": "rs_1",
        "type": "reasoning",
        "_rxy_reasoning_snapshot": True,
        "content": [
            {"index": 0, "type": "reasoning_text", "text": "Plan first."},
            {"index": 1, "type": "reasoning_text", "text": " Then read."},
            {"type": "reasoning_text", "text": "Plan first. Then read."},
        ],
    }
    out = finalize_responses_reasoning_item(block)
    text = "".join(
        str(part.get("text") or "")
        for part in (out.get("content") or [])
        if isinstance(part, dict)
    )
    assert text == "Plan first. Then read."
    assert text.count("Then read.") == 1


async def _stream_reasoning_events(events):
    index = output_index = sub_index = -1
    fragments = []
    for event in events:
        index, output_index, sub_index, generation = convert_responses_sdk_event(
            event, index, output_index, sub_index
        )
        if generation is not None:
            fragments.append(generation.message)

    async def source():
        for fragment in fragments:
            yield fragment
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    store: list[dict] = []
    streamed: list[str] = []
    async for chunk in responses_stream_as_chat_chunks(source()):
        delta = chunk.choices[0].delta
        text = getattr(delta, "reasoning_content", None) or ""
        if text:
            streamed.append(text)
        accumulate_reasoning_items(
            store,
            getattr(chunk, "_rxy_reasoning_items", None) or [],
        )
    replay = [reasoning_item_for_replay(item) for item in store]
    return "".join(streamed), replay


def _reasoning_added():
    return ResponseOutputItemAddedEvent(
        item=ResponseReasoningItem(id="rs_1", type="reasoning", summary=[]),
        output_index=0,
        sequence_number=1,
        type="response.output_item.added",
    )


def _reasoning_text_delta(text: str, sequence_number: int):
    return ResponseReasoningTextDeltaEvent(
        content_index=0,
        delta=text,
        item_id="rs_1",
        output_index=0,
        sequence_number=sequence_number,
        type="response.reasoning_text.delta",
    )


def _reasoning_summary_delta(text: str, sequence_number: int):
    return ResponseReasoningSummaryTextDeltaEvent(
        delta=text,
        item_id="rs_1",
        output_index=0,
        sequence_number=sequence_number,
        summary_index=0,
        type="response.reasoning_summary_text.delta",
    )


def _reasoning_done(*, with_status: bool, body: str, as_summary: bool):
    item_kwargs = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": (
            [{"type": "summary_text", "text": body}] if as_summary else []
        ),
    }
    if not as_summary:
        item_kwargs["content"] = [{"type": "reasoning_text", "text": body}]
    if with_status:
        item_kwargs["status"] = "completed"
    return ResponseOutputItemDoneEvent(
        item=ResponseReasoningItem(**item_kwargs),
        output_index=0,
        sequence_number=9,
        type="response.output_item.done",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "as_summary"),
    [
        (
            [
                _reasoning_added(),
                _reasoning_text_delta("Plan first.", 2),
                _reasoning_text_delta(" Then read.", 3),
                _reasoning_done(
                    with_status=True, body="Plan first. Then read.", as_summary=False
                ),
            ],
            False,
        ),
        (
            [
                _reasoning_added(),
                _reasoning_text_delta("Plan first.", 2),
                _reasoning_text_delta(" Then read.", 3),
                _reasoning_done(
                    with_status=False, body="Plan first. Then read.", as_summary=False
                ),
            ],
            False,
        ),
        (
            [
                _reasoning_added(),
                _reasoning_done(
                    with_status=False, body="Plan first. Then read.", as_summary=False
                ),
            ],
            False,
        ),
        (
            [
                _reasoning_added(),
                _reasoning_summary_delta("Plan first.", 2),
                _reasoning_summary_delta(" Then read.", 3),
                _reasoning_done(
                    with_status=False, body="Plan first. Then read.", as_summary=True
                ),
            ],
            True,
        ),
    ],
)
async def test_reasoning_done_snapshot_does_not_duplicate_stream_or_replay(
    events, as_summary
):
    streamed, replay = await _stream_reasoning_events(events)
    assert streamed == "Plan first. Then read."
    assert len(replay) == 1
    assert replay[0]["id"] == "rs_1"
    assert "_rxy_reasoning_snapshot" not in replay[0]
    assert "index" not in replay[0]
    if as_summary:
        assert replay[0]["summary"] == [
            {"type": "summary_text", "text": "Plan first. Then read."}
        ]
    else:
        assert replay[0].get("content") == [
            {"type": "reasoning_text", "text": "Plan first. Then read."}
        ]


def _deepseek_reasoning_sse_events() -> list[dict]:
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "status": "completed",
        "content": [
            {"type": "reasoning_text", "text": "Plan first. Then read."}
        ],
    }
    function_item = {
        "id": "fc_1",
        "type": "function_call",
        "name": "read",
        "arguments": '{"p":"x"}',
        "call_id": "call_1",
        "status": "completed",
    }
    response = {
        "id": "resp_test",
        "created_at": 0.0,
        "model": "deepseek-reasoner",
        "object": "response",
        "output": [reasoning_item, function_item],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "usage": {
            "input_tokens": 8,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 6,
            "output_tokens_details": {"reasoning_tokens": 4},
            "total_tokens": 14,
        },
    }
    return [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {**response, "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "sequence_number": 1,
            "item": {
                "id": "rs_1",
                "type": "reasoning",
                "summary": [],
                "status": "in_progress",
            },
        },
        {
            "type": "response.reasoning_text.delta",
            "delta": "Plan first.",
            "item_id": "rs_1",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 2,
        },
        {
            "type": "response.reasoning_text.delta",
            "delta": " Then read.",
            "item_id": "rs_1",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 3,
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "sequence_number": 4,
            "item": reasoning_item,
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "sequence_number": 5,
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "name": "read",
                "arguments": "",
                "call_id": "call_1",
                "status": "in_progress",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "delta": '{"p":"x"}',
            "item_id": "fc_1",
            "output_index": 1,
            "sequence_number": 6,
        },
        {
            "type": "response.output_item.done",
            "output_index": 1,
            "sequence_number": 7,
            "item": function_item,
        },
        {
            "type": "response.completed",
            "sequence_number": 8,
            "response": response,
        },
    ]


def _responses_sse(*events: dict) -> bytes:
    parts = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events]
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


@pytest.mark.asyncio
async def test_raw_sse_reasoning_text_replays_on_next_responses_request(
    monkeypatch,
):
    """DeepSeek native reasoning is dropped by langchain-openai 1.3.3 unless
    the SDK event layer keeps reasoning_text.delta / output_item.done.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-" + uuid4().hex)
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/responses"):
            try:
                captured.append(json.loads(request.content.decode()))
            except (UnicodeDecodeError, json.JSONDecodeError):
                captured.append({})
            if len(captured) == 1:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=_responses_sse(*_deepseek_reasoning_sse_events()),
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "id": "resp_followup",
                    "object": "response",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "done"}
                            ],
                        }
                    ],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = ChatOpenAI(
        model="deepseek-reasoner",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        use_responses_api=True,
        http_async_client=client,
    )
    install_langchain_responses_reasoning_patch()
    try:
        store: list[dict] = []
        streamed: list[str] = []
        async for chunk in responses_stream_as_chat_chunks(
            astream_with_native_reasoning_events(
                llm.astream([HumanMessage(content="q")])
            )
        ):
            text = getattr(chunk.choices[0].delta, "reasoning_content", None) or ""
            if text:
                streamed.append(text)
            accumulate_reasoning_items(
                store,
                getattr(chunk, "_rxy_reasoning_items", None) or [],
            )
        assert "".join(streamed) == "Plan first. Then read."
        content = assistant_content_for_responses_replay(store, "")
        followup = [
            HumanMessage(content="q"),
            AIMessage(
                content=content,
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"p": "x"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content="ok", tool_call_id="call_1"),
        ]
        await llm.ainvoke(followup)
    finally:
        await client.aclose()

    expected_reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "content": [
            {"type": "reasoning_text", "text": "Plan first. Then read."}
        ],
    }
    constructed = _construct_responses_api_input(followup)
    constructed_reasoning = [
        item for item in constructed if item.get("type") == "reasoning"
    ]
    assert len(constructed_reasoning) == 1
    assert constructed_reasoning[0]["id"] == expected_reasoning["id"]
    assert constructed_reasoning[0].get("content") == expected_reasoning["content"]
    assert "index" not in constructed_reasoning[0]
    assert [item.get("type") for item in constructed] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert len(captured) >= 2, "follow-up request never reached the transport"
    wire = captured[-1].get("input")
    assert isinstance(wire, list)
    live_reasoning = [item for item in wire if item.get("type") == "reasoning"]
    assert len(live_reasoning) == 1
    assert live_reasoning[0]["id"] == "rs_1"
    assert live_reasoning[0].get("content") == expected_reasoning["content"]


@pytest.mark.asyncio
async def test_native_reasoning_stream_survives_wait_for_anext():
    """AgentV2 drives streams with wait_for(anext); each call is a new Context."""
    seen_inside: list[bool] = []

    async def source():
        seen_inside.append(responses_adapter_mod._NATIVE_REASONING_EVENTS.get())
        yield "partial"
        seen_inside.append(responses_adapter_mod._NATIVE_REASONING_EVENTS.get())
        raise RuntimeError("endpoint disappeared")

    stream = astream_with_native_reasoning_events(source())
    first = await asyncio.create_task(stream.__anext__())
    assert first == "partial"
    with pytest.raises(RuntimeError, match="endpoint disappeared"):
        await asyncio.create_task(stream.__anext__())
    await stream.aclose()
    assert seen_inside == [True, True]


class _ScriptedResponsesAgentModel(ChatOpenAI):
    """create_agent ainvoke stand-in that records Responses payloads."""

    def __init__(self, *args, scripted_messages, payloads, **kwargs):
        super().__init__(*args, **kwargs)
        self._scripted_messages = list(scripted_messages)
        self._payloads = payloads

    def _get_request_payload(self, input_, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        self._payloads.append(payload)
        return payload

    async def ainvoke(self, input, config=None, **kwargs):
        self._get_request_payload(input, **kwargs)
        if not self._scripted_messages:
            return AIMessage(content="done")
        return self._scripted_messages.pop(0)


def _merged_stream_aimessage(events) -> AIMessage:
    """LangChain default aggregation of patched Responses chunks."""
    from langchain_core.messages import AIMessageChunk

    index = output_index = sub_index = -1
    merged = None
    for event in events:
        index, output_index, sub_index, generation = convert_responses_sdk_event(
            event, index, output_index, sub_index
        )
        if generation is None:
            continue
        chunk = generation.message
        if not isinstance(chunk, AIMessageChunk):
            chunk = AIMessageChunk(content=getattr(chunk, "content", []))
        merged = chunk if merged is None else merged + chunk
    assert merged is not None
    return AIMessage(
        content=merged.content,
        tool_calls=getattr(merged, "tool_calls", None) or [],
        additional_kwargs=getattr(merged, "additional_kwargs", None) or {},
        id=getattr(merged, "id", None),
    )


@pytest.mark.asyncio
async def test_create_agent_followup_request_collapses_reasoning_snapshot(
    monkeypatch,
):
    from langchain.agents import create_agent
    from langchain_core.tools import tool
    from openai.types.responses import (
        ResponseFunctionCallArgumentsDeltaEvent,
        ResponseFunctionToolCall,
        ResponseOutputItemAddedEvent,
        ResponseOutputItemDoneEvent,
    )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-" + uuid4().hex)
    install_langchain_responses_reasoning_patch()
    dirty = _merged_stream_aimessage(
        [
            _reasoning_added(),
            _reasoning_text_delta("Plan first.", 2),
            _reasoning_text_delta(" Then read.", 3),
            _reasoning_done(
                with_status=True, body="Plan first. Then read.", as_summary=False
            ),
            ResponseOutputItemAddedEvent(
                item=ResponseFunctionToolCall(
                    arguments="",
                    call_id="call_1",
                    name="read",
                    type="function_call",
                    id="fc_1",
                    status="in_progress",
                ),
                output_index=1,
                sequence_number=10,
                type="response.output_item.added",
            ),
            ResponseFunctionCallArgumentsDeltaEvent(
                delta='{"p":"x"}',
                item_id="fc_1",
                output_index=1,
                sequence_number=11,
                type="response.function_call_arguments.delta",
            ),
            ResponseOutputItemDoneEvent(
                item=ResponseFunctionToolCall(
                    arguments='{"p":"x"}',
                    call_id="call_1",
                    name="read",
                    type="function_call",
                    id="fc_1",
                    status="completed",
                ),
                output_index=1,
                sequence_number=12,
                type="response.output_item.done",
            ),
        ]
    )
    assert dirty.tool_calls
    payloads: list[dict] = []
    llm = _ScriptedResponsesAgentModel(
        model="deepseek-reasoner",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        use_responses_api=True,
        http_socket_options=(),
        scripted_messages=[dirty, AIMessage(content="done")],
        payloads=payloads,
    )

    @tool
    def read(p: str) -> str:
        """Read a path."""
        return "ok"

    agent = create_agent(llm, [read])
    await agent.ainvoke({"messages": [("user", "q")]})

    assert len(payloads) >= 2, "follow-up request never built a Responses payload"
    payload = payloads[1]
    assert "_rxy_reasoning_snapshot" not in json.dumps(payload)
    wire = payload.get("input") or []
    reasoning_items = [item for item in wire if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 1
    reasoning = reasoning_items[0]
    assert reasoning.get("status") in {None, "completed"}
    parts = reasoning.get("content") or reasoning.get("summary") or []
    reasoning_text = "".join(
        str(part.get("text") or "") for part in parts if isinstance(part, dict)
    )
    assert reasoning_text == "Plan first. Then read."
