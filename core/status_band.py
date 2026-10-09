"""F5-3 状态带：env 首注 + todo 段 + 事件段，指纹 diff 注入（FT1）。

唯一渲染器；fast/graph 两注入点共用。env 基线不进指纹，恢复请求不能靠改日期另造一条状态带。
任何字段不进 prefix identity/cache key（FT4）。注入前必须与即将发送的请求上下文比对最新快照。
状态带是消费 TodoSnapshot 的 request-context 段，不是第二 store。
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage


HEADER = "State update (auto-attached by harness, not user input):"
_ACTIVE = frozenset({"pending", "in_progress", "blocked"})
_ENV_KEYS = ("cwd", "worktree", "platform", "shell", "date", "git_repo")
_INJECTED_CHARS = 0
_CURRENT_BAND: contextvars.ContextVar[StatusBand | None] = contextvars.ContextVar(
    "rxycode_status_band",
    default=None,
)


@dataclass
class StatusBand:
    list_id: str
    revision: int
    env: dict | None
    todo_items: list
    events: list
    after_compaction: bool = False

    def fingerprint(self) -> str:
        """Canonical sha256 of the diff key.

        env 被排除：冻结的启动环境不是台账变更。恢复请求若带上另一个日期，
        指纹仍与已发送的快照相同，因此不会重写首注。
        """
        payload = {
            "events": [str(item) for item in self.events],
            "list_id": self.list_id,
            "revision": int(self.revision),
            "todo_items": list(self.todo_items or []),
        }
        blob = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def render(self) -> str:
        lines = [
            "当前状态以本条为准",
            f"list_id={self.list_id} revision={self.revision} fp={self.fingerprint()}",
        ]
        if self.env:
            for key in _ENV_KEYS:
                if key in self.env:
                    lines.append(f"{key}: {self.env[key]}")
        items = [item for item in (self.todo_items or []) if isinstance(item, dict)]
        active = [item for item in items if str(item.get("status")) in _ACTIVE]
        done = sum(1 for item in items if item.get("status") == "completed")
        cancelled = sum(1 for item in items if item.get("status") == "cancelled")
        if items:
            if self.after_compaction and active:
                lines.append(
                    f"{len(active)} task(s) still active from before context compression "
                    "— keep working through them and update status as you progress."
                )
            for item in active:
                lines.append(
                    f"- [{item.get('status')}] {item.get('id')}: {item.get('content')}"
                )
            folded: list[str] = []
            # 压缩后的非空段固定带完成数，0 也要写出来。取消数仍是可选尾段。
            if self.after_compaction or done:
                folded.append(f"{done} completed")
            if cancelled:
                folded.append(f"{cancelled} cancelled")
            if folded:
                lines.append("(" + ", ".join(folded) + ")")
        if self.events:
            for event in list(self.events)[-3:]:
                lines.append(str(event))
        return "\n".join(lines)


def injected_chars() -> int:
    return _INJECTED_CHARS


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")


def _request_has_fingerprint(messages, fingerprint: str) -> bool:
    if not fingerprint:
        return False
    for message in messages:
        if fingerprint in _message_text(message):
            return True
    return False


def attach_status_band(messages, band, last_fp=None, force_full: bool = False):
    """Append one trailing user message when this request lacks the latest fingerprint.

    ``last_fp`` is only a caller-side cache. It must not suppress injection when
    the outgoing messages do not already contain the fingerprint.
    """
    del last_fp
    if not isinstance(messages, list) or not isinstance(band, StatusBand):
        return messages
    if not force_full and _request_has_fingerprint(messages, band.fingerprint()):
        return messages
    text = HEADER + "\n" + band.render()
    global _INJECTED_CHARS
    _INJECTED_CHARS += len(text)
    return [*messages, HumanMessage(content=text)]


def push_event(events, text: str) -> list:
    return [*list(events or []), str(text)][-3:]


def note_date_rollover(events, *, frozen: str, today: str):
    if str(today) == str(frozen):
        return events
    marker = "date rollover:"
    if any(str(item).startswith(marker) for item in events):
        return events
    return [*list(events or []), f"{marker} {frozen} -> {today}"]


def note_todo_stale(events, *, turns_since_write: int, has_open: bool, turns_since_reminder: int):
    if int(turns_since_write) >= 3 and bool(has_open) and int(turns_since_reminder) >= 5:
        return ([*list(events or []), "todo stale: update the open list"], 0)
    return (events, int(turns_since_reminder))


def capture_session_env(frozen_date: str | None = None) -> dict:
    cwd = os.getcwd()
    worktree = cwd
    git_repo = False
    start = Path(cwd)
    for parent in (start, *start.parents):
        if (parent / ".git").exists():
            worktree = str(parent)
            git_repo = True
            break
    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or ""
    return {
        "cwd": cwd,
        "worktree": worktree,
        "platform": sys.platform,
        "shell": shell,
        "date": frozen_date or date.today().isoformat(),
        "git_repo": git_repo,
    }


def apply_date_rollover(events, frozen: str):
    return note_date_rollover(events, frozen=frozen, today=date.today().isoformat())


def bind_status_band(source):
    """Bind the agent (or a static band) for this task. Graph reloads per call."""
    return _CURRENT_BAND.set(source)


def reset_status_band(token) -> None:
    _CURRENT_BAND.reset(token)


def current_band_source():
    return _CURRENT_BAND.get()


# 废弃代码（2026-10-09 死代码复核）：全仓零调用（含 tests）——活接口是
# 上方的 current_band_source()（core/graph.py:255/340 消费），本函数为平行
# 冗余 API，勿新调用。
def current_status_band() -> StatusBand | None:
    source = _CURRENT_BAND.get()
    if isinstance(source, StatusBand):
        return source
    loader = getattr(source, "_load_status_band", None)
    if callable(loader):
        loaded = loader()
        return loaded if isinstance(loaded, StatusBand) else None
    return None


def timeout_event_text(action: str, note: str = "") -> str:
    """One event-ring line for a settled timeout decision. No breaker counts."""
    label = str(action or "").strip()
    if not label:
        return ""
    detail = " ".join(str(note or "").split())
    if len(detail) > 120:
        detail = detail[:120]
    if detail:
        return f"timeout: {label} {detail}"
    return f"timeout: {label}"
