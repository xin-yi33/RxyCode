"""Per-prompt asyncio context for appserver (concurrent session isolation)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_session_id: ContextVar[str] = ContextVar("appserver_session_id", default="latest")
_tui: ContextVar[Any | None] = ContextVar("appserver_tui", default=None)


def bind_prompt_context(session_id: str, tui: Any) -> tuple[Token[str], Token[Any | None]]:
    return _session_id.set(session_id), _tui.set(tui)


def reset_prompt_context(tokens: tuple[Token[str], Token[Any | None]]) -> None:
    _session_id.reset(tokens[0])
    _tui.reset(tokens[1])


def get_bound_session_id() -> str:
    return _session_id.get()


def get_bound_tui() -> Any | None:
    return _tui.get()


def install_tui_context_hook() -> None:
    """Route ``utils.tui.get_tui()`` through the bound ProtocolTui when set."""
    try:
        from ..utils import tui as tui_mod
    except ImportError:
        from utils import tui as tui_mod

    if getattr(tui_mod, "_appserver_context_hook_installed", False):
        return

    original_get = tui_mod.get_tui

    def context_aware_get_tui() -> Any:
        bound = get_bound_tui()
        if bound is not None:
            return bound
        return original_get()

    tui_mod.get_tui = context_aware_get_tui
    tui_mod._appserver_context_hook_installed = True