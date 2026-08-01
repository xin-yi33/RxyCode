"""Eval execution backends: raw LLM vs full AgentV2 pipeline."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable


@dataclass
class BackendResult:
    """Outcome of one backend execution."""

    answer: str
    token_usage: dict[str, int]
    tools_used: list[str] = field(default_factory=list)
    error: str = ""


@runtime_checkable
class EvalBackend(Protocol):
    """Execute one eval prompt through a specific runtime."""

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        ...


class RawLLMBackend:
    """直连 LLM。仅作为对照基线，不代表 RxyCode 的能力。"""

    def __init__(self, llm):
        self._llm = llm

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        from langchain_core.messages import HumanMessage

        from .runner import _extract_token_usage

        resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
        answer = getattr(resp, "content", "") or ""
        return BackendResult(
            answer=answer,
            token_usage=_extract_token_usage(self._llm, resp),
        )


def _extract_agent_tools(agent) -> list[str]:
    """Collect tool names from the agent's last evidence capture."""
    tools: list[str] = []
    for item in getattr(agent, "_last_evidence", []) or []:
        if isinstance(item, dict):
            name = item.get("tool")
        else:
            name = getattr(item, "tool", None)
        if name and name not in tools:
            tools.append(str(name))
    return tools


def _extract_agent_token_usage(agent) -> dict[str, int]:
    usage: dict[str, int] = {"input": 0, "output": 0, "total": 0}
    llm = getattr(agent, "_llm", None)
    ts = getattr(llm, "token_stats", None) if llm is not None else None
    if ts is not None:
        try:
            usage["input"] = int(getattr(ts, "input_tokens", 0) or 0)
            usage["output"] = int(getattr(ts, "output_tokens", 0) or 0)
            usage["total"] = usage["input"] + usage["output"]
        except (TypeError, ValueError):
            pass
    return usage


class AgentBackend:
    """走完整 AgentV2 管线，这是我们真正要评测的对象。"""

    def __init__(self, agent_factory):
        self._make_agent = agent_factory

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            clear_session_runtime,
            reset_session_binding,
            set_working_directory,
        )

        session_id = f"eval-{uuid.uuid4().hex[:12]}"
        agent = self._make_agent(session_id=session_id)
        session_token = bind_session(session_id)
        try:
            if workdir is not None:
                set_working_directory(workdir)
            result = await agent.run(prompt, mode="build")
            answer = result if isinstance(result, str) else str(result or "")
            return BackendResult(
                answer=answer,
                token_usage=_extract_agent_token_usage(agent),
                tools_used=_extract_agent_tools(agent),
            )
        except Exception as exc:
            return BackendResult(
                answer="",
                token_usage=_extract_agent_token_usage(agent),
                tools_used=_extract_agent_tools(agent),
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            reset_session_binding(session_token)
            clear_session_runtime(session_id)


def make_agent_factory(model_name: Optional[str] = None):
    """Return a factory that builds a fresh AgentV2 per eval task."""

    def _factory(*, session_id: str):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = AgentV2(model_name=model_name)
        agent._session_id = session_id
        return agent

    return _factory


def build_backend(
    name: str,
    *,
    llm=None,
    model_name: Optional[str] = None,
) -> EvalBackend:
    """Construct a backend by CLI name."""
    if name == "raw-llm":
        if llm is None:
            raise ValueError("raw-llm backend requires an LLM instance")
        return RawLLMBackend(llm)
    if name == "agent":
        return AgentBackend(make_agent_factory(model_name=model_name))
    raise ValueError(f"unknown backend: {name!r}")
