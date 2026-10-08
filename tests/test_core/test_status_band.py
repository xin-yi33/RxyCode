"""layer=unit/module F5-3 status band on the trailing user slot."""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from RxyCode.RxyCode1_1_0.core.prefix_profile import PrefixProfile
from RxyCode.RxyCode1_1_0.core.status_band import (
    HEADER,
    StatusBand,
    attach_status_band,
    injected_chars,
    note_date_rollover,
    note_todo_stale,
    push_event,
)
from RxyCode.RxyCode1_1_0.core.graph import _messages_with_guidance


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


def test_u_f5_3_01_render_and_fingerprint_are_stable():
    """layer=unit U-F5-3-01 渲染器和指纹稳定。"""
    band = _band()
    assert band.render() == band.render()
    assert band.fingerprint() == band.fingerprint()
    changed = _band(events=["timeout: stop"])
    assert changed.fingerprint() != band.fingerprint()
    flipped = _band(todo_items=[{"id": "t1", "content": "搭骨架", "status": "completed"}])
    assert flipped.fingerprint() != band.fingerprint()


def test_u_f5_3_02_inject_only_when_the_request_lacks_the_snapshot():
    """layer=unit U-F5-3-02 变则注、不变零字节。"""
    band = _band(env=None)
    before = injected_chars()
    first = attach_status_band([HumanMessage(content="hi")], band, last_fp=band.fingerprint())
    assert len(first) == 2
    assert isinstance(first[-1], HumanMessage)
    assert first[-1].content.startswith(HEADER)
    assert injected_chars() > before
    second = attach_status_band(first, band, last_fp="preset-but-ignored")
    assert second is first or len(second) == len(first)
    newer = _band(env=None, revision=2, todo_items=[{"id": "t1", "content": "搭骨架", "status": "completed"}])
    third = attach_status_band(second, newer)
    assert len(third) == len(second) + 1


def test_u_f5_3_03_compaction_forces_one_full_render_without_a_second_env():
    """layer=unit U-F5-3-03 压缩后全量恢复，env 只首注一次。"""
    first = _band()
    sent = attach_status_band([], first)
    assert "cwd:" in sent[-1].content
    again = _band(env=None, events=["compacted", "timeout: continue"])
    forced = attach_status_band(sent, again, force_full=True)
    assert len(forced) == len(sent) + 1
    assert "搭骨架" in forced[-1].content
    assert "compacted" in forced[-1].content
    assert "cwd:" not in forced[-1].content


def test_u_f5_3_04_append_only_and_graph_history_stays():
    """layer=unit U-F5-3-04 只追加，不删历史。"""
    history = [HumanMessage(content="原话")]
    first = attach_status_band(history, _band(env=None, revision=1))
    second_band = _band(env=None, revision=2, events=["next"])
    second = attach_status_band(first, second_band)
    assert history == [HumanMessage(content="原话")]
    assert len(second) == 3
    assert "当前状态以本条为准" in second[-1].content
    tracker = SimpleNamespace(guidance_notes=[], _guidance_sent=0, _status_band=second_band)
    graph_once = _messages_with_guidance(tracker, history)
    assert history == [HumanMessage(content="原话")]
    assert len(graph_once) == 2
    graph_next = _messages_with_guidance(tracker, graph_once)
    assert len(graph_next) == len(graph_once)


def test_u_f5_3_05_env_keys_and_frozen_date():
    """layer=unit U-F5-3-05 环境段六键，日期冻结。"""
    band = _band()
    text = band.render()
    for key in ("cwd", "worktree", "platform", "shell", "date", "git_repo"):
        assert f"{key}:" in text
    assert "2026-10-08" in text
    events = note_date_rollover([], frozen="2026-10-08", today="2026-10-08")
    assert events == []
    rolled = note_date_rollover([], frozen="2026-10-08", today="2026-10-09")
    assert len(rolled) == 1
    assert note_date_rollover(rolled, frozen="2026-10-08", today="2026-10-09") == rolled
    restored = _band(env={"cwd": "D:/repo", "worktree": "D:/repo", "platform": "win32", "shell": "pwsh", "date": "2026-10-09", "git_repo": True})
    # 已有最新状态时不重复注入，首注日期不被恢复请求改写。
    sent = attach_status_band([], band)
    assert "2026-10-08" in sent[-1].content
    kept = attach_status_band(sent, band)
    assert len(kept) == 1
    replay = attach_status_band(sent, restored)
    assert len(replay) == 1
    assert "2026-10-08" in replay[-1].content
    assert "2026-10-09" not in replay[-1].content


def test_u_f5_3_06_event_ring_and_todo_reminder_budget():
    """layer=unit U-F5-3-06 事件环 last-3，todo 提醒限频。"""
    events: list[str] = []
    for index in range(5):
        events = push_event(events, f"e{index}")
    assert events == ["e2", "e3", "e4"]
    reminded, since = note_todo_stale([], turns_since_write=3, has_open=True, turns_since_reminder=5)
    assert reminded
    silent, later = note_todo_stale(reminded, turns_since_write=4, has_open=True, turns_since_reminder=since)
    assert silent == reminded
    assert later < 5


def test_u_f5_3_07_prefix_identity_ignores_the_band():
    """layer=unit U-F5-3-07 缓存面不含状态带。"""
    profile = PrefixProfile(
        kind="agent",
        session_id="sess",
        provider="glm",
        model="glm-5.3-flash",
        thinking_enabled=True,
        thinking_effort="high",
        tools_digest="abc",
        s1_digest="def",
        system_template_version="1",
        prompt_variant="default",
    )
    before = profile.identity()
    _band()
    after = profile.identity()
    assert before == after
    assert "搭骨架" not in before
    assert "status_band" not in before
