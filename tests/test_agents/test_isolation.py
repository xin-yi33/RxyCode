"""Agent 间状态隔离测试。

拆全局单例最典型的 bug 是"看起来能跑，但两个 Agent 悄悄共享了状态"——它
不会让别的测试变红，只会让行为变怪。这个文件专门抓它。
"""

from __future__ import annotations

import hashlib

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from RxyCode.RxyCode1_1_0.cache.precise_cache import default_precise_cache, precise_cache
from RxyCode.RxyCode1_1_0.cache.semantic_cache import default_semantic_cache, semantic_cache
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime
from RxyCode.RxyCode1_1_0.core.agents.spec import AgentSpecError
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec
from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import (
    get_breaker,
    get_default_breaker,
    reset_all_breakers,
)
from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry, default_registry, registry


class _IsoInput(BaseModel):
    value: str = Field(default="x")


def _iso_tool(name: str) -> StructuredTool:
    def _run(value: str = "x") -> str:
        return value

    return StructuredTool.from_function(
        func=_run,
        name=name,
        description="isolation probe",
        args_schema=_IsoInput,
    )


def test_two_registries_do_not_share_tools():
    left = ToolRegistry()
    right = ToolRegistry()
    left.register(_iso_tool("iso_left"))
    assert left.get("iso_left") is not None
    assert right.get("iso_left") is None


def test_default_registry_not_polluted_by_new_instances():
    before = set(default_registry.get_names())
    extra = ToolRegistry()
    extra.register(_iso_tool("iso_private"))
    assert "iso_private" not in default_registry.get_names()
    assert set(default_registry.get_names()) == before
    assert extra.get("iso_private") is not None


def test_registry_alias_is_the_default_instance():
    assert registry is default_registry


def test_orchestrator_none_uses_default_registry():
    orch = ToolOrchestrator(tool_registry=None)
    assert orch._registry is default_registry


def test_orchestrator_accepts_injected_registry():
    custom = ToolRegistry()
    orch = ToolOrchestrator(tool_registry=custom)
    assert orch._registry is custom
    assert orch._registry is not default_registry


def _ns_agent(namespace=None) -> AgentV2:
    agent = object.__new__(AgentV2)
    agent.model_config = {
        "base_url": "https://api.example.com/",
        "model_name": "deepseek-v4-flash",
        "api_key": "sk-test-123",
    }
    agent._agent_namespace = namespace
    return agent


def _expected_base() -> str:
    digest = hashlib.sha256(b"sk-test-123").hexdigest()
    return f"https://api.example.com|deepseek-v4-flash|{digest}"


def test_single_agent_cache_namespace_is_unchanged():
    agent = _ns_agent(None)
    assert agent._application_cache_namespace() == _expected_base()
    unset = object.__new__(AgentV2)
    unset.model_config = agent.model_config
    assert unset._application_cache_namespace() == _expected_base()


def test_cache_namespaces_isolate_agents():
    left = _ns_agent("architect")
    right = _ns_agent("coder")
    assert left._application_cache_namespace() == f"{_expected_base()}|architect"
    assert right._application_cache_namespace() == f"{_expected_base()}|coder"
    assert left._application_cache_namespace() != right._application_cache_namespace()


def test_cache_aliases_point_at_default_instances():
    assert precise_cache is default_precise_cache
    assert semantic_cache is default_semantic_cache


def test_breakers_are_isolated_by_key():
    reset_all_breakers()
    left = get_breaker("agent-a")
    right = get_breaker("agent-b")
    assert left is not right


def test_same_breaker_key_returns_same_instance():
    reset_all_breakers()
    first = get_breaker("shared")
    second = get_breaker("shared")
    assert first is second


def test_default_breaker_alias_matches_default_key():
    reset_all_breakers()
    assert get_default_breaker() is get_breaker("default")


# ---------------------------------------------------------------------------
# F4 · AgentRuntime role adapter (does not replace D5 isolation tests)
# ---------------------------------------------------------------------------

def _session(session_id: str = "ses-f4") -> Session:
    return Session(session_id=session_id, workspace_root=".", emit=lambda _n: None)


def _role(
    role: str,
    *,
    tools: list[str] | None = None,
    memory_scope: str = "private",
    mechanical: bool = False,
) -> AgentSpec:
    return AgentSpec(
        role=role,
        display_name=role,
        goal=f"act as {role}",
        prompt_stage="default",
        tools=tools,
        memory_scope=memory_scope,  # type: ignore[arg-type]
        mechanical=mechanical,
    )


def test_inherited_model_config_fills_empty_model_name() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.runtime import (
        _inherited_model_config,
        _primary_model_name,
    )

    class _LLM:
        model_name = "mimo-v2.5"

    class _Primary:
        model_config = {"base_url": "https://opencode.ai/zen/go/v1", "model_name": ""}
        _llm = _LLM()
        _cfg = {"active_model": "opencode-go/mimo-v2.5"}

    assert _primary_model_name(_Primary()) == "mimo-v2.5"
    inherited = _inherited_model_config(_Primary())
    assert inherited["model_name"] == "mimo-v2.5"


def test_runtimes_have_separate_tool_registries():
    session = _session()
    left = AgentRuntime(_role("architect"), session=session)
    right = AgentRuntime(_role("coder"), session=session)
    assert left.registry is not right.registry
    left.registry.register(_iso_tool("only_architect"))
    assert left.registry.get("only_architect") is not None
    assert right.registry.get("only_architect") is None
    assert default_registry.get("only_architect") is None


def test_runtimes_have_separate_cache_namespaces():
    session = _session()
    left = AgentRuntime(_role("architect"), session=session)
    right = AgentRuntime(_role("coder"), session=session)
    assert left.cache_namespace == "agent:architect"
    assert right.cache_namespace == "agent:coder"
    assert (
        _ns_agent(left.cache_namespace)._application_cache_namespace()
        != _ns_agent(right.cache_namespace)._application_cache_namespace()
    )


def test_runtimes_have_separate_breakers():
    reset_all_breakers()
    session = _session()
    left = AgentRuntime(_role("architect"), session=session)
    right = AgentRuntime(_role("coder"), session=session)
    assert left.breaker is not right.breaker


def test_private_memory_scope_does_not_leak():
    session = _session()
    left = AgentRuntime(_role("architect", memory_scope="private"), session=session)
    right = AgentRuntime(_role("coder", memory_scope="private"), session=session)
    left.memory_set("note", "from-architect")
    right.memory_set("note", "from-coder")
    assert left.memory_get("note") == "from-architect"
    assert right.memory_get("note") == "from-coder"


def test_shared_memory_scope_does_leak_intentionally():
    session = _session()
    left = AgentRuntime(_role("architect", memory_scope="shared"), session=session)
    right = AgentRuntime(_role("coder", memory_scope="shared"), session=session)
    left.memory_set("board", "visible")
    assert right.memory_get("board") == "visible"


def test_unknown_tool_name_in_spec_raises():
    session = _session()
    with pytest.raises(AgentSpecError, match="unknown tool"):
        AgentRuntime(_role("coder", tools=["definitely_not_a_real_tool"]), session=session)


def test_empty_tool_list_yields_empty_registry():
    session = _session()
    runtime = AgentRuntime(_role("thinker", tools=[]), session=session)
    assert runtime.registry.get_names() == []


def test_mechanical_role_has_no_llm():
    session = _session()
    runtime = AgentRuntime(_role("verifier", tools=[], mechanical=True), session=session)
    assert runtime.llm is None
    assert runtime.spec.mechanical is True


def test_single_agent_path_is_byte_identical():
    session = _session()
    default = AgentRuntime(_role("default"), session=session)
    AgentRuntime(_role("coder"), session=session)
    assert default.cache_namespace is None
    assert _ns_agent(None)._application_cache_namespace() == _expected_base()
    unset = object.__new__(AgentV2)
    unset.model_config = {
        "base_url": "https://api.example.com/",
        "model_name": "deepseek-v4-flash",
        "api_key": "sk-test-123",
    }
    assert unset._application_cache_namespace() == _expected_base()
    assert precise_cache is default_precise_cache
    assert session.agent_runtimes["default"] is default
    assert "coder" in session.agent_runtimes
