"""Fetch public HTTP(S) content with SSRF and cancellation safeguards."""

from __future__ import annotations

import asyncio
import re

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
        response = await fetch_public_response(
            url,
            timeout=timeout,
            max_bytes=_MAX_DOWNLOAD_BYTES,
        )
        response.raise_for_status()
        return _format_content(response.text, format.lower())
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
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
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
