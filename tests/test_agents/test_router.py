"""F10 · ModeRouter 三级路由。"""

from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.agents.router import (
    ExecutionMode,
    ModeRouter,
    get_default_router,
)
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent


def test_slash_commands_force_mode() -> None:
    router = ModeRouter(enabled=False)
    assert router.handle_slash("/solo do it").startswith("forced solo")
    assert router.route("/team build both").mode is ExecutionMode.TEAM
    assert router.route("/team-multi x").mode is ExecutionMode.TEAM_MULTI_MODEL
    why = router.handle_slash("/why-mode")
    assert "decided_by=user" in why
    assert "team_multi" in why or "mode=" in why


def test_disabled_skips_llm_and_heuristic() -> None:
    calls: list[str] = []

    def ask(prompt: str) -> str:
        calls.append(prompt)
        return "team"

    router = ModeRouter(enabled=False, llm_ask=ask, router_model="x")
    decision = router.route("重构前后端并迁移多个模块")
    assert decision.mode is ExecutionMode.SOLO
    assert decision.decided_by == "default"
    assert calls == []
    assert router._llm_calls == 0


def test_structured_split_goes_team() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("把前后端拆成两个独立改造再多人审计")
    assert decision.mode is ExecutionMode.TEAM
    assert decision.decided_by == "heuristic"
    assert "split" in decision.reason


def test_serial_dependency_goes_solo() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("只改这一个单文件，必须同步改完全量上下文")
    assert decision.mode is ExecutionMode.SOLO
    assert "serial" in decision.reason


def test_llm_failure_falls_back_to_level_two() -> None:
    def boom(_prompt: str) -> str:
        raise RuntimeError("timeout")

    router = ModeRouter(enabled=True, llm_ask=boom, router_model="judge")
    decision = router.route("把前后端拆成两个独立改造")
    assert decision.mode is ExecutionMode.TEAM
    assert decision.decided_by == "heuristic"
    assert "llm failed" in decision.reason


def test_route_emits_agent_event_with_experiment_tag() -> None:
    seen: list[AgentEvent] = []
    router = ModeRouter(enabled=True, emit=seen.append, experiment_tag="E1")
    router.route("hello?")
    assert seen
    assert seen[0].method == "event/agent_routed"
    assert seen[0].experiment_tag == "E1"
    assert seen[0].routing_reason


def test_efficiency_gate_updates_l2_thresholds() -> None:
    router = ModeRouter(enabled=True)
    before = router.thresholds.min_files_for_team
    router.apply_efficiency_gate(team_beats_solo=False)
    assert router.thresholds.min_files_for_team == before + 1
    router.apply_efficiency_gate(team_beats_solo=True, min_files_for_team=5)
    assert router.thresholds.min_files_for_team == 5


def test_default_router_why_mode_without_history() -> None:
    router = ModeRouter()
    assert router.handle_slash("/why-mode") == "no routing decision yet"
    get_default_router().route("/solo x")
    assert "solo" in get_default_router().handle_slash("/why-mode")


def test_social_greeting_stays_solo_even_when_route_mode_team() -> None:
    from RxyCode.RxyCode1_1_0.core.agents import router as router_mod

    original = router_mod._settings_agents
    router_mod._settings_agents = lambda: {"enabled": True, "route_mode": "team"}
    try:
        router = ModeRouter(enabled=True)
        decision = router.route("hi")
        assert decision.mode is ExecutionMode.SOLO
        assert decision.reason == "social greeting"
    finally:
        router_mod._settings_agents = original


def test_legacy_parallel_method_is_gone() -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    assert not hasattr(AgentV2, "_should_request_parallel_execution")
