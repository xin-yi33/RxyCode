"""PP40: model-visible Computer Use / browser tools when enabled."""

from __future__ import annotations

from types import SimpleNamespace

from RxyCode.RxyCode1_1_0.core.cu.bind import bind_computer_use, unbind_computer_use
from RxyCode.RxyCode1_1_0.core.cu.spec import BROWSER_TOOLS, CU_TOOL_ORDER, OCU_TOOLS
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator


def _agent(enabled: bool = True, approved: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={
            "computer_use": {
                "enabled": enabled,
                "approved": approved,
                "browser": True,
            }
        },
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )


def test_cu_desktop_lock_is_released_when_the_call_ends(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    from RxyCode.RxyCode1_1_0.core.cu.bind import _cu_call_lock

    with _cu_call_lock() as first:
        assert first is True
    with _cu_call_lock() as second:
        assert second is True
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    monkeypatch.delenv("RXYCODE_COMPUTER_USE_APPROVED", raising=False)
    agent = _agent(enabled=False)
    names = bind_computer_use(agent)
    assert "list_apps" in names
    assert "click" in names
    tool = agent._tool_orchestrator.get("list_apps")
    assert (tool.metadata or {}).get("cu_kind") == "disabled"
    kept = agent._tool_orchestrator.get("browser_snapshot")
    assert (kept.metadata or {}).get("cu_kind") == "disabled"


def test_enabled_stub_exposes_ocu_and_browser_names_in_stable_order(monkeypatch):
    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    agent = _agent(enabled=True, approved=True)
    names = bind_computer_use(agent, stub=True)
    assert names == CU_TOOL_ORDER
    assert list(agent._tool_orchestrator.list_names())[-len(CU_TOOL_ORDER) :] == list(
        CU_TOOL_ORDER
    )
    for name in OCU_TOOLS + BROWSER_TOOLS:
        tool = agent._tool_orchestrator.get(name)
        assert tool is not None, name
        assert "Computer Use" in (tool.description or "") or "Browser use" in (
            tool.description or ""
        )


def test_agent_get_core_tools_includes_cu_when_enabled(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    monkeypatch.delenv("RXYCODE_COMPUTER_USE", raising=False)
    agent = AgentV2.__new__(AgentV2)
    agent._tool_orchestrator = ToolOrchestrator()
    agent._cfg = {
        "computer_use": {"enabled": True, "approved": True, "browser": True}
    }
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = None
    bind_computer_use(agent, stub=True)
    visible = {getattr(tool, "name", "") for tool in AgentV2._get_core_tools(agent)}
    assert "list_apps" in visible
    assert "get_app_state" in visible
    assert "browser_open" in visible
    assert "browser_snapshot" in visible
    assert "browser_act" in visible
    unbind_computer_use(agent)


def test_env_try_path_enables_without_config(monkeypatch):
    monkeypatch.setenv("RXYCODE_COMPUTER_USE", "1")
    agent = SimpleNamespace(
        _tool_orchestrator=ToolOrchestrator(),
        _cfg={},
        _cu_client=None,
        _cu_tool_names=(),
        _cu_fingerprint=None,
    )
    names = bind_computer_use(agent, stub=True)
    assert "list_apps" in names
    assert "browser_act" in names
    unbind_computer_use(agent)


def test_register_builtin_tools_does_not_include_cu():
    from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import register_builtin_tools
    from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

    registry = ToolRegistry()
    orch = ToolOrchestrator(tool_registry=registry)
    register_builtin_tools(registry, orch, rag_enabled=False)
    names = set(orch.list_names())
    assert "list_apps" not in names
    assert "get_app_state" not in names
    assert "browser_navigate" in names
    snap = orch.get("browser_snapshot")
    assert snap is not None
    assert (getattr(snap, "metadata", None) or {}).get("source") != "computer_use"
    assert "cli_run" not in names

