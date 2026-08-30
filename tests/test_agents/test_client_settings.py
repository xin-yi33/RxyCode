"""F13 · Settings 分层 + 协议 RoutingDecision。"""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.agents.client_settings import (
    apply_agents_args,
    hidden_when_disabled,
    settings_items,
)
from RxyCode.RxyCode1_1_0.core.agents.router import ExecutionMode, ModeRouter
from RxyCode.RxyCode1_1_0.protocol.agents import RoutingDecision
from RxyCode.RxyCode1_1_0.protocol.schema import export_schema


def test_settings_hide_nested_items_when_disabled() -> None:
    items = settings_items({"agents": {"enabled": False}})
    assert hidden_when_disabled(items)
    ids = [item["id"] for item in items]
    assert "agents_enabled" in ids
    assert "agents_team" not in ids
    assert "agents_budget" not in ids
    assert "agents_router_model" not in ids


def test_settings_show_nested_items_when_enabled() -> None:
    items = settings_items({"agents": {"enabled": True, "router_model": None}})
    assert not hidden_when_disabled(items)
    ids = [item["id"] for item in items]
    assert "agents_router_model" in ids
    assert "agents_multi_model" in ids
    multi = next(item for item in items if item["id"] == "agents_multi_model")
    assert multi.get("disabled") is not True
    assert "Phase H 才可用" not in str(multi.get("desc") or "")


def test_agents_command_sets_router_model() -> None:
    cfg: dict = {"agents": {"enabled": False}}
    agents, msg = apply_agents_args(cfg, "on")
    assert agents["enabled"] is True
    assert "enabled=True" in msg
    apply_agents_args(cfg, "router-model judge-v1")
    assert cfg["agents"]["router_model"] == "judge-v1"
    apply_agents_args(cfg, "router-model none")
    assert cfg["agents"]["router_model"] is None
    apply_agents_args(cfg, "route team")
    assert cfg["agents"]["route_mode"] == "team"
    apply_agents_args(cfg, "multi-model on")
    assert cfg["agents"]["multi_model"]["enabled"] is True
    apply_agents_args(cfg, "role-model architect deepseek-v4")
    assert cfg["agents"]["multi_model"]["role_models"]["architect"] == "deepseek-v4"


def test_route_mode_settings_force_team() -> None:
    router = ModeRouter(enabled=True)
    # settings.route_mode is read from load_config; inject via monkey-style override
    router._enabled_override = True
    from RxyCode.RxyCode1_1_0.core.agents import router as router_mod

    original = router_mod._settings_agents
    router_mod._settings_agents = lambda: {"enabled": True, "route_mode": "team"}
    try:
        decision = router.route("hello?")
        assert decision.mode is ExecutionMode.TEAM
        assert "route_mode=team" in decision.reason
    finally:
        router_mod._settings_agents = original


def test_routing_decision_is_in_protocol_schema() -> None:
    schema = export_schema()
    assert "RoutingDecision" in schema["$defs"]
    dumped = RoutingDecision(
        mode="solo",
        decided_by="user",
        reason="slash /solo",
    )
    assert dumped.mode == "solo"
