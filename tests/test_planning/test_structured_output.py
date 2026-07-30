"""Structured LLM output parsing and repair tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel


class _NestedResult(BaseModel):
    name: str
    metadata: dict[str, object]


def _response(content: str):
    response = MagicMock()
    response.content = content
    return response


def test_balanced_parser_handles_fences_nested_values_and_braces_in_strings():
    from RxyCode.RxyCode1_1_0.planning.structured_output import parse_structured_output

    result = parse_structured_output(
        'Explanation first.\n```json\n'
        '{"name":"demo {literal}","metadata":{"items":[1,{"ok":true}]}}'
        '\n```\nTrailing prose.',
        _NestedResult,
    )

    assert result.name == "demo {literal}"
    assert result.metadata == {"items": [1, {"ok": True}]}


@pytest.mark.asyncio
async def test_invalid_model_output_gets_exactly_one_repair_attempt():
    from RxyCode.RxyCode1_1_0.planning.structured_output import invoke_structured_output

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        side_effect=[
            _response('{"name": 123, "metadata": "wrong"}'),
            _response('{"name":"fixed","metadata":{"source":"repair"}}'),
        ]
    )

    result = await invoke_structured_output(
        llm,
        [HumanMessage(content="Return the object")],
        _NestedResult,
    )

    assert result.name == "fixed"
    assert llm.ainvoke.await_count == 2
    repair_messages = llm.ainvoke.await_args_list[1].args[0]
    assert "could not be validated" in repair_messages[-1].content
    assert "metadata" in repair_messages[-1].content


@pytest.mark.asyncio
async def test_second_invalid_response_raises_without_a_third_call():
    from RxyCode.RxyCode1_1_0.planning.structured_output import (
        StructuredOutputError,
        invoke_structured_output,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        side_effect=[_response("not json"), _response("still not json")]
    )

    with pytest.raises(StructuredOutputError):
        await invoke_structured_output(
            llm,
            [HumanMessage(content="Return the object")],
            _NestedResult,
        )

    assert llm.ainvoke.await_count == 2
