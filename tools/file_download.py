"""Download public HTTP(S) resources to the local filesystem."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_write_path
from ..utils.safe_http import (
    ResponseTooLargeError,
    fetch_public_response,
    safe_url_label,
)


_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36"
}


class FileDownloadInput(BaseModel):
    """Input for the file download tool."""

    url: str = Field(description="Public HTTP(S) URL of the file to download")
    save_path: Optional[str] = Field(
        default=None,
        description=(
            "Local directory or full path. Defaults to the RxyCode output directory."
        ),
    )
    filename: Optional[str] = Field(
        default=None,
        description="Custom filename. Defaults to the final URL path component.",
    )


def _resolve_download_path(
    url: str,
    save_path: Optional[str],
    filename: Optional[str],
) -> Path:
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = urlsplit("")
    inferred_name = filename or os.path.basename(parsed.path) or "downloaded_file"
    inferred_name = Path(inferred_name).name or "downloaded_file"

    if save_path:
        requested = Path(save_path).expanduser()
        if requested.suffix:
            target = resolve_write_path(requested)
        else:
            target = resolve_write_path(requested / inferred_name)
    else:
        from ..config.settings import get_output_dir

        target = get_output_dir() / inferred_name

    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _download_success(url: str, target: Path, started_at: float) -> str:
    file_size = target.stat().st_size
    if file_size < 1024:
        size_str = f"{file_size} bytes"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size / (1024 * 1024):.2f} MB"
    return (
        "Successfully downloaded file!\n"
        f"  URL: {safe_url_label(url)}\n"
        f"  Saved to: {target}\n"
        f"  Size: {size_str}\n"
        f"  Time: {time.time() - started_at:.1f}s"
    )


async def download_file_async(
    url: str,
    save_path: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """Fetch a public file with cancellable I/O and atomic publication."""
    temporary: Path | None = None
    started_at = time.time()
    try:
        response = await fetch_public_response(
            url,
            timeout=30,
            max_bytes=_MAX_DOWNLOAD_BYTES,
            headers=_DOWNLOAD_HEADERS,
        )
        response.raise_for_status()
        target = _resolve_download_path(url, save_path, filename)

        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(response.content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, target)
        temporary = None
        return _download_success(url, target, started_at)
    except asyncio.CancelledError:
        raise
    except ResponseTooLargeError:
        return "Error: File exceeded the maximum size of 100MB."
    except httpx.TimeoutException:
        return "Download failed: Connection timed out (30s)"
    except httpx.HTTPStatusError as exc:
        return f"Download failed: HTTP Error {exc.response.status_code}"
    except Exception as exc:
        return f"Download failed: {type(exc).__name__}: {exc}"
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def download_file(
    url: str,
    save_path: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """Synchronous compatibility wrapper for non-event-loop callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            download_file_async(url, save_path=save_path, filename=filename)
        )
    return "Download failed: synchronous download cannot run inside an event loop"


file_download_tool = StructuredTool(
    name="download_file",
    description=(
        "Download a file from a public HTTP(S) URL to the local filesystem. "
        "Private/local destinations and unsafe redirects are blocked. "
        "The default save location is the RxyCode output directory."
    ),
    func=download_file,
    coroutine=download_file_async,
    args_schema=FileDownloadInput,
)
