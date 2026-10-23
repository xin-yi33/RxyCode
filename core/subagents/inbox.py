"""Parent-session inbox for child reports. The running agent drains this list."""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_INBOXES: dict[str, list[str]] = {}


def inbox_for(session_id: str) -> list[str]:
    """Return the stable list for one session. Callers share this object."""
    key = str(session_id or "").strip()
    if not key:
        key = ""
    with _LOCK:
        box = _INBOXES.get(key)
        if box is None:
            box = []
            _INBOXES[key] = box
        return box


def push_inbox(session_id: str, text: str) -> bool:
    body = str(text or "").strip()
    key = str(session_id or "").strip()
    if not body or not key:
        return False
    inbox_for(key).append(body)
    return True
