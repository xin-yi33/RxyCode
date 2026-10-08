"""layer=unit P7"""
from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.timeout_decision import timeout_decision_config


def test_u_p7_02_config_section_defaults_and_merge():
    """layer=unit U-P7-02 config 节读取与默认值：键、值、cap 全集钉死"""
    d = timeout_decision_config({})
    assert d["enabled"] is False
    assert d["max_extensions_per_point"] == 2
    assert d["extension_growth"] == 2
    assert d["decision_timeout_seconds"] == 15.0
    assert d["decision_model"] is None
    assert d["fail_closed"] is True
    assert d["max_restarts"] == 2                               # 裁定 C 持久闸
    assert d["restart_total_wall_seconds"] == 7200.0            # 持久闸默认 2h（三轮统一直觉：dev/tests 同源）
    assert d["restart_grant_base_seconds"] == 900.0             # Policy 单次重启预算基数（cap 1800，不混 total_wall）
    assert d["absolute_cap_seconds"] == {
        "graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
        "watchdog_stall": 1800.0, "tool_timeout": 7200.0,
    }
    m = timeout_decision_config({"timeout_decision": {"enabled": True, "extension_growth": 3, "bogus": 1}})
    assert m["enabled"] is True and m["extension_growth"] == 3
    assert "bogus" not in m                                     # 未知键不渗透
    assert m["decision_timeout_seconds"] == 15.0                # 未覆盖保默认
    with pytest.raises(ValueError, match="absolute_cap"):
        timeout_decision_config({"timeout_decision": {"absolute_cap_seconds": {"tool_timeout": 1.0}}})
