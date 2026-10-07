"""F4-1 stall 分级：turn 级 cancel → 决策环（P5 钩子位）→ kill。

废弃代码（2026-10-08 版）：server.py _handle_stalled_job 直接
_fail_job(kill_host=True) 的旧内联实现，已路由到本模块 escalate_stalled_job。
事件名/phase/outcome 与测试包 §1.3 共用唯一真值，禁止第二份字符串。
"""

from __future__ import annotations

import asyncio
import time

EVENT_STALL_ESCALATION = "event/stall_escalation"
STALL_PHASES = ("interrupt", "grace_wait", "grace_end", "kill")
STALL_OUTCOMES = ("kept", "killed", "killed_by_interrupt_fallback", "restart_requested")


async def default_decision_hook(evidence):
    """生产默认决策钩子：恒 None =「到点 kill」的现状决策。

    P5 换成真决策环。签名保持 async，escalate 必须 await。
    """
    return None


async def escalate_stalled_job(
    *,
    watchdog,
    host,
    job,
    fail_job,
    emit,
    stall_seconds: float,
    grace_seconds: float,
    decision_hook=None,
    interrupt_timeout: float = 5.0,
    monotonic=time.monotonic,
    sleep=asyncio.sleep,
) -> dict:
    reason = f"job stalled >{stall_seconds}s (session {job.session_id})"
    if decision_hook is None:
        # 现状逐字节（旧 _handle_stalled_job；U-F4-1-04 回退护栏）。
        await fail_job(
            session_id=job.session_id,
            job_id=job.job_id,
            request_id=job.request_id,
            code=-32004,
            message=reason,
            kill_host=True,
            degrade_reason=reason,
        )
        return {"action": "legacy_kill"}

    async def _phase(phase: str, **extra) -> None:
        await emit(
            {
                "method": EVENT_STALL_ESCALATION,
                "params": {
                    "session_id": job.session_id,
                    "job_id": job.job_id,
                    "phase": phase,
                    **extra,
                },
            }
        )

    await _phase("interrupt")
    interrupt_killed = host is None or not host.alive()
    if not interrupt_killed:
        try:
            outcome = await host.interrupt(timeout=interrupt_timeout)
            interrupt_killed = bool((outcome or {}).get("killed")) or not host.alive()
        except Exception:
            # agent_host.interrupt 抛异常时已自行 kill。跳过 grace，不二次 kill。
            interrupt_killed = True
    if not interrupt_killed:
        await _phase("grace_wait")
        deadline = monotonic() + grace_seconds
        while monotonic() < deadline:
            if job.job_id not in watchdog.jobs:
                await _phase("grace_end", outcome="kept")
                return {"action": "kept"}
            await sleep(1.0)
        if job.job_id not in watchdog.jobs:
            await _phase("grace_end", outcome="kept")
            return {"action": "kept"}
        decision = await decision_hook({"job": job, "reason": reason})
        if decision == "continue":
            await _phase("grace_end", outcome="restart_requested")
            return {"action": "restart_requested"}
        await _phase("kill", outcome="killed")
        await fail_job(
            session_id=job.session_id,
            job_id=job.job_id,
            request_id=job.request_id,
            code=-32004,
            message=reason,
            kill_host=True,
            degrade_reason=reason,
        )
        return {"action": "killed"}
    await _phase("kill", outcome="killed_by_interrupt_fallback")
    await fail_job(
        session_id=job.session_id,
        job_id=job.job_id,
        request_id=job.request_id,
        code=-32004,
        message=reason,
        kill_host=False,
        degrade_reason=reason,
    )
    return {"action": "killed"}
