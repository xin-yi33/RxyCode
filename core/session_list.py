"""OpenTUI /session row DTO helpers (UPDATE-01 track H).

Pure functions. Not Session, not chat_storage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SESSION_DEFAULT_TITLE = "新任务"
SESSION_TITLE_MAX_CHARS = 40
DATE_GROUP_TODAY = "Today"
DATE_GROUP_YESTERDAY = "Yesterday"
DATE_GROUP_PINNED = "Pinned"
SESSION_AGE_NOW = "now"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # Monday=0
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_TITLE_SOURCES = frozenset({"manual", "llm", "fallback", "default"})


def _as_aware(ts: Any, now: datetime) -> datetime:
    tz = now.tzinfo or timezone.utc
    if ts is None or ts == "":
        return now
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    else:
        raw = str(ts).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def format_session_age(ts: Any, *, now: datetime) -> str:
    dt = _as_aware(ts, now)
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 60:
        return SESSION_AGE_NOW
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    months = max(1, days // 30)
    return f"{months}mo"


def session_date_group(ts: Any, *, now: datetime, pinned: bool = False) -> str:
    if pinned:
        return DATE_GROUP_PINNED
    dt = _as_aware(ts, now)
    d = dt.date()
    n = now.date()
    if d == n:
        return DATE_GROUP_TODAY
    if d == n - timedelta(days=1):
        return DATE_GROUP_YESTERDAY
    return f"{WEEKDAYS[d.weekday()]} {MONTHS[d.month - 1]} {d.day} {d.year}"


def _prompt_fallback_title(record: Any) -> str:
    blob = " ".join(str(getattr(record, "last_user_prompt", None) or "").split())
    return blob[:SESSION_TITLE_MAX_CHARS]


def display_title(record: Any) -> str:
    """manual title 赢；否则 generated_title；再否则 title / 首轮 prompt / SESSION_DEFAULT_TITLE。"""
    title = str(getattr(record, "title", None) or "").strip()
    generated = str(getattr(record, "generated_title", None) or "").strip()
    if bool(getattr(record, "title_is_manual", False)) and title:
        return title
    if generated:
        return generated
    if title and title not in {SESSION_DEFAULT_TITLE, "New task"}:
        return title
    prompt_title = _prompt_fallback_title(record)
    if prompt_title:
        return prompt_title
    return title or SESSION_DEFAULT_TITLE


def title_source_of(record: Any) -> str:
    stored = str(getattr(record, "title_source", "") or "").strip()
    if bool(getattr(record, "title_is_manual", False)):
        return "manual"
    if stored in _TITLE_SOURCES:
        return stored
    if str(getattr(record, "generated_title", None) or "").strip():
        return "llm"
    title = str(getattr(record, "title", None) or "").strip()
    if not title or title == SESSION_DEFAULT_TITLE:
        return "default"
    return "fallback"


def session_list_visible(record: Any, *, has_user_turn: bool | None = None) -> bool:
    """trashed / 子代理隐藏。无用户对话的空窗口不进 /session 列表。"""
    if getattr(record, "trashed_at", None):
        return False
    parent = getattr(record, "parent_session_id", None)
    if parent:
        return False
    if has_user_turn is None or has_user_turn:
        return True
    if bool(getattr(record, "pinned", False)) or bool(getattr(record, "title_is_manual", False)):
        return True
    return False


def session_list_row(record: Any, *, now: datetime) -> dict[str, Any]:
    """供 `_session_summary` 调用。含 display_title / age_label / date_group / title_source。"""
    generated = getattr(record, "generated_title", None)
    generated_s = str(generated).strip() if generated else ""
    pinned = bool(getattr(record, "pinned", False))
    ts = getattr(record, "updated_at", None) or getattr(record, "created_at", None) or now
    return {
        "display_title": display_title(record),
        "generated_title": generated_s or None,
        "title_is_manual": bool(getattr(record, "title_is_manual", False)),
        "title_source": title_source_of(record),
        "age_label": format_session_age(ts, now=now),
        "date_group": session_date_group(ts, now=now, pinned=pinned),
    }
