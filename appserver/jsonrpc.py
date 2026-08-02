"""Newline-delimited JSON-RPC helpers for appserver stdio transport."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any

_stdout_lock = threading.Lock()


def write_message_sync(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout (sync; safe from worker threads)."""
    with _stdout_lock:
        sys.stdout.write(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        sys.stdout.flush()


async def write_message(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message without blocking the asyncio event loop."""
    await asyncio.to_thread(write_message_sync, message)


def parse_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("JSON-RPC payload must be an object")
    return payload


def is_client_request(message: dict[str, Any]) -> bool:
    return isinstance(message.get("method"), str) and "id" in message


def is_client_response(message: dict[str, Any]) -> bool:
    return "id" in message and ("result" in message or "error" in message)


def is_notification(message: dict[str, Any]) -> bool:
    return isinstance(message.get("method"), str) and "id" not in message
