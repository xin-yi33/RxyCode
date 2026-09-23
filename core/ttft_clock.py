"""User TTFT clock: prompt submit → first thinking/reasoning token.

Routing ProgressUpdate / AgentEvent and liveness snapshots such as
「思考中...」do not count. The red line is the first model reasoning delta
on the wire or the matching protocol ``event/reasoning_snapshot``.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from typing import Any

SIMPLE_TTFT_S = 1.0
SIMPLE_TOL_S = 0.5
COMPLEX_TTFT_S = 3.0
COMPLEX_TOL_S = 0.2
SIMPLE_UPPER_S = SIMPLE_TTFT_S + SIMPLE_TOL_S  # 1.5
COMPLEX_UPPER_S = COMPLEX_TTFT_S + COMPLEX_TOL_S  # 3.2

# Status / liveness strings that are not a model thinking token.
_LIVENESS_MARKERS = (
    "思考中...",
    "思考中…",
    "思考中（",
    "等待模型返回",
    "模型输出中",
    "Analyzing your request",
    "正在用 explore",
    "正在组装",
    "等待终端返回",
    "等待工具",
    "等待视觉",
)


_clock: ContextVar["ThinkingTtftClock | None"] = ContextVar(
    "thinking_ttft_clock", default=None
)


def _is_real_thinking(text: object) -> bool:
    chunk = str(text or "").strip()
    if not chunk:
        return False
    for marker in _LIVENESS_MARKERS:
        if chunk.startswith(marker) or chunk == marker.rstrip("…."):
            return False
    return True


class ThinkingTtftClock:
    """One user-turn clock. Start at Session.prompt; mark first reasoning."""

    __slots__ = ("started_at", "first_reasoning_s", "first_reasoning_kind")

    def __init__(self) -> None:
        self.started_at: float | None = None
        self.first_reasoning_s: float | None = None
        self.first_reasoning_kind: str | None = None

    def start(self) -> None:
        self.started_at = time.perf_counter()
        self.first_reasoning_s = None
        self.first_reasoning_kind = None

    def mark_reasoning(self, text: object, *, kind: str = "delta") -> bool:
        """Record the first real thinking token. Returns True on first mark."""
        if self.first_reasoning_s is not None or self.started_at is None:
            return False
        if not _is_real_thinking(text):
            return False
        self.first_reasoning_s = time.perf_counter() - self.started_at
        self.first_reasoning_kind = kind
        _record_thinking_ttft_ms(self.first_reasoning_s * 1000.0)
        return True


def _record_thinking_ttft_ms(ttft_ms: float) -> None:
    """Best-effort: canonical package path or checkout-local utils."""
    try:
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats as ts

        ts.record_thinking_ttft(ttft_ms)
        return
    except Exception:
        pass
    try:
        from utils.streaming import token_stats as ts

        ts.record_thinking_ttft(ttft_ms)
    except Exception:
        pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "started": self.started_at is not None,
            "first_reasoning_s": self.first_reasoning_s,
            "kind": self.first_reasoning_kind,
        }


def current_clock() -> ThinkingTtftClock | None:
    return _clock.get()


def bind_prompt_clock() -> Token:
    clock = ThinkingTtftClock()
    clock.start()
    return _clock.set(clock)


def reset_prompt_clock(token: Token) -> None:
    _clock.reset(token)


def mark_reasoning(text: object, *, kind: str = "delta") -> bool:
    clock = _clock.get()
    if clock is None:
        return False
    return clock.mark_reasoning(text, kind=kind)


def first_reasoning_s() -> float | None:
    clock = _clock.get()
    if clock is None:
        return None
    return clock.first_reasoning_s


def is_real_thinking(text: object) -> bool:
    return _is_real_thinking(text)
