from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    AgentV2,
    _is_approved_plan_implement,
    _session_plan_md_path,
)


def test_approved_plan_prefixes():
    assert _is_approved_plan_implement("按已批准的计划开始实施，不要重新规划。\n\n# 1024")
    assert _is_approved_plan_implement("已批准计划，开始实施")
    assert not _is_approved_plan_implement("随便做一个贪吃蛇")


def test_prepare_approved_implement_clears_prefix_and_pins_plan_md(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "sess-1024"
    agent._agent_prefix_messages = ["stale-snake-prefix"]
    path = _session_plan_md_path("sess-1024")
    path.parent.mkdir(parents=True)
    path.write_text("# 1024炸弹\n\n不要做贪吃蛇\n", encoding="utf-8")

    text, role, meta = agent._prepare_approved_implement("已批准计划，开始实施")
    assert agent._agent_prefix_messages is None
    assert "1024炸弹" in text
    assert "不要做贪吃蛇" in text
    assert "旧游戏" in role
    assert meta["title"] == "1024炸弹"
    assert meta["disk_chars"] > 0
