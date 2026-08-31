"""Executor /full path must keep DeepSeek Responses reasoning on the next turn."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from RxyCode.RxyCode1_1_0.core.state import TaskNode
from RxyCode.RxyCode1_1_0.execution.executor import Executor


def _responses_sse(*events: dict) -> bytes:
    parts = [
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ]
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


def _deepseek_reasoning_sse_events(
    segments: tuple[str, ...] = ("Plan first.", " Then read."),
    *,
    kind: str = "content",
    distinct_indexes: bool = False,
) -> list[dict]:
    part_type = "summary_text" if kind == "summary" else "reasoning_text"
    delta_type = (
        "response.reasoning_summary_text.delta"
        if kind == "summary"
        else "response.reasoning_text.delta"
    )
    snapshot_parts = [{"type": part_type, "text": text} for text in segments]
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": snapshot_parts if kind == "summary" else [],
        "status": "completed",
    }
    if kind == "content":
        reasoning_item["content"] = snapshot_parts
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
    events = [
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
    ]
    sequence = 2
    for offset, text in enumerate(segments):
        delta = {
            "type": delta_type,
            "delta": text,
            "item_id": "rs_1",
            "output_index": 0,
            "sequence_number": sequence,
        }
        index = offset if distinct_indexes else 0
        if kind == "summary":
            delta["summary_index"] = index
        else:
            delta["content_index"] = index
        events.append(delta)
        sequence += 1
    events.append(
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "sequence_number": sequence,
            "item": reasoning_item,
        }
    )
    sequence += 1
    events.extend(
        [
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "sequence_number": sequence,
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
                "sequence_number": sequence + 1,
            },
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "sequence_number": sequence + 2,
                "item": function_item,
            },
            {
                "type": "response.completed",
                "sequence_number": sequence + 3,
                "response": response,
            },
        ]
    )
    return events


class _OrchestratorStub:
    def __init__(self, tools):
        self.tools = tools

    def select_safe_tools(self, hints, config, **kwargs):
        del hints, config, kwargs
        return self.tools

    def begin_evidence_capture(self):
        return object()

    def end_evidence_capture(self, token):
        del token
        return []


async def _executor_followup_payload(monkeypatch, sse_events: list[dict]) -> dict:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-" + uuid4().hex)
    monkeypatch.setenv("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        body["_url"] = str(request.url)
        captured.append(body)
        if len(captured) == 1:
            body = _responses_sse(*sse_events)
        else:
            body = _responses_sse(
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {
                        "id": "resp_followup",
                        "created_at": 0.0,
                        "model": "deepseek-reasoner",
                        "object": "response",
                        "output": [],
                        "parallel_tool_calls": True,
                        "tool_choice": "auto",
                        "tools": [],
                        "status": "in_progress",
                    },
                },
                {
                    "type": "response.output_text.delta",
                    "delta": "done",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "sequence_number": 1,
                    "logprobs": [],
                },
                {
                    "type": "response.completed",
                    "sequence_number": 2,
                    "response": {
                        "id": "resp_followup",
                        "created_at": 0.0,
                        "model": "deepseek-reasoner",
                        "object": "response",
                        "output": [
                            {
                                "id": "msg_1",
                                "type": "message",
                                "role": "assistant",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "done",
                                        "annotations": [],
                                    }
                                ],
                            }
                        ],
                        "parallel_tool_calls": True,
                        "tool_choice": "auto",
                        "tools": [],
                        "status": "completed",
                    },
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = ChatOpenAI(
        model="deepseek-reasoner",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        use_responses_api=True,
        streaming=True,
        http_async_client=client,
        http_socket_options=(),
    )

    def read(p: str) -> str:
        """Read a path."""
        del p
        return "ok"

    tool = StructuredTool.from_function(read)
    executor = Executor(
        llm,
        _OrchestratorStub([tool]),
        config={"execution": {"max_tool_rounds": 4}},
    )
    try:
        await executor.execute_with_evidence(
            TaskNode(title="read file", description="read x", tools_hint=["read"])
        )
    finally:
        await client.aclose()

    assert len(captured) >= 2, "follow-up request never reached the transport"
    return captured[1]


def _assert_reasoning_segments(payload: dict, segments: tuple[str, ...]) -> None:
    dump = json.dumps(payload)
    assert "_rxy_reasoning_snapshot" not in dump
    wire = payload.get("input") or []
    reasoning_items = [item for item in wire if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 1
    reasoning = reasoning_items[0]
    assert reasoning.get("status") in {None, "completed"}
    parts = reasoning.get("content") or reasoning.get("summary") or []
    reasoning_text = "".join(
        str(part.get("text") or "") for part in parts if isinstance(part, dict)
    )
    joined = "".join(segments)
    assert reasoning_text == joined
    for segment in segments:
        assert reasoning_text.count(segment) == 1


@pytest.mark.asyncio
async def test_executor_sse_followup_keeps_reasoning_text_once(monkeypatch):
    payload = await _executor_followup_payload(
        monkeypatch, _deepseek_reasoning_sse_events()
    )
    _assert_reasoning_segments(payload, ("Plan first.", " Then read."))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("segments", "kind"),
    [
        (("Plan first.", " Then read."), "content"),
        (("Plan first.", " Then read.", " Then write."), "content"),
        (("Plan first.", " Then read."), "summary"),
        (("Plan first.", " Then read.", " Then write."), "summary"),
    ],
)
async def test_executor_sse_multipart_reasoning_segments_appear_once(
    monkeypatch, segments, kind
):
    payload = await _executor_followup_payload(
        monkeypatch,
        _deepseek_reasoning_sse_events(
            segments, kind=kind, distinct_indexes=True
        ),
    )
    _assert_reasoning_segments(payload, segments)
