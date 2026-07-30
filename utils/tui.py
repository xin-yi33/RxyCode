"""Backend output adapter shared by agents, tools, and API transports."""

from __future__ import annotations

import sys
import threading
import uuid
from typing import Any


class BackendOutputAdapter:
    """Minimal non-interactive event sink used outside an API stream."""

    def __init__(self) -> None:
        self._expand_thinking = False
        self._mode = "build"
        self._model_name = ""

    @staticmethod
    def _safe_print(text: Any) -> None:
        try:
            print(str(text))
        except Exception:
            pass

    def set_thinking_expanded(self, expanded: bool) -> None:
        self._expand_thinking = bool(expanded)

    def get_thinking_expanded(self) -> bool:
        return self._expand_thinking

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_model(self, name: str) -> None:
        self._model_name = name

    def set_busy(self, busy: bool) -> None:
        del busy

    def update_stats(self, **kwargs: Any) -> None:
        del kwargs

    def write(self, text: str, color: str = "") -> None:
        del color
        self._safe_print(text)

    def write_user_input(self, text: str) -> None:
        self._safe_print(text)

    def write_thought(self, elapsed: float) -> None:
        self._safe_print(f"Thought: {elapsed:.1f}s")

    def write_step(self, num: int, total: int, desc: str) -> None:
        self._safe_print(f"{num}/{total} {desc}")

    def write_step_done(self, num: int, total: int, desc: str) -> None:
        self._safe_print(f"Done {num}/{total} {desc}")

    def write_tool_call(self, name: str, args: Any, call_id: str | None = None) -> str:
        self._safe_print(f"{name}({args})")
        return str(call_id or uuid.uuid4().hex)

    def write_tool_result(
        self,
        result: Any,
        status: str = "success",
        call_id: str | None = None,
    ) -> None:
        del call_id
        self._safe_print(f"[{status}] {result}")

    def write_error(self, msg: str) -> None:
        self._safe_print(f"[ERR] {msg}")

    def write_success(self, msg: str) -> None:
        self._safe_print(f"[OK] {msg}")

    def write_info(self, msg: str) -> None:
        self._safe_print(msg)

    def write_progress(self, msg: str) -> None:
        self._safe_print(msg)

    def write_thinking(self, msg: str) -> None:
        if self._expand_thinking:
            self._safe_print(msg)

    def write_reasoning(self, text: str) -> None:
        if self._expand_thinking:
            self._safe_print(text)

    def write_warning(self, msg: str) -> None:
        self._safe_print(f"[WARN] {msg}")

    @staticmethod
    def stream_token(token: str) -> None:
        try:
            sys.stdout.write(token)
            sys.stdout.flush()
        except Exception:
            pass

    def write_model_indicator(self, mode: str, model: str) -> None:
        self._safe_print(f"{mode} | {model}")


_tui_instance: Any = None
_tui_lock = threading.Lock()


def get_tui() -> Any:
    global _tui_instance
    with _tui_lock:
        if _tui_instance is None:
            _tui_instance = BackendOutputAdapter()
        return _tui_instance


def set_tui(tui: Any) -> None:
    global _tui_instance
    with _tui_lock:
        _tui_instance = tui
