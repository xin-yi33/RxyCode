"""LangChain Responses public-chunk → RxyCode internal stream.

Stdlib-only. Stress harnesses can import this without loading AgentV2 or the
installed ``RxyCode.RxyCode1_1_0`` package.
"""

from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator

_NATIVE_REASONING_EVENTS = contextvars.ContextVar(
    "rxy_native_reasoning_events", default=False
)


def _text_from_part(part: object) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(getattr(part, "text", "") or "")
    return str(part.get("text") or "")


def _reasoning_from_block(block: dict) -> str:
    """OpenAI uses ``summary[].text``; DeepSeek uses ``reasoning_text`` parts."""
    parts: list[str] = []
    for summary in block.get("summary") or []:
        text = _text_from_part(summary)
        if text:
            parts.append(text)
    content = block.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                text = _text_from_part(part)
                if text:
                    parts.append(text)
                continue
            if str(part.get("type") or "") in {"reasoning_text", "text", "summary_text"}:
                text = _text_from_part(part)
                if text:
                    parts.append(text)
    elif isinstance(content, str) and content:
        parts.append(content)
    direct = block.get("text")
    if isinstance(direct, str) and direct and not parts:
        parts.append(direct)
    return "".join(parts)


_SNAPSHOT_FLAG = "_rxy_reasoning_snapshot"
_NATIVE_REASONING_KEYS = {
    "id",
    "type",
    "status",
    "content",
    "summary",
    "encrypted_content",
    "index",
    _SNAPSHOT_FLAG,
}
_REPLAY_REASONING_KEYS = _NATIVE_REASONING_KEYS - {"index", _SNAPSHOT_FLAG}


def _copy_reasoning_item(block: dict) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, value in block.items():
        if value is None or key not in _NATIVE_REASONING_KEYS:
            continue
        if key in {"summary", "content"} and isinstance(value, list):
            item[key] = [dict(part) if isinstance(part, dict) else part for part in value]
        else:
            item[key] = value
    return item


def _maybe_native_reasoning_item(block: dict) -> dict[str, Any] | None:
    if str(block.get("type") or "") != "reasoning":
        return None
    item = _copy_reasoning_item(block)
    return item or None


def _merge_indexed_parts(existing: object, incoming: object) -> list:
    merged: list = []
    if isinstance(existing, list):
        merged = [dict(part) if isinstance(part, dict) else part for part in existing]
    if not isinstance(incoming, list):
        return merged
    for part in incoming:
        if not isinstance(part, dict):
            merged.append(part)
            continue
        part_index = part.get("index")
        matched = None
        if part_index is not None:
            for prev in merged:
                if isinstance(prev, dict) and prev.get("index") == part_index:
                    matched = prev
                    break
        elif (
            merged
            and isinstance(merged[-1], dict)
            and merged[-1].get("index") is None
            and merged[-1].get("type") == part.get("type")
        ):
            matched = merged[-1]
        if matched is None:
            merged.append(dict(part))
            continue
        extra = str(part.get("text") or "")
        if extra:
            matched["text"] = str(matched.get("text") or "") + extra
        for key, value in part.items():
            if key in {"text", "index"} or value is None:
                continue
            matched.setdefault(key, value)
    return merged


def _existing_reasoning_item(
    store: list[dict[str, Any]], item: dict[str, Any]
) -> dict[str, Any] | None:
    item_id = item.get("id")
    if item_id:
        for existing in store:
            if existing.get("id") == item_id:
                return existing
    item_index = item.get("index")
    if item_index is not None:
        for existing in store:
            if existing.get("index") == item_index:
                return existing
    return None


def accumulate_reasoning_items(
    store: list[dict[str, Any]], incoming: list[object]
) -> None:
    """Merge streamed reasoning fragments by id, then by LangChain index."""
    for raw in incoming:
        if not isinstance(raw, dict) or str(raw.get("type") or "") != "reasoning":
            continue
        item = _copy_reasoning_item(raw)
        existing = _existing_reasoning_item(store, item)
        if existing is None:
            store.append(item)
            continue
        if item.get("id") and not existing.get("id"):
            existing["id"] = item["id"]
        if item.get("index") is not None and existing.get("index") is None:
            existing["index"] = item["index"]
        if item.get("status"):
            existing["status"] = item["status"]
        if item.get("encrypted_content"):
            existing["encrypted_content"] = item["encrypted_content"]
        if item.get(_SNAPSHOT_FLAG):
            incoming_text = _reasoning_from_block(item)
            existing_text = _reasoning_from_block(existing)
            if incoming_text or not existing_text:
                if "content" in item:
                    existing["content"] = [
                        dict(part) if isinstance(part, dict) else part
                        for part in (item.get("content") or [])
                    ]
                if "summary" in item:
                    existing["summary"] = [
                        dict(part) if isinstance(part, dict) else part
                        for part in (item.get("summary") or [])
                    ]
            continue
        if "summary" in item:
            existing["summary"] = _merge_indexed_parts(
                existing.get("summary"), item.get("summary")
            )
        if "content" in item:
            existing["content"] = _merge_indexed_parts(
                existing.get("content"), item.get("content")
            )


def _join_part_texts(parts: list) -> str:
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = str(part.get("text") or "")
            if text:
                texts.append(text)
        elif isinstance(part, str) and part:
            texts.append(part)
    return "".join(texts)


def _strip_part_index(part: object) -> object:
    if not isinstance(part, dict):
        return part
    return {key: value for key, value in part.items() if key != "index"}


def _select_reasoning_parts(parts: object, *, prefer_snapshot: bool) -> list:
    """Prefer a complete done snapshot; otherwise merge deltas by index."""
    if not isinstance(parts, list):
        return []
    indexed: list = []
    unindexed: list = []
    for part in parts:
        if isinstance(part, dict) and part.get("index") is not None:
            indexed.append(part)
        else:
            unindexed.append(part)
    snapshot_text = _join_part_texts(unindexed)
    if snapshot_text and (prefer_snapshot or not indexed):
        return [_strip_part_index(part) for part in unindexed]
    if snapshot_text and indexed:
        indexed_text = _join_part_texts(_merge_indexed_parts([], indexed))
        if (
            not indexed_text
            or snapshot_text == indexed_text
            or snapshot_text.startswith(indexed_text)
            or indexed_text in snapshot_text
        ):
            return [_strip_part_index(part) for part in unindexed]
    merged = _merge_indexed_parts([], indexed or parts)
    return [_strip_part_index(part) for part in merged]


def finalize_responses_reasoning_item(block: dict[str, Any]) -> dict[str, Any]:
    """Collapse LangChain-merged reasoning into one replay-safe item."""
    item = _copy_reasoning_item(block)
    status = str(item.get("status") or "")
    if "completed" in status.casefold():
        item["status"] = "completed"
    else:
        item.pop("status", None)
    prefer_snapshot = bool(item.get(_SNAPSHOT_FLAG))
    if "content" in item:
        collapsed = _select_reasoning_parts(
            item.get("content"), prefer_snapshot=prefer_snapshot
        )
        if collapsed:
            item["content"] = collapsed
        else:
            item.pop("content", None)
    if "summary" in item:
        collapsed = _select_reasoning_parts(
            item.get("summary"), prefer_snapshot=prefer_snapshot
        )
        if collapsed:
            item["summary"] = collapsed
        else:
            item.pop("summary", None)
    return reasoning_item_for_replay(item)


def finalize_responses_reasoning_message(message):
    """Fix concatenated snapshot/delta reasoning on a complete AIMessage."""
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return message
    if not any(
        isinstance(block, dict) and str(block.get("type") or "") == "reasoning"
        for block in content
    ):
        return message
    new_content = [
        finalize_responses_reasoning_item(block)
        if isinstance(block, dict) and str(block.get("type") or "") == "reasoning"
        else block
        for block in content
    ]
    copier = getattr(message, "model_copy", None)
    if callable(copier):
        return copier(update={"content": new_content})
    return message


def reasoning_item_for_replay(item: dict[str, Any]) -> dict[str, Any]:
    """Drop LangChain aggregation indexes before the next Responses request."""
    out: dict[str, Any] = {}
    for key, value in item.items():
        if value is None or key not in _REPLAY_REASONING_KEYS:
            continue
        if key in {"summary", "content"} and isinstance(value, list):
            parts = []
            for part in value:
                if not isinstance(part, dict):
                    parts.append(part)
                    continue
                cleaned = {
                    part_key: part_value
                    for part_key, part_value in part.items()
                    if part_key != "index" and part_value is not None
                }
                if cleaned:
                    parts.append(cleaned)
            if parts:
                out[key] = parts
            continue
        out[key] = value
    return out


def assistant_content_for_responses_replay(
    reasoning_items: list[dict[str, Any]],
    text: str,
) -> list[dict[str, Any]]:
    """Content list LangChain will serialize as reasoning items then text."""
    blocks = [
        reasoning_item_for_replay(item)
        for item in reasoning_items
        if isinstance(item, dict)
    ]
    if text:
        blocks.append({"type": "output_text", "text": text, "annotations": []})
    return blocks


def _tool_call_as_function_call(tool_call: object) -> dict[str, Any] | None:
    if isinstance(tool_call, dict):
        name = str(tool_call.get("name") or "")
        call_id = str(tool_call.get("id") or "")
        args = tool_call.get("args", tool_call.get("arguments", {}))
    else:
        name = str(getattr(tool_call, "name", "") or "")
        call_id = str(getattr(tool_call, "id", "") or "")
        args = getattr(tool_call, "args", {})
    if not name or not call_id:
        return None
    if isinstance(args, str):
        arguments = args
    else:
        arguments = json.dumps(args or {}, ensure_ascii=False)
    return {
        "type": "function_call",
        "name": name,
        "arguments": arguments,
        "call_id": call_id,
    }


def build_responses_replay_input(messages) -> list[dict[str, Any]]:
    """Rebuild DeepSeek/OpenAI Responses input: reasoning → function_call → output."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role = getattr(message, "type", None)
        ak = getattr(message, "additional_kwargs", None) or {}
        content = getattr(message, "content", "")
        if role in {"system", "human"}:
            text = content if isinstance(content, str) else str(content or "")
            items.append(
                {
                    "type": "message",
                    "role": "system" if role == "system" else "user",
                    "content": text,
                }
            )
            continue
        if role == "ai":
            stored = ak.get("responses_reasoning_items")
            emitted_reasoning = False
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "")
                    if block_type == "reasoning":
                        items.append(reasoning_item_for_replay(block))
                        emitted_reasoning = True
                    elif block_type in {"text", "output_text"} and block.get("text"):
                        items.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": str(block.get("text") or ""),
                                    }
                                ],
                            }
                        )
            if not emitted_reasoning and isinstance(stored, list):
                for block in stored:
                    if isinstance(block, dict) and block.get("type") == "reasoning":
                        items.append(reasoning_item_for_replay(block))
            elif (
                not emitted_reasoning
                and isinstance(ak.get("reasoning_content"), str)
                and ak["reasoning_content"]
            ):
                items.append(
                    {
                        "type": "reasoning",
                        "content": [
                            {
                                "type": "reasoning_text",
                                "text": ak["reasoning_content"],
                            }
                        ],
                    }
                )
            for tool_call in getattr(message, "tool_calls", None) or []:
                function_call = _tool_call_as_function_call(tool_call)
                if function_call is not None:
                    items.append(function_call)
            continue
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(getattr(message, "tool_call_id", "") or ""),
                    "output": str(content or ""),
                }
            )
    return items


def _reasoning_track_keys(block: dict) -> list[tuple[str, object]]:
    keys: list[tuple[str, object]] = []
    item_id = block.get("id")
    if item_id:
        keys.append(("id", str(item_id)))
    index = block.get("index")
    if index is not None:
        keys.append(("index", index))
    return keys


def _seen_reasoning_text(emitted: dict[tuple[str, object], str], block: dict) -> str:
    seen = ""
    for key in _reasoning_track_keys(block):
        value = emitted.get(key) or ""
        if len(value) > len(seen):
            seen = value
    return seen


def _record_reasoning_text(
    emitted: dict[tuple[str, object], str], block: dict, text: str
) -> None:
    if not text:
        return
    for key in _reasoning_track_keys(block):
        emitted[key] = text


def _visible_reasoning_text(
    emitted: dict[tuple[str, object], str], block: dict
) -> str:
    """Deltas append; complete snapshots only emit text not already streamed."""
    text = _reasoning_from_block(block)
    if not text:
        return ""
    seen = _seen_reasoning_text(emitted, block)
    if block.get(_SNAPSHOT_FLAG):
        if text.startswith(seen):
            extra = text[len(seen) :]
            recorded = text
        elif not seen:
            extra = text
            recorded = text
        else:
            extra = ""
            recorded = seen
        _record_reasoning_text(emitted, block, recorded)
        return extra
    _record_reasoning_text(emitted, block, seen + text)
    return text


async def responses_stream_as_chat_chunks(stream) -> AsyncIterator[SimpleNamespace]:
    """Translate LangChain Responses chunks to the legacy raw-chat shape.

    Also accepts DeepSeek ``reasoning`` items whose content parts are
    ``reasoning_text`` rather than OpenAI ``summary`` blocks. Native reasoning
    items (id/content/summary) are attached on the chunk for later replay.
    """
    saw_legal_terminal = False
    saw_refusal = False
    emitted_reasoning: dict[tuple[str, object], str] = {}
    async for item in stream:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        refusal_parts: list[str] = []
        native_reasoning_items: list[dict[str, Any]] = []
        content = getattr(item, "content", "")
        if isinstance(content, str):
            if content:
                text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    if isinstance(block, str):
                        text_parts.append(block)
                    continue
                block_type = str(block.get("type") or "")
                if block_type in {"text", "output_text"}:
                    text_parts.append(str(block.get("text") or ""))
                elif block_type == "reasoning":
                    visible = _visible_reasoning_text(emitted_reasoning, block)
                    if visible:
                        reasoning_parts.append(visible)
                    native = _maybe_native_reasoning_item(block)
                    if native is not None:
                        native_reasoning_items.append(native)
                elif block_type == "reasoning_text":
                    reasoning_parts.append(_text_from_part(block))
                elif block_type == "refusal":
                    refusal = str(block.get("refusal") or "")
                    if refusal:
                        refusal_parts.append(refusal)
                        saw_refusal = True

        extra = getattr(item, "additional_kwargs", None) or {}
        if isinstance(extra, dict):
            extra_reason = extra.get("reasoning_content") or extra.get("reasoning")
            if isinstance(extra_reason, str) and extra_reason:
                reasoning_parts.append(extra_reason)

        tool_deltas = []
        for call in getattr(item, "tool_call_chunks", None) or []:
            if not isinstance(call, dict):
                continue
            tool_deltas.append(
                SimpleNamespace(
                    index=call.get("index", 0),
                    id=call.get("id"),
                    function=SimpleNamespace(
                        name=call.get("name"),
                        arguments=call.get("args") or "",
                    ),
                )
            )

        usage = None
        usage_metadata = getattr(item, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            input_details = usage_metadata.get("input_token_details") or {}
            output_details = usage_metadata.get("output_token_details") or {}
            cached_tokens = int(input_details.get("cache_read", 0) or 0)
            reasoning_tokens = int(output_details.get("reasoning", 0) or 0)
            usage = SimpleNamespace(
                prompt_tokens=int(usage_metadata.get("input_tokens", 0) or 0),
                completion_tokens=int(
                    usage_metadata.get("output_tokens", 0) or 0
                ),
                input_tokens_details=SimpleNamespace(
                    cached_tokens=cached_tokens
                ),
                prompt_tokens_details=SimpleNamespace(
                    cached_tokens=cached_tokens
                ),
                completion_tokens_details=SimpleNamespace(
                    reasoning_tokens=reasoning_tokens
                ),
                output_tokens_details=SimpleNamespace(
                    reasoning_tokens=reasoning_tokens
                ),
            )

        terminal = getattr(item, "chunk_position", None) == "last"
        finish_reason = None
        if terminal:
            metadata = getattr(item, "response_metadata", None)
            metadata = metadata if isinstance(metadata, dict) else {}
            status = str(metadata.get("status") or "").strip().casefold()
            if status == "completed":
                saw_legal_terminal = True
                finish_reason = (
                    "content_filter"
                    if saw_refusal
                    else ("tool_calls" if tool_deltas else "stop")
                )
            elif status == "incomplete":
                details = metadata.get("incomplete_details") or {}
                reason = (
                    str(details.get("reason") or "").strip().casefold()
                    if isinstance(details, dict)
                    else ""
                )
                if reason == "max_output_tokens":
                    saw_legal_terminal = True
                    finish_reason = "length"
                elif reason == "content_filter":
                    saw_legal_terminal = True
                    finish_reason = "content_filter"
                else:
                    raise RuntimeError(
                        "Responses stream ended with incomplete status but no "
                        "supported incomplete reason"
                    )
            elif status == "failed":
                raise RuntimeError("Responses stream ended with failed status")
            else:
                raise RuntimeError(
                    "Responses stream ended without a valid terminal response status"
                )
        delta = SimpleNamespace(
            content="".join(text_parts) + "".join(refusal_parts),
            reasoning_content="".join(reasoning_parts),
            tool_calls=tool_deltas,
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=delta,
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
            _rxy_responses_terminal=terminal,
            _rxy_reasoning_items=native_reasoning_items,
        )
    if not saw_legal_terminal:
        raise RuntimeError(
            "Responses stream ended without a valid terminal response status"
        )


_LC_CONVERT_ORIGINAL = None


def _event_type(event: object) -> str:
    if isinstance(event, dict):
        return str(event.get("type") or "")
    return str(getattr(event, "type", "") or "")


def _event_field(event: object, name: str, default=None):
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _dump_sdk_item(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True, mode="json")
    return {}


def _advance_responses_indexes(
    current_index: int,
    current_output_index: int,
    current_sub_index: int,
    output_idx: int,
    sub_idx: int | None = None,
) -> tuple[int, int, int]:
    if sub_idx is None:
        if current_output_index != output_idx:
            current_index += 1
    else:
        if (current_output_index != output_idx) or (current_sub_index != sub_idx):
            current_index += 1
        current_sub_index = sub_idx
    return current_index, output_idx, current_sub_index


def _load_langchain_runtime():
    from . import _langchain_runtime as runtime

    return runtime


def _generation_from_dropped_reasoning_event(
    chunk: object,
    current_index: int,
    current_output_index: int,
    current_sub_index: int,
):
    """Map DeepSeek native reasoning events langchain-openai 1.3.3 drops."""
    runtime = _load_langchain_runtime()
    AIMessageChunk = runtime.AIMessageChunk
    ChatGenerationChunk = runtime.ChatGenerationChunk

    chunk_type = _event_type(chunk)
    content: list[dict[str, Any]] | None = None
    if chunk_type == "response.reasoning_text.delta":
        current_index, current_output_index, current_sub_index = (
            _advance_responses_indexes(
                current_index,
                current_output_index,
                current_sub_index,
                int(_event_field(chunk, "output_index", 0) or 0),
            )
        )
        content = [
            {
                "type": "reasoning",
                "id": _event_field(chunk, "item_id"),
                "index": current_index,
                "content": [
                    {
                        "index": _event_field(chunk, "content_index", 0),
                        "type": "reasoning_text",
                        "text": str(_event_field(chunk, "delta") or ""),
                    }
                ],
            }
        ]
    elif chunk_type == "response.output_item.done":
        item = _event_field(chunk, "item")
        dumped = _dump_sdk_item(item) if item is not None else {}
        if str(dumped.get("type") or "") != "reasoning":
            return (
                current_index,
                current_output_index,
                current_sub_index,
                None,
            )
        current_index, current_output_index, current_sub_index = (
            _advance_responses_indexes(
                current_index,
                current_output_index,
                current_sub_index,
                int(_event_field(chunk, "output_index", 0) or 0),
            )
        )
        dumped["index"] = current_index
        dumped[_SNAPSHOT_FLAG] = True
        content = [dumped]
    else:
        return current_index, current_output_index, current_sub_index, None

    message = AIMessageChunk(content=content, tool_call_chunks=[])
    return (
        current_index,
        current_output_index,
        current_sub_index,
        ChatGenerationChunk(message=message),
    )


@contextmanager
def native_reasoning_scope():
    """Enable dropped-event conversion for the current Responses call."""
    token = _NATIVE_REASONING_EVENTS.set(True)
    try:
        yield
    finally:
        try:
            _NATIVE_REASONING_EVENTS.reset(token)
        except ValueError:
            # AgentV2 pulls this generator with wait_for(anext), so __exit__
            # can run in a different Task/Context than __enter__.
            _NATIVE_REASONING_EVENTS.set(False)


async def astream_with_native_reasoning_events(stream):
    """Enable dropped-event conversion only while pulling the next item.

    AgentV2 drives streams with ``asyncio.wait_for(ait.__anext__())``. Each
    wait_for call is a new Task with its own Context, so a ``with`` around
    ``yield`` would reset a ContextVar token created in a different Context.
    """
    aiter = stream.__aiter__() if hasattr(stream, "__aiter__") else stream
    while True:
        with native_reasoning_scope():
            try:
                item = await aiter.__anext__()
            except StopAsyncIteration:
                break
        yield item


def convert_responses_sdk_event(
    chunk: object,
    current_index: int,
    current_output_index: int,
    current_sub_index: int,
    **kwargs,
):
    """LangChain Responses converter plus native reasoning events it drops."""
    lc_base = _load_langchain_runtime().lc_base

    converter = (
        _LC_CONVERT_ORIGINAL
        or lc_base._convert_responses_chunk_to_generation_chunk
    )
    idx, out_idx, sub_idx, generation = converter(
        chunk,
        current_index,
        current_output_index,
        current_sub_index,
        **kwargs,
    )
    if generation is not None:
        return idx, out_idx, sub_idx, generation
    return _generation_from_dropped_reasoning_event(
        chunk, idx, out_idx, sub_idx
    )


def _install_responses_payload_sanitizer() -> None:
    runtime = _load_langchain_runtime()
    AIMessage = runtime.AIMessage
    lc_base = runtime.lc_base

    original = lc_base._construct_responses_api_input
    if getattr(original, "_rxy_sanitize_reasoning", False):
        return

    def sanitized(messages, *args, **kwargs):
        cleaned = [
            finalize_responses_reasoning_message(message)
            if isinstance(message, AIMessage)
            else message
            for message in messages
        ]
        return original(cleaned, *args, **kwargs)

    sanitized._rxy_sanitize_reasoning = True
    lc_base._construct_responses_api_input = sanitized


def install_langchain_responses_reasoning_patch() -> None:
    """Install gated stream conversion and replay sanitization.

    Dropped native reasoning events are converted only while
    ``astream_with_native_reasoning_events`` is active. Complete AIMessages
    are collapsed before ``_construct_responses_api_input`` so create_agent
    follow-up requests do not keep snapshot flags or duplicated text.
    """
    global _LC_CONVERT_ORIGINAL
    lc_base = _load_langchain_runtime().lc_base

    _install_responses_payload_sanitizer()
    current = lc_base._convert_responses_chunk_to_generation_chunk
    if getattr(current, "_rxy_native_reasoning", False):
        return
    _LC_CONVERT_ORIGINAL = current

    def patched(
        chunk,
        current_index,
        current_output_index,
        current_sub_index,
        **kwargs,
    ):
        idx, out_idx, sub_idx, generation = _LC_CONVERT_ORIGINAL(
            chunk,
            current_index,
            current_output_index,
            current_sub_index,
            **kwargs,
        )
        if not _NATIVE_REASONING_EVENTS.get():
            return idx, out_idx, sub_idx, generation
        if generation is not None:
            return idx, out_idx, sub_idx, generation
        return _generation_from_dropped_reasoning_event(
            chunk, idx, out_idx, sub_idx
        )

    patched._rxy_native_reasoning = True
    lc_base._convert_responses_chunk_to_generation_chunk = patched
