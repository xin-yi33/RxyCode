"""layer=unit/module F4-7 超时常量单一注册表。"""
from __future__ import annotations

import pytest

EXPECTED_DEFAULTS = {
    "stream.connect_seconds": 20.0,
    "stream.idle_seconds": 180.0,
    "stream.tool_argument_idle_seconds": 60.0,
    "pipeline.soft_budget_seconds": 3600.0,
    "graph.task_stall_timeout_seconds": 0.0,
    "graph.task_max_time_seconds": 7200.0,
    "graph.heartbeat_interval_seconds": 15.0,
    "tool.timeout_seconds": 1800.0,
    "tool.stall_timeout_seconds": 120.0,
    "appserver.heartbeat_seconds": 15.0,
    "appserver.stall_seconds": 120.0,
    "appserver.stall_grace_seconds": 20.0,
}


def test_u_f4_7_01_defaults_match_current_code_table():
    """layer=unit U-F4-7-01
    迁移的全部旋钮默认值与现状逐一对表（一个都不能少、一个都不能变）。
    """
    from RxyCode.RxyCode1_1_0.config.timeouts import TIMEOUT_REGISTRY, resolve_timeout

    assert set(TIMEOUT_REGISTRY) == set(EXPECTED_DEFAULTS)
    for name, expected in EXPECTED_DEFAULTS.items():
        assert resolve_timeout(name) == expected, name


def test_u_f4_7_02_idle_cap_semantics_preserved():
    """layer=unit U-F4-7-02
    cap 语义不变：stream.idle cfg 覆盖到 999 仍被 cap 到 300；无 cap 键不被钳。
    """
    from RxyCode.RxyCode1_1_0.config.timeouts import TIMEOUT_REGISTRY, resolve_timeout

    assert TIMEOUT_REGISTRY["stream.idle_seconds"].cap == 300.0
    assert resolve_timeout("stream.idle_seconds", cfg={"stream": {"idle_seconds": 999.0}}) == 300.0
    assert resolve_timeout("stream.connect_seconds") == 20.0
    assert TIMEOUT_REGISTRY["stream.connect_seconds"].cap is None


def test_u_f4_7_03_cfg_override_beats_env_beats_default(monkeypatch):
    """layer=unit U-F4-7-03
    覆盖优先级钉死：cfg > env > default。env 不可解析 → ValueError（现状 float() 行为）。
    """
    from RxyCode.RxyCode1_1_0.config.timeouts import resolve_timeout

    monkeypatch.setenv("RXYCODE_APPSERVER_STALL_GRACE_SECONDS", "33")
    assert resolve_timeout("appserver.stall_grace_seconds") == 33.0
    cfg = {"appserver": {"stall_grace_seconds": 7.0}}
    assert resolve_timeout("appserver.stall_grace_seconds", cfg=cfg) == 7.0
    monkeypatch.setenv("RXYCODE_APPSERVER_STALL_GRACE_SECONDS", "not-a-number")
    with pytest.raises(ValueError):
        resolve_timeout("appserver.stall_grace_seconds")


def test_u_f4_7_04_unknown_name_raises_keyerror():
    """layer=unit U-F4-7-04"""
    from RxyCode.RxyCode1_1_0.config.timeouts import resolve_timeout

    with pytest.raises(KeyError):
        resolve_timeout("stream.nonexistent_seconds")


def test_u_f4_7_05_settings_mirror_single_source(tmp_path):
    """layer=unit U-F4-7-05
    默认配置里的 appserver/schedule 新键与 §1.2 钉死值一致（防第二份字面量漂移）。
    """
    from RxyCode.RxyCode1_1_0.config.settings import get_settings

    settings = get_settings()
    raw = getattr(settings, "raw", None) or getattr(settings, "_raw", None) or getattr(settings, "config", None)
    if raw is None and isinstance(settings, dict):
        raw = settings
    assert raw is not None, "get_settings 的原始 dict 访问口缺失时先钉口再改此测试"
    assert raw["appserver"]["stall_grace_seconds"] == 20
    assert raw["schedule"]["revive_orphans_on_restore"] is False


def test_mo_f4_7_01_migrated_callsites_resolve_same_values(monkeypatch):
    """layer=module MO-F4-7-01
    迁移点现值与注册表一致（替换不漂移）：
    agent_v2 三层时钟、watchdog 两个 env 访问器、tool 默认 1800/120。
    """
    from RxyCode.RxyCode1_1_0.appserver import watchdog
    from RxyCode.RxyCode1_1_0.core import agent_v2
    from RxyCode.RxyCode1_1_0.config.timeouts import resolve_timeout

    assert agent_v2.STREAM_CONNECT_TIMEOUT_DEFAULT_SECONDS == resolve_timeout("stream.connect_seconds") == 20.0
    assert agent_v2.STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS == resolve_timeout("stream.idle_seconds") == 180.0
    assert agent_v2.STREAM_IDLE_TIMEOUT_CAP_SECONDS == 300.0
    assert agent_v2.TOOL_ARGUMENT_STREAM_IDLE_SECONDS == resolve_timeout("stream.tool_argument_idle_seconds") == 60.0
    assert agent_v2.FIRST_TOKEN_TIMEOUT_CAP_SECONDS == 180.0

    monkeypatch.delenv("RXYCODE_APPSERVER_STALL_SECONDS", raising=False)
    monkeypatch.delenv("RXYCODE_APPSERVER_HEARTBEAT_SECONDS", raising=False)
    assert watchdog.stall_timeout_seconds() == resolve_timeout("appserver.stall_seconds") == 120.0
    assert watchdog.heartbeat_interval_seconds() == resolve_timeout("appserver.heartbeat_seconds") == 15.0

    monkeypatch.setenv("RXYCODE_APPSERVER_STALL_SECONDS", "9")
    assert watchdog.stall_timeout_seconds() == resolve_timeout("appserver.stall_seconds") == 9.0


def test_mo_f4_7_02_tool_orchestrator_defaults_via_registry():
    """layer=module MO-F4-7-02
    工具超时：空 cfg 走注册表默认（1800 硬顶 / 120 stall）；cfg 覆盖语义不变。
    """
    from RxyCode.RxyCode1_1_0.config.timeouts import resolve_timeout
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    assert resolve_timeout("tool.timeout_seconds") == 1800.0
    assert resolve_timeout("tool.stall_timeout_seconds") == 120.0
    empty: dict = {"execution": {}}
    # shell 归一为 bash（TOOL_ALIASES）→ _LONG_RUNNING_TOOLS → 全局硬顶：
    assert ToolOrchestrator._tool_timeout_seconds(empty, "shell") == 1800.0
    # read 类工具：min(stall 120, _TOOL_STALL_SECONDS["read"]=60) = 60：
    assert ToolOrchestrator._tool_timeout_seconds(empty, "read_file") == 60.0
    overridden = {"execution": {"tool_timeout_seconds": 60, "tool_stall_timeout_seconds": 300}}
    # cfg 覆盖语义不变：global=60 成为硬顶，stall 300 被钳到 60。
    assert ToolOrchestrator._tool_timeout_seconds(overridden, "read_file") == 60.0
    assert ToolOrchestrator._tool_timeout_seconds(overridden, "shell") == 60.0


def test_mo_f4_7_03_present_falsy_keeps_old_or_normalization():
    """Present 0 / None keep the old `or` read. Missing keys stay on the registry."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import resolve_pipeline_clocks
    from RxyCode.RxyCode1_1_0.core.graph import resolve_graph_watch_clocks
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    stall, max_time, heartbeat = resolve_graph_watch_clocks(
        {"execution": {"heartbeat_interval_seconds": 0, "task_max_time_seconds": None}}
    )
    assert stall == 0.0
    assert max_time == 0.0
    assert heartbeat == 15.0
    for falsy in ("", [], {}):
        stalled, _, _ = resolve_graph_watch_clocks(
            {"execution": {"task_stall_timeout_seconds": falsy}}
        )
        assert stalled == 0.0, falsy

    soft, pipe_heartbeat = resolve_pipeline_clocks(
        {
            "execution": {
                "pipeline_soft_budget_seconds": None,
                "heartbeat_interval_seconds": 0,
            }
        }
    )
    assert soft == 0.0
    assert pipe_heartbeat == 15.0

    assert ToolOrchestrator._tool_timeout_seconds(
        {"execution": {"tool_timeout_seconds": None}}, "shell"
    ) == 0.0
    assert ToolOrchestrator._tool_timeout_seconds(
        {"execution": {"tool_timeout_seconds": ""}}, "shell"
    ) == 0.0
    assert ToolOrchestrator._tool_timeout_seconds(
        {"execution": {"tool_stall_timeout_seconds": ""}}, "read_file"
    ) == 60.0
    assert ToolOrchestrator._tool_timeout_seconds({"execution": {}}, "shell") == 1800.0
