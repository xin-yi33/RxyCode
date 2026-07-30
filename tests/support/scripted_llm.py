"""Deterministic chat model backed by recorded response messages."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool


class ScriptedChatModel(BaseChatModel):
    """Deterministic chat model for testing.

    Returns pre-recorded AIMessage responses in order.  When the script is
    exhausted, returns a no-op AIMessage (empty content, no tool_calls)
    instead of raising StopIteration.

    Implements ``_agenerate`` directly (not via ``run_in_executor``) so
    that tool_calls are faithfully preserved in the async path and no
    empty RuntimeError is raised by the executor wrapper.
    """

    def __init__(self, messages: Any, **kwargs: Any) -> None:
        msg_list = list(messages)
        super().__init__(messages=msg_list, **kwargs)
        self._script: list[BaseMessage] = msg_list
        self._idx: int = 0

    # --- Core contract -------------------------------------------------------

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._next_result()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._next_result()

    def _next_result(self) -> ChatResult:
        if self._idx < len(self._script):
            msg = self._script[self._idx]
            self._idx += 1
        else:
            msg = AIMessage(content="")
        if isinstance(msg, str):
            msg = AIMessage(content=msg)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    # --- Tool binding --------------------------------------------------------

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "ScriptedChatModel":
        return self

    # --- LangChain boilerplate ----------------------------------------------

    @property
    def _llm_type(self) -> str:
        return "scripted"
