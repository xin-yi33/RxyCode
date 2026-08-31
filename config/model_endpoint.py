"""Validation and API-root normalization for LLM transport endpoints."""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit, urlunsplit

from .model_transport import (
    ANTHROPIC_MESSAGES_TRANSPORT,
    LLMTransport,
    OPENAI_CHAT_TRANSPORT,
    OPENAI_RESPONSES_TRANSPORT,
    normalize_api_transport,
)


_RESOURCE_SUFFIXES: dict[LLMTransport, tuple[str, ...]] = {
    # Longer suffix first.  ``/chat`` is the Chat Completions alias so probe and
    # the OpenAI SDK hit ``/chat/completions``.  Gateways whose real resource
    # is exactly ``/chat`` must set ``resource_path: /chat`` on the API root.
    OPENAI_CHAT_TRANSPORT: ("/chat/completions", "/chat"),
    OPENAI_RESPONSES_TRANSPORT: ("/responses",),
    ANTHROPIC_MESSAGES_TRANSPORT: ("/messages",),
}
_FINAL_RESOURCE: dict[LLMTransport, str] = {
    OPENAI_CHAT_TRANSPORT: "/chat/completions",
    OPENAI_RESPONSES_TRANSPORT: "/responses",
    ANTHROPIC_MESSAGES_TRANSPORT: "/messages",
}


def normalize_resource_path(value: object) -> str | None:
    """Return an exact terminal resource such as ``/chat``, or None.

    ``base_url`` remains the API root.  When this is set, probe and the SDK
    rewrite hit that path instead of the canonical ``/chat/completions``.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("resource_path must be a string")
    text = value.strip()
    if not text:
        return None
    if (
        not text.startswith("/")
        or text.startswith("//")
        or any(char.isspace() for char in text)
        or "?" in text
        or "#" in text
        or "://" in text
    ):
        raise ValueError(
            "resource_path must be an absolute path like /chat "
            "(no query, fragment, or URL scheme)"
        )
    return text.rstrip("/") or text


def infer_transport_from_resource_path(resource_path: str) -> LLMTransport:
    detected = _detect_path_transport(resource_path)
    if detected is not None:
        return detected[0]
    return OPENAI_CHAT_TRANSPORT


def rewrite_sdk_request_url(
    url: str,
    *,
    resource_path: str,
    transport: object,
) -> str:
    """Replace the SDK's canonical suffix with an exact resource_path."""
    canonical = normalize_api_transport(transport, allow_auto=False)
    suffix = _FINAL_RESOURCE[canonical]
    parsed = urlsplit(url)
    path = parsed.path
    if path.endswith(suffix):
        path = path[: -len(suffix)] + resource_path
        return urlunsplit(parsed._replace(path=path))
    return url


def ensure_resource_path_rewritable(
    resource_path: str,
    transport: object | None = None,
) -> None:
    """Reject transports whose runtime client does not honor resource_path."""
    inferred = infer_transport_from_resource_path(resource_path)
    canonical = inferred
    if transport is not None:
        requested = normalize_api_transport(transport, allow_auto=True)
        if requested != "auto":
            canonical = requested
    if canonical == ANTHROPIC_MESSAGES_TRANSPORT:
        raise ValueError(
            "resource_path is not supported for anthropic_messages; "
            "ChatAnthropic does not rewrite the SDK /v1/messages path. "
            "Omit resource_path for Anthropic, or use openai_chat / "
            "openai_responses"
        )


def resource_path_request_hook(resource_path: str, transport: object):
    """httpx.AsyncClient request hook so ChatOpenAI/AsyncOpenAI hit resource_path.

    The hook must be async: AsyncClient does ``await hook(request)``. A sync
    hook returns None and the request never reaches the network handler.
    """

    async def _hook(request) -> None:
        rewritten = rewrite_sdk_request_url(
            str(request.url),
            resource_path=resource_path,
            transport=transport,
        )
        if rewritten != str(request.url):
            request.url = type(request.url)(rewritten)

    return _hook


def _validated_split(base_url: str, *, require_https: bool) -> SplitResult:
    if not isinstance(base_url, str):
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    value = base_url.strip().rstrip("/")
    if not value or any(char.isspace() for char in value):
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "base_url must not contain credentials, query parameters, or fragments"
        )
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base_url contains an invalid port") from exc
    if require_https and parsed.scheme.casefold() != "https":
        raise ValueError("base_url must use https:// when an API credential is sent")
    return parsed._replace(path=parsed.path.rstrip("/"))


def validate_llm_base_url(base_url: str, *, require_https: bool = False) -> str:
    """Validate a URL without assuming or removing a protocol resource."""
    return urlunsplit(_validated_split(base_url, require_https=require_https))


def _detect_path_transport(path: str) -> tuple[LLMTransport, str] | None:
    folded = path.casefold()
    for transport, suffixes in _RESOURCE_SUFFIXES.items():
        for suffix in suffixes:
            if folded.endswith(suffix):
                return transport, suffix
    return None


def detect_explicit_transport(base_url: str) -> LLMTransport | None:
    """Return the protocol explicitly named by the terminal URL resource."""
    parsed = _validated_split(base_url, require_https=False)
    detected = _detect_path_transport(parsed.path)
    return detected[0] if detected is not None else None


def normalize_llm_endpoint(
    base_url: str,
    transport: object,
    *,
    require_https: bool = False,
) -> str:
    """Return an API root for one canonical transport.

    A matching terminal resource is removed exactly once. A terminal resource
    belonging to another protocol is rejected before network I/O.
    """
    canonical = normalize_api_transport(transport, allow_auto=False)
    parsed = _validated_split(base_url, require_https=require_https)
    detected = _detect_path_transport(parsed.path)
    path = parsed.path
    if detected is not None:
        explicit_transport, suffix = detected
        if explicit_transport != canonical:
            raise ValueError(
                "base_url explicit resource conflicts with api_transport: "
                f"{explicit_transport} != {canonical}"
            )
        path = path[: -len(suffix)]
    return urlunsplit(parsed._replace(path=path.rstrip("/")))


def llm_endpoint_url(
    base_url: str,
    transport: object,
    *,
    require_https: bool = False,
    resource_path: object = None,
) -> str:
    """Return the final resource URL, appending the protocol path once."""
    canonical = normalize_api_transport(transport, allow_auto=False)
    root = normalize_llm_endpoint(
        base_url,
        canonical,
        require_https=require_https,
    )
    extra = normalize_resource_path(resource_path)
    if extra:
        return root + extra
    return root + _FINAL_RESOURCE[canonical]


def llm_client_base_url(base_url: str, transport: object) -> str:
    """Return the base URL expected by the protocol's official SDK.

    OpenAI clients append resources below an API root such as ``/v1``.
    Anthropic's SDK resource is already the absolute ``/v1/messages`` path, so
    its client must receive the service root with a terminal ``/v1`` removed.
    The persisted/configured API root remains unchanged.
    """
    canonical = normalize_api_transport(transport, allow_auto=False)
    root = normalize_llm_endpoint(base_url, canonical)
    if canonical != ANTHROPIC_MESSAGES_TRANSPORT:
        return root
    parsed = urlsplit(root)
    path = parsed.path.rstrip("/")
    if path.casefold().endswith("/v1"):
        path = path[:-3]
    return urlunsplit(parsed._replace(path=path.rstrip("/")))
