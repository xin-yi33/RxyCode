"""Fetch public HTTP(S) content with SSRF and cancellation safeguards."""

from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..utils.safe_http import (
    fetch_public_response,
    resolve_public_addresses,
    safe_url_label,
    validate_public_url,
)


_resolve_public_addresses = resolve_public_addresses
_validate_target_url = validate_public_url


_MAX_DOWNLOAD_BYTES = 1_000_000
_MAX_OUTPUT_CHARS = 50_000
_CHARSET_RE = re.compile(br"charset\s*=\s*['\"]?([a-zA-Z0-9_-]+)", re.I)
_AD_BLOCK_RE = re.compile(
    r"<(iframe|ins|aside)[^>]*>.*?</\1>",
    re.I | re.DOTALL,
)
_AD_ATTR_RE = re.compile(
    r"<[^>]+(?:id|class)=['\"][^'\"]*(?:ad[-_]?|ads|advert|sponsor|popup)[^'\"]*['\"][^>]*>.*?</[^>]+>",
    re.I | re.DOTALL,
)


def unwrap_click_url(url: str) -> str:
    """Resolve search-engine click wrappers (baidu /link, google /url) to the target."""
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    qs = parse_qs(parsed.query)
    target = ""
    if "baidu.com" in host and "url" in qs:
        target = unquote(qs["url"][0] or "")
    elif "google." in host and parsed.path.startswith("/url") and "q" in qs:
        target = unquote(qs["q"][0] or "")
    if target.startswith(("http://", "https://")):
        return target
    return raw


def _charset_from_bytes(raw: bytes, content_type: str) -> str | None:
    match = re.search(r"charset\s*=\s*['\"]?([a-zA-Z0-9_-]+)", content_type or "", re.I)
    if match:
        return match.group(1)
    meta = _CHARSET_RE.search(raw[:4096] if raw else b"")
    return meta.group(1).decode("ascii", errors="ignore") if meta else None


def decode_response_body(raw: bytes, content_type: str = "") -> str:
    """Prefer declared charset; fall back so GBK interstitial pages are not mojibake."""
    declared = _charset_from_bytes(raw, content_type)
    tried: set[str] = set()
    for enc in (declared, "utf-8", "gb18030", "gbk"):
        if not enc:
            continue
        name = enc.lower().replace("gb2312", "gb18030")
        if name in tried:
            continue
        tried.add(name)
        try:
            text = raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
        if name in {"utf-8", "utf8"} and text.count("\ufffd") > 8:
            continue
        return text
    return raw.decode("utf-8", errors="replace")


def strip_boilerplate_html(html: str) -> str:
    text = html or ""
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<noscript[^>]*>.*?</noscript>", "", text, flags=re.I | re.DOTALL)
    text = _AD_BLOCK_RE.sub("", text)
    text = _AD_ATTR_RE.sub("", text)
    return text


class FetchInput(BaseModel):
    url: str = Field(description="Public HTTP(S) URL to fetch")
    format: str = Field(default="text", description="Return format: text, markdown, or html")
    timeout: int = Field(default=30, ge=1, le=120, description="Timeout in seconds")


def _format_content(content: str, output_format: str) -> str:
    if output_format == "html":
        return content[:_MAX_OUTPUT_CHARS]
    if output_format == "markdown":
        return _html_to_markdown(content)[:_MAX_OUTPUT_CHARS]
    if output_format == "text":
        return _html_to_text(content)[:_MAX_OUTPUT_CHARS]
    raise ValueError("format must be one of: text, markdown, html")


async def fetch_url_async(url: str, format: str = "text", timeout: int = 30) -> str:
    """Fetch a public URL using cancellable I/O and per-hop validation."""
    try:
        target = unwrap_click_url(url)
        response = await fetch_public_response(
            target,
            timeout=timeout,
            max_bytes=_MAX_DOWNLOAD_BYTES,
        )
        response.raise_for_status()
        raw = response.content if isinstance(response.content, (bytes, bytearray)) else b""
        if not raw and getattr(response, "text", None):
            body = response.text
        else:
            ctype = str(response.headers.get("content-type") or "")
            body = decode_response_body(bytes(raw), ctype)
        body = strip_boilerplate_html(body)
        return _format_content(body, format.lower())
    except asyncio.TimeoutError:
        return f"[timeout fetching {safe_url_label(url)} after {timeout:g}s]"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return f"[error fetching {safe_url_label(url)}: {exc}]"


def fetch_url(url: str, format: str = "text", timeout: int = 30) -> str:
    """Synchronous compatibility wrapper for non-async callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_url_async(url, format=format, timeout=timeout))
    return "[error fetching URL: synchronous webfetch cannot run inside an event loop]"


def _html_to_text(html: str) -> str:
    text = unescape(html or "")
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _html_to_markdown(html: str) -> str:
    text = html
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1\n", text)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1\n", text)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"### \1\n", text)
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text)
    text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text)
    text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text)
    text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>", "\n\n", text)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


webfetch_tool = StructuredTool(
    name="webfetch",
    description=(
        "Fetch content from a public HTTP(S) URL. Private/local destinations "
        "and unsafe redirects are blocked."
    ),
    func=fetch_url,
    coroutine=fetch_url_async,
    args_schema=FetchInput,
)
