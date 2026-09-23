"""Per-prompt asyncio context for appserver (concurrent session isolation)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_session_id: ContextVar[str] = ContextVar("appserver_session_id", default="latest")
_tui: ContextVar[Any | None] = ContextVar("appserver_tui", default=None)
#: 2026-09-23（P0 answer-last）：子代理执行期间深度 +1。ProtocolTui 打标
#: 时读取：depth>=1 的流式文本/进度是中间输出，不得渲染成最终答复。
_delegate_depth: ContextVar[int] = ContextVar("appserver_delegate_depth", default=0)


def bind_prompt_context(session_id: str, tui: Any) -> tuple[Token[str], Token[Any | None]]:
    return _session_id.set(session_id), _tui.set(tui)


def reset_prompt_context(tokens: tuple[Token[str], Token[Any | None]]) -> None:
    _session_id.reset(tokens[0])
    _tui.reset(tokens[1])


def get_bound_session_id() -> str:
    return _session_id.get()


def get_bound_tui() -> Any | None:
    return _tui.get()


def bind_delegate_depth() -> Token[int]:
    """进入子代理执行：深度 +1。返回 token 供 reset_delegate_depth。"""
    return _delegate_depth.set(_delegate_depth.get() + 1)


def reset_delegate_depth(token: Token[int]) -> None:
    _delegate_depth.reset(token)


def current_delegate_depth() -> int:
    """0 = 主代理；>=1 = 子代理（专家团角色 / task 子代理）。"""
    return _delegate_depth.get()


def install_tui_context_hook() -> None:
    """Route every supported TUI import path through the bound ProtocolTui.

    The stdio appserver is launched as top-level ``appserver`` while AgentV2
    imports ``RxyCode.RxyCode1_1_0.utils.tui``.  Python loads those as distinct
    module objects, so patch both paths rather than assuming a single module
    namespace.
    """
    modules: list[Any] = []
    try:
        from ..utils import tui as tui_mod
        modules.append(tui_mod)
    except ImportError:
        pass
    try:
        from utils import tui as tui_mod
        modules.append(tui_mod)
    except ImportError:
        pass
    try:
        from RxyCode.RxyCode1_1_0.utils import tui as tui_mod
        modules.append(tui_mod)
    except ImportError:
        pass

    for tui_mod in modules:
        if getattr(tui_mod, "_appserver_context_hook_installed", False):
            continue
        original_get = tui_mod.get_tui

        def context_aware_get_tui(*, _original_get: Any = original_get) -> Any:
            bound = get_bound_tui()
            if bound is not None:
                return bound
            return _original_get()

        tui_mod.get_tui = context_aware_get_tui
        tui_mod._appserver_context_hook_installed = True
