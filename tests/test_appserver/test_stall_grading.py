"""layer=unit/module F4-1 watchdog stall 分级。"""
from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.appserver.watchdog import ActiveJob, WatchdogState


def _fake_host(*, cancel_on_interrupt: bool, watchdog: WatchdogState, job_id: str):
    """同形 AgentHost：记录 interrupt/kill；可选：interrupt 把 job 抹掉（等于任务被 turn 级取消）。"""

    class _Host:
        def __init__(self):
            self.interrupt_calls: list[float] = []
            self.kill_calls = 0

        def alive(self) -> bool:
            return True

        async def interrupt(self, *, timeout: float = 5.0):
            self.interrupt_calls.append(timeout)
            if cancel_on_interrupt:
                watchdog.finish_job(job_id)  # turn 级取消成功 → job 消失
            return {"cancelled": cancel_on_interrupt, "failed": False, "killed": False}

        async def kill_async(self) -> None:
            self.kill_calls += 1

    return _Host()


def _clock():
    now = {"t": 1000.0}

    def monotonic() -> float:
        return now["t"]

    async def sleep(seconds: float) -> None:
        now["t"] += seconds

    return monotonic, sleep


def _recording_hook(answer=None):
    """裁定 C（2026-10-02）：decision_hook 必须是 ASYNC 可调用——escalate 必须 await。
    同步 hook 会让返回值变 coroutine 对象被比较（§4 红灯"同步比较协程对象"永红锚）。"""

    class _Hook:
        def __init__(self):
            self.calls = 0
            self.evidences: list = []
            self.seen_evidence_type: type | None = None   # 三轮复审 #1：dict 入参契约的记录面

        async def __call__(self, evidence):
            self.calls += 1
            self.evidences.append(evidence)
            self.seen_evidence_type = type(evidence)
            _ = evidence["job"]            # 契约钉：dict 入参（ActiveJob 永不直传）
            return answer                  # 契约钉：返回 "continue" 或 None（字符串）

    return _Hook()



def test_u_f4_1_01_interrupt_before_grace_and_event_order():
    """layer=unit U-F4-1-01
    预期先红：ImportError（stall_grading 尚不存在）。
    stall 后必须先 interrupt、再等 grace，且事件序列为 interrupt→grace_wait→grace_end。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    async def main():
        watchdog = WatchdogState()
        watchdog.register_job("j1", "sess_1")
        job = watchdog.jobs["j1"]
        host = _fake_host(cancel_on_interrupt=True, watchdog=watchdog, job_id="j1")
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        hook = _recording_hook()
        monotonic, sleep = _clock()
        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=hook,
            monotonic=monotonic,
            sleep=sleep,
        )
        assert result["action"] == "kept"
        assert hook.calls == 0                           # kept 在 grace 内出清，kill 判定点未到
        assert host.interrupt_calls == [5.0]          # interrupt 先发生，timeout=5.0
        assert host.kill_calls == 0
        assert fail_calls == []                        # kept 路径绝不 _fail_job
        stall_events = [e for e in events if e.get("method") == EVENT_STALL_ESCALATION]
        phases = [e["params"]["phase"] for e in stall_events]
        assert phases == ["interrupt", "grace_wait", "grace_end"]
        assert stall_events[-1]["params"]["outcome"] == "kept"
        assert stall_events[-1]["params"]["job_id"] == "j1"

    asyncio.run(main())


def test_u_f4_1_02_grace_expires_still_kills_with_legacy_code():
    """layer=unit U-F4-1-02
    grace 超时（job 一直心跳断、interrupt 取消不掉）→ 必须落到现状 kill 路径：
    code=-32004、kill_host=True、reason 逐字节为现状模板。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    async def main():
        watchdog = WatchdogState()
        watchdog.register_job("j2", "sess_1")
        job = watchdog.jobs["j2"]
        host = _fake_host(cancel_on_interrupt=False, watchdog=watchdog, job_id="j2")
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        hook = _recording_hook()
        monotonic, sleep = _clock()
        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=hook,
            monotonic=monotonic,
            sleep=sleep,
        )
        assert result["action"] == "killed"
        assert hook.calls == 1                           # kill 判定点 await hook 恰一次（裁定 C 行为钉）
        assert hook.evidences[0]["reason"] == "job stalled >120.0s (session sess_1)"
        assert len(fail_calls) == 1
        call = fail_calls[0]
        assert call["code"] == -32004
        assert call["kill_host"] is True
        assert call["session_id"] == "sess_1"
        assert call["job_id"] == "j2"
        assert call["message"] == "job stalled >120.0s (session sess_1)"
        assert call["degrade_reason"] == "job stalled >120.0s (session sess_1)"
        phases = [e["params"]["phase"] for e in events if e.get("method") == EVENT_STALL_ESCALATION]
        assert phases == ["interrupt", "grace_wait", "kill"]

    asyncio.run(main())


def test_u_f4_1_03_grace_boundary_job_finishing_in_grace_not_killed():
    """layer=unit U-F4-1-03
    grace 期内 job 完成（非 interrupt 直接造成）→ kill_host 不调；结果 kept。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import escalate_stalled_job

    async def main():
        watchdog = WatchdogState()
        watchdog.register_job("j3", "sess_1")
        job = watchdog.jobs["j3"]
        host = _fake_host(cancel_on_interrupt=False, watchdog=watchdog, job_id="j3")
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        calls = {"n": 0}
        now = {"t": 0.0}

        def monotonic() -> float:
            return now["t"]

        async def sleep(seconds: float) -> None:
            now["t"] += seconds
            calls["n"] += 1
            if calls["n"] == 2:
                watchdog.finish_job("j3")  # grace 中途 job 完成

        hook = _recording_hook()
        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=hook,
            monotonic=monotonic,
            sleep=sleep,
        )
        assert result["action"] == "kept"
        assert hook.calls == 0
        assert fail_calls == []
        assert host.kill_calls == 0

    asyncio.run(main())


def test_u_f4_1_04_legacy_byte_equal_when_no_decision_hook():
    """layer=unit U-F4-1-04
    decision_hook=None → 与现状（server.py:841-860）逐字节等价：
    一次 _fail_job(code=-32004, kill_host=True)，不调 interrupt，零 stall 事件。
    （本条守卫现状，落地即绿；它是回退护栏。）
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    async def main():
        watchdog = WatchdogState()
        watchdog.register_job("j4", "sess_x")
        job = watchdog.jobs["j4"]
        job.request_id = 42
        host = _fake_host(cancel_on_interrupt=False, watchdog=watchdog, job_id="j4")
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=None,
        )
        assert result["action"] == "legacy_kill"
        assert host.interrupt_calls == []
        assert [e for e in events if e.get("method") == EVENT_STALL_ESCALATION] == []
        assert len(fail_calls) == 1
        call = fail_calls[0]
        assert call["code"] == -32004
        assert call["kill_host"] is True
        assert call["request_id"] == 42
        assert call["message"] == "job stalled >120.0s (session sess_x)"
        assert call["degrade_reason"] == call["message"]

    asyncio.run(main())


def test_u_f4_1_05_interrupt_fallback_killed_no_second_kill():
    """layer=unit U-F4-1-05（P5 对齐，2026-10-01 GPT 审计）
    interrupt RPC 失败兜底已杀 host（AgentHost.interrupt 返回 {"killed": True}
    或抛异常）→ 跳过 grace，outcome=killed_by_interrupt_fallback，fail_job 恰一次
    且 kill_host=False（不二次 kill），零 grace_wait 事件。
    每种形态各跑一次：05a 返回 killed=True；05b interrupt 抛异常前已自尽。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    class _HostSuicide:
        def __init__(self, *, style: str):
            self.style = style
            self.kill_calls = 0
            self.interrupt_calls = 0

        def alive(self) -> bool:
            return self.kill_calls == 0

        async def interrupt(self, *, timeout: float = 5.0):
            self.interrupt_calls += 1
            if self.style == "returns_killed":
                # AgentHost.interrupt 兜底形态（agent_host.py:970-974）：RPC 抛错→
                # 自行 kill_async → 返回 failed/killed。
                self.kill_calls += 1
                return {"cancelled": False, "failed": True, "killed": True}
            # 兜底把异常透出上级（host 已被杀，raise 只是痕迹）
            self.kill_calls += 1
            raise ConnectionError("pipe dead")

        async def kill_async(self) -> None:
            self.kill_calls += 1

    async def run(style: str):
        watchdog = WatchdogState()
        watchdog.register_job("j5", "sess_1")
        job = watchdog.jobs["j5"]
        host = _HostSuicide(style=style)
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        hook = _recording_hook()
        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=hook,
        )
        assert result["action"] == "killed"
        assert hook.calls == 0                          # 自杀分支确定性 kill：不咨询 hook
        stall_events = [e for e in events if e.get("method") == EVENT_STALL_ESCALATION]
        phases = [e["params"]["phase"] for e in stall_events]
        assert phases == ["interrupt", "kill"]          # 无 grace_wait / grace_end
        assert stall_events[-1]["params"]["outcome"] == "killed_by_interrupt_fallback"
        assert len(fail_calls) == 1
        assert fail_calls[0]["code"] == -32004
        assert fail_calls[0]["kill_host"] is False      # host 已死，不二次 kill
        assert fail_calls[0]["message"] == "job stalled >120.0s (session sess_1)"
        assert host.kill_calls == 1                     # 仅兜底那 1 次；escalate 不追加

    asyncio.run(run("returns_killed"))
    asyncio.run(run("raises_after_suicide"))


@pytest.mark.asyncio
async def test_mo_f4_1_01_watchdog_host_grading_module(tmp_path):
    """layer=module MO-F4-1-01
    真 WatchdogState + 同形 host（真 asyncio，微小时间窗）：
    stall → interrupt 取消成功 → kept → watchdog 不进 degraded、同一 host 继续可用。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    watchdog = WatchdogState()
    watchdog.register_job("jm", "sess_m")
    job = watchdog.jobs["jm"]
    host = _fake_host(cancel_on_interrupt=True, watchdog=watchdog, job_id="jm")
    events: list[dict] = []
    fail_calls: list[dict] = []

    async def fail_job(**kwargs):
        fail_calls.append(kwargs)

    async def emit(message):
        events.append(message)

    hook = _recording_hook()
    result = await escalate_stalled_job(
        watchdog=watchdog,
        host=host,
        job=job,
        fail_job=fail_job,
        emit=emit,
        stall_seconds=0.05,
        grace_seconds=0.5,
        decision_hook=hook,
    )
    assert result["action"] == "kept"
    assert hook.calls == 0
    assert "jm" not in watchdog.jobs                # turn 级取消后 job 已出清
    assert watchdog.degraded is False               # kept 路径不得 degrade
    assert fail_calls == []
    outcomes = [e["params"].get("outcome") for e in events if e.get("method") == EVENT_STALL_ESCALATION]
    assert outcomes[-1] == "kept"


def test_u_f4_1_06_hook_continue_requests_restart_no_fail(tmp_path):
    """layer=unit U-F4-1-06（裁定 C，2026-10-02；三轮复审 #1 修型）
    hook（ASYNC，dict 入参）返回 "continue" → escalate：grace_end(outcome=restart_requested)、
    result["action"]=="restart_requested"、fail_job 零次；**escalade 不执行重启**
    （重启职责唯一归属外壳——旧稿 `restart_worker=` 参数已删除，参数面必须不存在）；
    hook.calls == 1 行为钉（同步 mis-call 永红）；job 不被 escalate 清理（外壳接管）。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    async def main():
        watchdog = WatchdogState()
        watchdog.register_job("j6", "sess_1")
        job = watchdog.jobs["j6"]
        host = _fake_host(cancel_on_interrupt=False, watchdog=watchdog, job_id="j6")
        fail_calls: list[dict] = []
        events: list[dict] = []

        async def fail_job(**kwargs):
            fail_calls.append(kwargs)

        async def emit(message):
            events.append(message)

        hook = _recording_hook(answer="continue")
        monotonic, sleep = _clock()
        result = await escalate_stalled_job(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            stall_seconds=120.0,
            grace_seconds=20.0,
            decision_hook=hook,
            monotonic=monotonic,
            sleep=sleep,
        )
        assert result["action"] == "restart_requested"
        assert hook.calls == 1                          # kill 判定点恰一次 await（行为钉）
        assert hook.calls == 1 and hook.seen_evidence_type is dict   # dict 入参契约
        assert fail_calls == []                         # continue → 绝不 fail_job
        stall_events = [e for e in events if e.get("method") == EVENT_STALL_ESCALATION]
        phases = [e["params"]["phase"] for e in stall_events]
        assert phases == ["interrupt", "grace_wait", "grace_end"]
        assert stall_events[-1]["params"]["outcome"] == "restart_requested"
        assert "j6" in watchdog.jobs                    # escalate 不清理，外壳接管

    asyncio.run(main())


@pytest.mark.asyncio
async def test_mo_f4_1_02_restart_requested_outer_shell_once():
    """layer=module MO-F4-1-02（裁定 C：restart 出口**外壳**恰一次；三轮复审 #1 修型）
    真 asyncio 微小时间窗 + ASYNC hook "continue"：escalade 返回 restart_requested
    后，**外壳接线**（escalade 不含重启参数面）调 `_restart_worker_continue` 恰一次、
    fail_job 零次、watchdog 不进 degraded、事件面带 outcome=restart_requested。
    """
    from RxyCode.RxyCode1_1_0.appserver.stall_grading import (
        EVENT_STALL_ESCALATION,
        escalate_stalled_job,
    )

    watchdog = WatchdogState()
    watchdog.register_job("jm2", "sess_m2")
    job = watchdog.jobs["jm2"]
    host = _fake_host(cancel_on_interrupt=False, watchdog=watchdog, job_id="jm2")
    events: list[dict] = []
    fail_calls: list[dict] = []
    restart_calls = {"n": 0}

    async def fail_job(**kwargs):
        fail_calls.append(kwargs)

    async def emit(message):
        events.append(message)

    hook = _recording_hook(answer="continue")
    result = await escalate_stalled_job(
        watchdog=watchdog,
        host=host,
        job=job,
        fail_job=fail_job,
        emit=emit,
        stall_seconds=0.05,
        grace_seconds=0.2,
        decision_hook=hook,
    )
    assert result["action"] == "restart_requested"
    assert hook.calls == 1
    assert fail_calls == []

    # 外壳接线钉（server._handle_stalled_job 同构）：restart_requested → 重启恰一次
    async def shell_dispatch(result: dict) -> None:
        if result.get("action") == "restart_requested":
            restart_calls["n"] += 1                    # 生产位：await _restart_worker_continue(job)

    await shell_dispatch(result)
    assert restart_calls["n"] == 1
    assert watchdog.degraded is False
    assert watchdog.degraded is False
    outcomes = [e["params"].get("outcome") for e in events if e.get("method") == EVENT_STALL_ESCALATION]
    assert outcomes[-1] == "restart_requested"
