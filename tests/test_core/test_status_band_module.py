"""layer=module F5-3 fast and graph share one status-band renderer."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.graph import _messages_with_guidance
from RxyCode.RxyCode1_1_0.core.status_band import HEADER, StatusBand, attach_status_band


def _band(**over) -> StatusBand:
    base = dict(
        list_id="default",
        revision=1,
        env={"cwd": "D:/repo", "worktree": "D:/repo", "platform": "win32", "shell": "pwsh", "date": "2026-10-08", "git_repo": True},
        todo_items=[{"id": "t1", "content": "搭骨架", "status": "in_progress"}],
        events=["timeout: continue"],
    )
    base.update(over)
    return StatusBand(**base)


def test_mo_f5_3_01_fast_and_graph_share_one_renderer(tmp_path, monkeypatch):
    """layer=module MO-F5-3-01 双路径同一渲染器。"""
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    band = _band(env=None)
    fast = attach_status_band([SystemMessage(content="S1")], band)
    tracker = SimpleNamespace(guidance_notes=[], _guidance_sent=0, _status_band=band)
    graph = _messages_with_guidance(tracker, [SystemMessage(content="S1")])
    assert band.render() in fast[-1].content
    assert band.render() in graph[-1].content
    assert fast[0].content == "S1"
    assert graph[0].content == "S1"
    assert ".render(" in inspect.getsource(attach_status_band)
    assert "attach_status_band" in inspect.getsource(_messages_with_guidance)
    assert "attach_status_band" in inspect.getsource(AgentV2._ensure_status_band)

    todo_write(
        [{"id": "t1", "content": "搭骨架", "status": "in_progress"}],
        merge=True,
        session_id="band-fast",
    )
    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "band-fast"
    agent._turns_since_todo_write = 1
    agent._turns_since_todo_reminder = 0
    produced = agent._ensure_status_band([SystemMessage(content="S1")])
    assert produced[0].content == "S1"
    assert isinstance(produced[-1], HumanMessage)
    assert produced[-1].content.startswith(HEADER)
    assert "搭骨架" in produced[-1].content
    assert band.render() not in produced[0].content
    again = agent._ensure_status_band(produced)
    assert len(again) == len(produced)


def test_mo_f5_3_02_one_trailing_user_with_band_before_steer():
    """layer=module MO-F5-3-02 band 与 steer 合成一条 trailing user。"""
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_summary_llm_calls

    band = _band(env=None)
    tracker = SimpleNamespace(
        guidance_notes=["往左走"],
        _guidance_sent=0,
        _status_band=band,
    )
    out = _messages_with_guidance(tracker, [HumanMessage(content="hi")])
    assert len(out) == 2
    text = out[-1].content
    assert text.index(band.render()) < text.index("往左走")
    assert tracker._guidance_sent == 1
    assert todo_summary_llm_calls == 0


def test_rollover_flag_and_timeout_event_outlive_the_ring(tmp_path, monkeypatch):
    """日期翻页记在环外；已落定的超时决策进入同一事件环。"""
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    todo_write(
        [{"id": "t1", "content": "搭骨架", "status": "in_progress"}],
        merge=True,
        session_id="band-fast",
    )
    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "band-fast"
    agent._turns_since_todo_write = 1
    agent._turns_since_todo_reminder = 0
    agent._status_frozen_date = "2000-01-01"
    agent._status_env = {
        "cwd": "D:/repo",
        "worktree": "D:/repo",
        "platform": "win32",
        "shell": "pwsh",
        "date": "2000-01-01",
        "git_repo": True,
    }
    agent._status_env_sent = True
    agent._status_rollover_noted = True
    agent._status_events = ["e1", "e2", "e3"]
    band = agent._load_status_band()
    assert band is not None
    assert not any(str(item).startswith("date rollover:") for item in band.events)
    agent.note_status_event("timeout: continue")
    noted = agent._load_status_band()
    assert "timeout: continue" in noted.render()
