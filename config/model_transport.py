"""Canonical LLM transport names and migration helpers.

Configuration accepts the legacy ``chat``/``responses`` spellings during the
migration window.  Provider and execution layers only consume the three
canonical values exported here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, cast


LLMTransport = Literal[
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
]
TransportSetting = Literal[
    "auto",
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
]

OPENAI_CHAT_TRANSPORT: LLMTransport = "openai_chat"
OPENAI_RESPONSES_TRANSPORT: LLMTransport = "openai_responses"
ANTHROPIC_MESSAGES_TRANSPORT: LLMTransport = "anthropic_messages"

_TRANSPORT_ALIASES: dict[str, LLMTransport] = {
    "chat": OPENAI_CHAT_TRANSPORT,
    OPENAI_CHAT_TRANSPORT: OPENAI_CHAT_TRANSPORT,
    "responses": OPENAI_RESPONSES_TRANSPORT,
    OPENAI_RESPONSES_TRANSPORT: OPENAI_RESPONSES_TRANSPORT,
    ANTHROPIC_MESSAGES_TRANSPORT: ANTHROPIC_MESSAGES_TRANSPORT,
}


def normalize_api_transport(
    value: object,
    *,
    allow_auto: bool = False,
) -> LLMTransport | Literal["auto"]:
    """Return a canonical transport, accepting legacy config spellings.

    ``None`` and an empty string mean ``auto`` only at a configuration
    boundary.  Invalid non-empty values fail closed instead of silently
    changing the request protocol.
    """
    if value is None:
        text = "auto"
    elif isinstance(value, str):
        text = value.strip().casefold()
        if not text:
            text = "auto"
    else:
        raise ValueError("api_transport must be a string")

    if text == "auto":
        if allow_auto:
            return "auto"
        raise ValueError("api_transport='auto' is not an executable transport")
    try:
        return _TRANSPORT_ALIASES[text]
    except KeyError as exc:
        raise ValueError(
            "api_transport must be one of auto, openai_chat, "
            "openai_responses, anthropic_messages (legacy chat/responses "
            "are also accepted)"
        ) from exc


def normalize_transport_candidates(
    candidates: Iterable[object],
) -> tuple[LLMTransport, ...]:
    """Canonicalize and stably de-duplicate a Provider candidate sequence."""
    if isinstance(candidates, (str, bytes)):
        raise ValueError("transport candidates must be a sequence, not a string")

    normalized: list[LLMTransport] = []
    seen: set[LLMTransport] = set()
    try:
        iterator = iter(candidates)
    except TypeError as exc:
        raise ValueError("transport candidates must be iterable") from exc
    for candidate in iterator:
        value = cast(
            LLMTransport,
            normalize_api_transport(candidate, allow_auto=False),
        )
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    if not normalized:
        raise ValueError("transport candidates must contain at least one value")
    return tuple(normalized)
