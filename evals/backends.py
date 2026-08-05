"""Eval execution backends: raw LLM vs full AgentV2 pipeline."""

from __future__ import annotations

import importlib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Protocol, runtime_checkable


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


def _extract_agent_token_usage(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, int]:
    """Return per-run token usage from a global token_stats delta."""
    usage = {
        "input": max(0, int(input_tokens or 0)),
        "output": max(0, int(output_tokens or 0)),
    }
    usage["total"] = usage["input"] + usage["output"]
    return usage


@contextmanager
def _headless_eval_runtime(
    *,
    workspace_root: Optional[Path] = None,
    extra_write_paths: Optional[list[str]] = None,
) -> Iterator[None]:
    """Headless eval: inject full_auto safety and an auto-approval broker.

    Agent graph nodes call ``load_config()`` directly (not ``agent._cfg``), so
    eval runs must patch config loading and register a broker for any tools
    that still require explicit approval.
    """
    from RxyCode.RxyCode1_1_0.config import settings as settings_module
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalDecision,
        ApprovalRequest,
        get_approval_broker,
        set_approval_broker,
    )
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

    class _EvalAutoApprovalBroker:
        async def request_approval(
            self, request: ApprovalRequest
        ) -> ApprovalDecision:
            return ApprovalDecision.APPROVED

        def is_level_always_allowed(self, level: RiskLevel) -> bool:
            return False

    real_load_config = settings_module.load_config

    def _eval_load_config():
        cfg = dict(real_load_config() or {})
        safety = dict(cfg.get("safety") or {})
        safety["enabled"] = True
        safety["permission_mode"] = "full_auto"
        safety["auto_approve"] = sorted(
            {
                *(str(x).lower() for x in (safety.get("auto_approve") or [])),
                "read",
                "write",
                "danger",
            }
        )
        safety["allowed_write_paths"] = sorted(
            {
                *(str(x) for x in (safety.get("allowed_write_paths") or [])),
                *(str(p) for p in (extra_write_paths or [])),
            }
        )
        cfg["safety"] = safety
        if workspace_root is not None:
            execution = dict(cfg.get("execution") or {})
            execution["sandbox_mode"] = "workspace"
            execution["workspace_root"] = str(Path(workspace_root).resolve())
            cfg["execution"] = execution
        return cfg

    # Modules that bound ``load_config`` at import time must be patched on
    # their own module-global name; patching only settings_module leaves the
    # bash sandbox (utils.shell) reading the original config.
    _import_bound_modules = ("utils.shell", "tools.workflow_tool")
    real_bindings: dict = {}
    for _rel in _import_bound_modules:
        try:
            _mod = importlib.import_module(f"RxyCode.RxyCode1_1_0.{_rel}")
        except Exception:
            continue
        _orig = getattr(_mod, "load_config", None)
        if _orig is not None:
            real_bindings[_mod] = _orig
            _mod.load_config = _eval_load_config

    prev_broker = get_approval_broker()
    settings_module.load_config = _eval_load_config  # type: ignore[method-assign]
    set_approval_broker(_EvalAutoApprovalBroker())
    try:
        yield
    finally:
        settings_module.load_config = real_load_config  # type: ignore[method-assign]
        for _mod, _orig in real_bindings.items():
            _mod.load_config = _orig
        set_approval_broker(prev_broker)


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

        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        session_id = f"eval-{uuid.uuid4().hex[:12]}"
        agent = self._make_agent(session_id=session_id)
        session_token = bind_session(session_id)
        token_start = (token_stats.input_tokens, token_stats.output_tokens)
        try:
            with _headless_eval_runtime(
                workspace_root=workdir,
                extra_write_paths=[str(workdir)] if workdir is not None else None,
            ):
                if workdir is not None:
                    set_working_directory(workdir)
                    # Tool threads inside the LangGraph pipeline can lose the
                    # ContextVar session binding and resolve to the default
                    # "latest" session id; seed that id's cwd so tools observe
                    # the eval workdir either way.
                    latest_token = bind_session("latest")
                    try:
                        set_working_directory(workdir)
                    finally:
                        reset_session_binding(latest_token)
                result = await agent.run(prompt, mode="build")
            answer = result if isinstance(result, str) else str(result or "")
            input_tokens = token_stats.input_tokens - token_start[0]
            output_tokens = token_stats.output_tokens - token_start[1]
            return BackendResult(
                answer=answer,
                token_usage=_extract_agent_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
                tools_used=_extract_agent_tools(agent),
            )
        except Exception as exc:
            input_tokens = token_stats.input_tokens - token_start[0]
            output_tokens = token_stats.output_tokens - token_start[1]
            return BackendResult(
                answer="",
                token_usage=_extract_agent_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
                tools_used=_extract_agent_tools(agent),
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            reset_session_binding(session_token)
            clear_session_runtime(session_id)
            clear_session_runtime("latest")


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
