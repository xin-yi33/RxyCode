"""Phase H · 多模型协作：角色模型解析 + agents/settings RPC。"""

from __future__ import annotations

from copy import deepcopy

from RxyCode.RxyCode1_1_0.core.agents.coordinator import Coordinator
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec, SopStage, TeamSpec


def _session() -> Session:
    return Session(session_id="ses-mm", workspace_root=".", emit=lambda _n: None)


def _member(role: str, *, model: str | None = None, mechanical: bool = False) -> AgentSpec:
    return AgentSpec(
        role=role,
        display_name=role,
        goal=role,
        prompt_stage="default",
        model=model,
        mechanical=mechanical,
    )


def _team(*members: AgentSpec) -> TeamSpec:
    return TeamSpec(
        name="dev",
        display_name="Dev",
        members=list(members),
        stages=[
            SopStage(
                name="plan",
                role=members[0].role,
                expected_output="note",
                output_key="plan",
            )
        ],
        entry_stage="plan",
    )


def test_apply_multi_model_disabled_is_noop() -> None:
    coord = Coordinator(_session())
    team = _team(_member("architect", model="explicit-v1"), _member("coder"))
    same = coord._apply_multi_model(
        team,
        {
            "enabled": True,
            "multi_model": {"enabled": False, "master_model": "master-v1", "role_models": {}},
        },
    )
    assert same.members[0].model == "explicit-v1"
    assert same.members[1].model is None


def test_apply_multi_model_precedence_explicit_then_role_then_master() -> None:
    coord = Coordinator(_session())
    team = _team(
        _member("architect", model="explicit-v1"),
        _member("coder"),
        _member("auditor"),
    )
    resolved = coord._apply_multi_model(
        team,
        {
            "enabled": True,
            "multi_model": {
                "enabled": True,
                "master_model": "master-v1",
                "role_models": {"coder": "role-coder"},
            },
        },
    )
    by_role = {member.role: member.model for member in resolved.members}
    assert by_role["architect"] == "explicit-v1"
    assert by_role["coder"] == "role-coder"
    assert by_role["auditor"] == "master-v1"


def test_cache_namespace_keeps_agent_dimension() -> None:
    import inspect

    from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime

    source = inspect.getsource(AgentRuntime.spawn)
    assert 'agent:{self._spec.role}' in source or 'agent:' in source


def test_agents_settings_rpc_roundtrip(monkeypatch, tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.appserver import agents_routes

    store = {
        "agents": {
            "enabled": False,
            "team": "software_dev",
            "route_mode": "auto",
            "router_model": None,
            "total_token_budget": 500_000,
            "total_timeout_s": 1800.0,
            "multi_model": {"enabled": False, "master_model": None, "role_models": {}},
        }
    }

    monkeypatch.setattr(agents_routes, "load_config", lambda: deepcopy(store))

    def _save(cfg: dict) -> None:
        store.clear()
        store.update(deepcopy(cfg))

    monkeypatch.setattr(agents_routes, "save_config", _save)
    got = agents_routes.agents_settings_get()
    assert got["enabled"] is False
    assert got["multi_model"]["enabled"] is False
    agents_routes.agents_settings_set(
        {
            "enabled": True,
            "route_mode": "auto",
            "multi_model": {
                "enabled": True,
                "master_model": "gpt-5.6-luna",
                "role_models": {"architect": "deepseek-v4"},
            },
        }
    )
    again = agents_routes.agents_settings_get()
    assert again["enabled"] is True
    assert again["multi_model"]["master_model"] == "gpt-5.6-luna"
    assert again["multi_model"]["role_models"]["architect"] == "deepseek-v4"
