"""layer=unit/module F4-6 scheduler 真起 turn + orphan 复活。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.appserver.schedule_service import ScheduleError, ScheduleService


class _Permissions:
    def evaluate(self, **kwargs) -> str:
        return "allow"


class _FakeSessions:
    """同形 SessionStore：consumer 有无可控；enqueue 落 event 记录（真起 turn 与否的探针）。"""

    def __init__(self, *, consumer: bool):
        self.consumer = consumer
        self.enqueued: list[dict] = []
        from types import SimpleNamespace

        self._record = SimpleNamespace(
            session_id="sess_sch",
            trashed_at=None,
            workspace_root=".",
            usage={"budget_exhausted": 0, "input_tokens": 0, "output_tokens": 0},
            budget={"max_tokens": 0},
        )

    def get(self, session_id):
        return self._record if session_id == "sess_sch" else None

    def restore(self, session_id):
        return self._record

    def is_consumer_attached(self, session_id: str) -> bool:
        return self.consumer

    def enqueue_scheduled(self, session_id: str, *, kind: str, text: str, origin: str = "schedule"):
        self.enqueued.append({"session_id": session_id, "kind": kind, "text": text, "origin": origin})
        return {"seq": len(self.enqueued)}


def _service(tmp_path: Path, *, consumer: bool, runner=None, max_parallel: int = 2, budget_exhausted: int = 0) -> ScheduleService:
    sessions = _FakeSessions(consumer=consumer)
    sessions._record.usage["budget_exhausted"] = budget_exhausted
    return ScheduleService(
        tmp_path / "schedules.json",
        sessions=sessions,
        permissions=_Permissions(),
        runner=runner,
        max_parallel=max_parallel,
    )


def _interval_action() -> dict:
    return {"kind": "session", "session_id": "sess_sch", "message": "ping health"}


def test_u_f4_6_01_no_consumer_marks_scheduled_pending(tmp_path):
    """layer=unit U-F4-6-01
    dispatch 无消费窗口 → scheduled_pending；消息仍入队（delivered=True）；结果可发现。
    """
    svc = _service(tmp_path, consumer=False)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    result = svc.fire(job["id"])
    assert result["ok"] is True
    payload = result["result"]
    assert payload["delivered"] is True
    assert payload["execution"] == "scheduled_pending"
    jobs = svc.list_jobs()["jobs"]
    assert jobs[0]["last_result"]["execution"] == "scheduled_pending"
    assert svc.sessions.enqueued[0]["text"] == "ping health"


def test_u_f4_6_02_consumer_attached_runs_turn(tmp_path):
    """layer=unit U-F4-6-02
    有消费窗口 → execution == "turn"（真起 turn，不再只是入队）。
    """
    svc = _service(tmp_path, consumer=True)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    result = svc.fire(job["id"])
    assert result["ok"] is True
    assert result["result"]["execution"] == "turn"


def test_u_f4_6_03_revive_orphan_fires_once_interval_continues(tmp_path):
    """layer=unit U-F4-6-03（崩溃恢复可重放范围）
    orphan（interval 规则）复活：立即 fire-once、orphan 清除、next_fire 从 now 重算
    （**不补积压**：已错过多个 interval 也只补当前这一次）；再 revive 同 job 拒绝。
    """
    svc = _service(tmp_path, consumer=False)
    enqueued_before = len(svc.sessions.enqueued)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    job_id = job["id"]
    svc._jobs[job_id]["run_status"] = "running"
    orphans = svc.restore_after_restart(revive_orphans=False)
    assert [o["id"] for o in orphans] == [job_id]
    fires_before = [r for r in svc.audit() if r.get("action") == "fire"]
    revived = svc.revive_orphan(job_id)
    assert revived["orphan"] is False
    assert revived["ok"] is True
    fires_after = [r for r in svc.audit() if r.get("action") == "fire"]
    assert len(fires_after) == len(fires_before) + 1  # fire-once：不补积压
    assert len(svc.sessions.enqueued) == enqueued_before + 1
    job_after = svc._jobs[job_id]
    assert job_after["next_fire"] is not None        # interval 规则续期（重算，非回填过去时点）
    with pytest.raises(ScheduleError, match="orphan"):
        svc.revive_orphan(job_id)


def test_u_f4_6_04_revive_on_restore_config_off_default(tmp_path):
    """layer=unit U-F4-6-04
    revive_orphans_on_restore=false（默认）→ restore 后不自动复活：
    orphan 仍在、零 fire、零 revive 审计。
    """
    svc = _service(tmp_path, consumer=False)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    svc._jobs[job["id"]]["run_status"] = "running"
    orphans = svc.restore_after_restart()            # 不传参 = 走 config（默认 False）
    assert len(orphans) == 1
    job_after = svc._jobs[job["id"]]
    assert job_after["orphan"] is True
    assert job_after["run_status"] == "recovery_required"
    fires = [r for r in svc.audit() if r.get("action") == "fire"]
    assert fires == []


def test_u_f4_6_05_running_job_policy_is_skip(tmp_path):
    """layer=unit U-F4-6-05（生命周期①：上轮未结束策略 = 跳过）
    running 中的 job 再触发 → {"ok": False, "reason": "already-running"}；
    不并发第二实例（enqueued 不增、零新增 fire 审计）。
    """
    svc = _service(tmp_path, consumer=False)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    job_id = job["id"]
    svc._running.add(job_id)                             # 现状执行寄存器：上轮未结束
    fires_before = [r for r in svc.audit() if r.get("action") == "fire"]
    result = svc.fire(job_id)
    assert result["ok"] is False
    assert result["reason"] == "already-running"
    assert result["queued"] is False
    assert len(svc.sessions.enqueued) == 0
    fires_after = [r for r in svc.audit() if r.get("action") == "fire"]
    assert fires_after == fires_before


def test_u_f4_6_06_reconnect_does_not_redeliver(tmp_path, monkeypatch):
    """layer=unit U-F4-6-06（生命周期②：断线重连不重复投递，去重键 = 持久化 next_fire）
    interval fire 一次 → 模拟重启（新实例同 path）→ 未到 next_fire 的 tick 重复跑：
    零新增 enqueue、零新增 fire 审计（同一 interval 不重发）。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    svc = _service(tmp_path, consumer=False)
    start = datetime(2026, 10, 1, 9, 0, 0)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action(), now=start)
    fired = svc.tick(now=start + timedelta(seconds=90))
    assert fired[0]["ok"] is True
    assert len(svc.sessions.enqueued) == 1
    # 重启：新实例从同一持久文件读 next_fire（T+1min 之后）
    rebooted = _service(tmp_path, consumer=False)
    audit_len_before = len(rebooted.audit())          # 持久 audit 含首期 fire，取增量断言
    fired2 = rebooted.tick(now=start + timedelta(seconds=100))  # 未到 next_fire
    assert fired2 == []
    assert len(rebooted.sessions.enqueued) == 0
    new_rows = rebooted.audit()[audit_len_before:]
    assert [r for r in new_rows if r.get("action") == "fire"] == []


def test_u_f4_6_07_toggle_off_never_fires(tmp_path, monkeypatch):
    """layer=unit U-F4-6-07（生命周期④：停止/toggle 后不再触发）
    toggle(enabled=False) → 充分过期的 tick 也不 fire、不 enqueue；审计有 toggle 行。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    svc = _service(tmp_path, consumer=False)
    start = datetime(2026, 10, 1, 9, 0, 0)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action(), now=start)
    svc.toggle(job["id"], False)
    assert svc._jobs[job["id"]]["enabled"] is False
    fired = svc.tick(now=start + timedelta(hours=3))
    assert fired == []
    assert svc.sessions.enqueued == []
    toggles = [r for r in svc.audit() if r.get("action") == "toggle" and r.get("job_id") == job["id"]]
    assert len(toggles) == 1
    assert toggles[0]["enabled"] is False


def test_u_f4_6_08_parallel_cap_queues_beyond_max(tmp_path, monkeypatch):
    """layer=unit U-F4-6-08（生命周期⑤a：次数上限 = MAX_PARALLEL）
    3 个 job 同时到期、max_parallel=2 → 本 tick 恰 2 个 fire、第 3 个进 queue（不丢不并）。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    svc = _service(tmp_path, consumer=False, max_parallel=2)
    start = datetime(2026, 10, 1, 9, 0, 0)
    ids = []
    for _ in range(3):
        job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action(), now=start)
        ids.append(job["id"])
    fired = svc.tick(now=start + timedelta(seconds=90))
    fired_ids = sorted(f["id"] for f in fired)
    assert len(fired) == 2
    assert sorted(ids[:2]) == fired_ids
    assert svc.list_jobs()["queue"] == [ids[2]]
    assert len(svc.sessions.enqueued) == 2
    # queue 里的 job 在后续 tick 消费（不超预算补发——供需面见 MO/E2E）
    fired2 = svc.tick(now=start + timedelta(seconds=100))
    assert [f["id"] for f in fired2] == [ids[2]]


def test_u_f4_6_09_budget_and_expiry_caps(tmp_path, monkeypatch):
    """layer=unit U-F4-6-09（生命周期⑤b/c：成本上限 + 到期上限）
    预算耗尽 → fire 拒绝 (SCHEDULE_BUDGET)、零 enqueue；once 规则 fire 后
    enabled=False、next_fire=None（自然到期，不再触发）。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    svc = _service(tmp_path, consumer=False, budget_exhausted=1)
    job = svc.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    result = svc.fire(job["id"])
    assert result["ok"] is False
    assert result["error_code"] == "SCHEDULE_BUDGET"
    assert svc.sessions.enqueued == []

    svc2 = _service(tmp_path / "expiry", consumer=False)   # 与预算腿隔离的持久文件
    once = svc2.create(
        rule={"kind": "at", "time": "2026-10-01T09:00:00"},
        action=_interval_action(),
        now=datetime(2026, 10, 1, 8, 30, 0),
    )
    fired = svc2.fire(once["id"])
    assert fired["ok"] is True
    job_after = svc2._jobs[once["id"]]
    assert job_after["enabled"] is False                  # 到期上限：一次性规则自然终止
    assert job_after["next_fire"] is None
    fired_again = svc2.tick(now=datetime(2026, 10, 1, 10, 0, 0))
    assert fired_again == []
    assert len(svc2.sessions.enqueued) == 1


def test_mo_f4_6_01_tick_dispatch_pending_then_revive_on_restart(tmp_path, monkeypatch):
    """layer=module MO-F4-6-01
    真 tick（到点 fire，持久化 tmp 文件） + 模拟重启（新 service 实例同 path）：
    无窗口 → scheduled_pending 可发现；恢复后 orphan 显式复活 fire-once；
    且 revive_on_restore=True 时自动复活并审计 action="revive"。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")  # 构造不自动 restore，显式控制
    svc = _service(tmp_path, consumer=False)
    due_at = datetime(2026, 10, 1, 9, 0, 0)
    job = svc.create(
        rule={"kind": "interval", "every": 1, "unit": "minutes"},
        action=_interval_action(),
        now=due_at,
    )
    fired = svc.tick(now=due_at + timedelta(seconds=90))
    assert fired and fired[0]["ok"] is True
    assert fired[0]["result"]["execution"] == "scheduled_pending"
    # 模拟运行中崩溃：把 job 置 running 后用新实例从同一文件复原（重启）
    svc._jobs[job["id"]]["run_status"] = "running"
    svc._save()
    rebooted = _service(tmp_path, consumer=False)
    orphans = rebooted.restore_after_restart(revive_orphans=True)
    assert [o["id"] for o in orphans] == [job["id"]]
    job_after = rebooted._jobs[job["id"]]
    assert job_after["orphan"] is False
    revive_rows = [r for r in rebooted.audit() if r.get("action") == "revive"]
    assert len(revive_rows) == 1
    assert revive_rows[0]["job_id"] == job["id"]
    fires = [r for r in rebooted.audit() if r.get("action") == "fire" and r.get("job_id") == job["id"]]
    assert len(fires) == 1                              # 复活只 fire-once：再补恰好 1 次。历史 tick 不删。


def test_revive_redelivers_only_the_persisted_inflight_slot(tmp_path, monkeypatch):
    """A finished tick stays one fire. The next round saved by _open_inflight still replays once."""
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    svc = _service(tmp_path, consumer=False)
    start = datetime(2026, 10, 1, 9, 0, 0)
    job = svc.create(
        rule={"kind": "interval", "every": 1, "unit": "minutes"},
        action=_interval_action(),
        now=start,
    )
    job_id = job["id"]
    fired = svc.tick(now=start + timedelta(seconds=90))
    assert fired and fired[0]["ok"] is True
    before = [
        row for row in svc.audit()
        if row.get("action") == "fire" and row.get("job_id") == job_id
    ]
    assert len(before) == 1
    svc._open_inflight(svc._jobs[job_id])
    rebooted = _service(tmp_path, consumer=False)
    rebooted.restore_after_restart(revive_orphans=True)
    fires = [
        row for row in rebooted.audit()
        if row.get("action") == "fire" and row.get("job_id") == job_id
    ]
    assert len(fires) == 2
    assert fires[0] == before[0]
    assert rebooted._jobs[job_id]["orphan"] is False
    assert rebooted._jobs[job_id].get("inflight_slot") is None
    assert len(rebooted.sessions.enqueued) == 1


def test_mo_f4_6_02_multi_window_does_not_reclaim_orphan(tmp_path, monkeypatch):
    """layer=module MO-F4-6-02（多窗口不互相 reclaim——真实持久文件双实例）
    窗口 A 崩溃留 orphan（run_status=running）；窗口 B（`local_session_ids` 只含自己的
    session）tick 时既不得 fire 也不得 reclaim 该 orphan（`schedule_service.py:244-250`
    `_job_is_local` 现状门禁 + `schedule_loop:355-356` reclaim 分支）。
    """
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    window_a = _service(tmp_path, consumer=False)
    job = window_a.create(rule={"kind": "interval", "every": 1, "unit": "minutes"}, action=_interval_action())
    job_id = job["id"]
    window_a._jobs[job_id]["run_status"] = "running"
    window_a._jobs[job_id]["orphan"] = True
    window_a._save()

    window_b = _service(tmp_path, consumer=False)        # 同 path = 另一扇窗口
    window_b.local_session_ids = {"other-window-session"}
    audit_len_before = len(window_b.audit())
    due_at = datetime.fromisoformat(window_b._jobs[job_id]["next_fire"])
    window_b.tick(now=due_at + timedelta(seconds=10))    # job 到点但非本窗口 → 门禁拦
    after = window_b._jobs[job_id]
    assert after["orphan"] is True                       # 第二窗口不得 reclaim
    assert after["run_status"] == "running"
    new_rows = window_b.audit()[audit_len_before:]
    assert [r for r in new_rows if r.get("action") == "fire"] == []
    assert [r for r in new_rows if r.get("action") == "reclaim"] == []
    assert window_b.sessions.enqueued == []
