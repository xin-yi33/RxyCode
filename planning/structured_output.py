"""Reliable structured-output parsing for planning pipeline LLM calls.

Models frequently wrap JSON in prose or Markdown fences.  Regex extraction is
not sufficient because plans contain nested arrays/objects and braces inside
strings.  This module scans balanced JSON values, validates them with Pydantic,
and gives the model one bounded repair attempt when validation fails.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError


ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised after structured output cannot be decoded and validated."""

    def __init__(self, message: str, *, response_text: str = "") -> None:
        super().__init__(message)
        self.response_text = response_text


def _response_text(content: object) -> str:
    """Normalize LangChain text and content-block responses to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if parts:
            return "\n".join(parts)
    return str(content or "")


def iter_balanced_json(text: str) -> Iterator[str]:
    """Yield balanced JSON object/array candidates found in arbitrary text.

    The scanner tracks nested containers, quoted strings, and escapes.  A bad
    early candidate does not prevent a later valid candidate from being tried.
    """
    for start, opening in enumerate(text):
        if opening not in "{[":
            continue

        stack = [opening]
        in_string = False
        escaped = False
        for index in range(start + 1, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in "{[":
                stack.append(char)
            elif char in "}]":
                expected = "{" if char == "}" else "["
                if not stack or stack[-1] != expected:
                    break
                stack.pop()
                if not stack:
                    yield text[start : index + 1]
                    break


def parse_structured_output(
    text: str,
    model_type: type[ModelT],
    *,
    root_key: str | None = None,
) -> ModelT:
    """Decode the first candidate that satisfies ``model_type``.

    ``root_key`` adapts an array response to an object Pydantic model, e.g. an
    array of tasks becomes ``{"tasks": [...]}`` for ``SubTaskList``.
    """
    failures: list[str] = []
    found_candidate = False
    for candidate in iter_balanced_json(text):
        found_candidate = True
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            failures.append(f"invalid JSON at position {exc.pos}: {exc.msg}")
            continue

        if root_key is not None and isinstance(value, list):
            value = {root_key: value}
        try:
            return model_type.model_validate(value)
        except ValidationError as exc:
            failures.append(str(exc))

    if not found_candidate:
        message = "No JSON object or array found in model response"
    else:
        detail = failures[-1] if failures else "no candidate matched the schema"
        message = f"JSON could not be validated: {detail}"
    raise StructuredOutputError(message, response_text=text)


def _repair_instruction(
    model_type: type[BaseModel],
    error: StructuredOutputError,
    *,
    root_key: str | None,
) -> str:
    schema = json.dumps(model_type.model_json_schema(), ensure_ascii=False)
    root_instruction = (
        f"Return a JSON array representing the '{root_key}' field."
        if root_key
        else "Return a JSON object."
    )
    return (
        "Your previous response could not be validated as the required JSON. "
        f"Validation error: {str(error)[:1500]}\n"
        f"{root_instruction} Return JSON only, with no Markdown fence or prose.\n"
        f"Required schema: {schema[:6000]}"
    )


async def invoke_structured_output(
    llm,
    messages: Sequence[BaseMessage],
    model_type: type[ModelT],
    *,
    root_key: str | None = None,
    repair_attempts: int = 1,
) -> ModelT:
    """Invoke an LLM and parse Pydantic output with a bounded repair retry."""
    if repair_attempts < 0 or repair_attempts > 1:
        raise ValueError("repair_attempts must be 0 or 1")

    request_messages = list(messages)
    last_error: StructuredOutputError | None = None
    for attempt in range(repair_attempts + 1):
        response = await llm.ainvoke(request_messages)
        text = _response_text(response.content)
        try:
            return parse_structured_output(text, model_type, root_key=root_key)
        except StructuredOutputError as exc:
            last_error = exc
            if attempt >= repair_attempts:
                raise
            request_messages = [
                *messages,
                AIMessage(content=text),
                HumanMessage(
                    content=_repair_instruction(model_type, exc, root_key=root_key)
                ),
            ]

    # The loop always returns or raises; this protects type checkers.
    assert last_error is not None
    raise last_error
