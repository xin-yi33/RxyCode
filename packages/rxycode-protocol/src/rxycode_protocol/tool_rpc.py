"""Tool call frames. The schema models in protocol.requests are the only definition."""

from __future__ import annotations


def _models():
    try:
        from RxyCode.RxyCode1_1_0.protocol.requests import ToolCall, ToolChunk
    except ImportError:
        from protocol.requests import ToolCall, ToolChunk
    return ToolCall, ToolChunk


ToolCall, ToolChunk = _models()

__all__ = ["ToolCall", "ToolChunk"]
