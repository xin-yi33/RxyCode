"""F4-1 stall 分级：turn 级 cancel → 决策环（P5 钩子位）→ kill。

废弃代码（2026-10-08 版）：server.py _handle_stalled_job 直接
_fail_job(kill_host=True) 的旧内联实现，已路由到本模块 escalate_stalled_job。
事件名/phase/outcome 与测试包 §1.3 共用唯一真值，禁止第二份字符串。
"""

from __future__ import annotations

import asyncio
import time
import types

EVENT_STALL_ESCALATION = "event/stall_escalation"
STALL_PHASES = ("interrupt", "grace_wait", "grace_end", "kill")
STALL_OUTCOMES = ("kept", "killed", "killed_by_interrupt_fallback", "restart_requested")


async def default_decision_hook(evidence):
    """生产默认决策钩子：恒 None =「到点 kill」的现状决策。

    P5 换成真决策环。签名保持 async，escalate 必须 await。
    """
    return None


def classify_stall_host(host) -> str:
    """Four stall classes. Missing probes stay on the interrupt path.

    ``normal_terminal``: the worker process already exited (poll/returncode).
    ``process_gone``: no process, or it is not alive and has no exit code.
    ``pipe_broken``: the process is alive but the pipe is already marked broken.
    ``loop_stuck``: the process is alive, so interrupt and the decision can run.
    """
    if host is None:
        return "process_gone"
    proc = getattr(host, "_proc", None)
    if proc is not None:
        returncode = getattr(proc, "returncode", None)
        if returncode is None:
            poll = getattr(proc, "poll", None)
            if callable(poll):
                try:
                    returncode = poll()
                except Exception:
                    return "pipe_broken"
        if returncode is not None:
            return "normal_terminal"
    try:
        living = bool(host.alive())
    except Exception:
        return "process_gone"
    if not living:
        return "process_gone"
    # AsyncRpcPipe has no ``broken`` flag. A lost pipe sets degraded / failure_exc.
    pipe = getattr(host, "_pipe", None)
    if pipe is not None and (
        getattr(pipe, "degraded", False) is True
        or getattr(pipe, "failure_exc", None) is not None
    ):
        return "pipe_broken"
    if getattr(host, "degraded", False) is True or getattr(host, "_legacy_degraded", False) is True:
        return "pipe_broken"
    return "loop_stuck"


async def run_stall_interrupt(
    *,
    watchdog,
    host,
    job,
    fail_job,
    emit,
    reason: str,
    grace_seconds: float,
    interrupt_timeout: float = 5.0,
    monotonic=time.monotonic,
    sleep=asyncio.sleep,
) -> dict:
    """Interrupt plus grace. The only turn-cancel implementation.

    Returns ``kept`` (job left during grace), ``killed`` (interrupt already
    killed the host and ``fail_job(kill_host=False)`` ran), or
    ``needs_decision`` (grace expired, hook not called).
    """

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

    if classify_stall_host(host) == "normal_terminal":
        # The process already exited. Do not decide and do not kill it again.
        # Drop the watchdog row so the heartbeat does not re-enter this stall.
        finish = getattr(watchdog, "finish_job", None)
        if callable(finish):
            finish(job.job_id)
        await _phase("grace_end", outcome="kept")
        return {"action": "kept", "reason": reason}
    if classify_stall_host(host) == "pipe_broken":
        # Interrupt reaps the worker when the RPC fails. A thrown kill is not
        # a killed worker: only host.alive() decides whether to try once more.
        await _phase("interrupt")
        if host is not None:
            try:
                await host.interrupt(timeout=interrupt_timeout)
            except Exception:
                pass
            if host.alive():
                kill = getattr(host, "kill_async", None)
                if callable(kill):
                    try:
                        await kill()
                    except Exception:
                        pass
        reaped = host is None or not host.alive()
        if reaped:
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
            return {"action": "killed", "reason": reason}
        return {"action": "needs_decision", "reason": reason}

    await _phase("interrupt")
    interrupt_killed = host is None or not host.alive()
    if not interrupt_killed:
        try:
            outcome = await host.interrupt(timeout=interrupt_timeout)
            interrupt_killed = bool((outcome or {}).get("killed")) or not host.alive()
        except Exception:
            # A raised interrupt is not proof the worker died. kill_async can
            # throw and leave the process alive. Confirm with alive().
            interrupt_killed = not host.alive()
            if not interrupt_killed:
                kill = getattr(host, "kill_async", None)
                if callable(kill):
                    try:
                        await kill()
                    except Exception:
                        pass
                interrupt_killed = not host.alive()
    if not interrupt_killed:
        await _phase("grace_wait")
        deadline = monotonic() + grace_seconds
        while monotonic() < deadline:
            if job.job_id not in watchdog.jobs:
                await _phase("grace_end", outcome="kept")
                return {"action": "kept", "reason": reason}
            await sleep(1.0)
        if job.job_id not in watchdog.jobs:
            await _phase("grace_end", outcome="kept")
            return {"action": "kept", "reason": reason}
        return {"action": "needs_decision", "reason": reason}
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
    return {"action": "killed", "reason": reason}


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
    turn_cancel=None,
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

    if turn_cancel is not None:
        # _try_turn_cancel 是上面 interrupt 的别名。测试可替换它。
        # 替换后这里仍然 await hook，不会再走第二套 cancel。
        recovered = await turn_cancel(job)
        if recovered:
            stashed = None
            if isinstance(turn_cancel, types.MethodType):
                stashed = getattr(turn_cancel.__self__, "_last_stall_result", None)
            if isinstance(stashed, dict) and stashed.get("action"):
                return stashed
            return {"action": "kept", "reason": reason}
    else:
        interrupted = await run_stall_interrupt(
            watchdog=watchdog,
            host=host,
            job=job,
            fail_job=fail_job,
            emit=emit,
            reason=reason,
            grace_seconds=grace_seconds,
            interrupt_timeout=interrupt_timeout,
            monotonic=monotonic,
            sleep=sleep,
        )
        if interrupted.get("action") != "needs_decision":
            return interrupted

    decision = await decision_hook({"job": job, "reason": reason})
    if decision == "continue":
        await _phase("grace_end", outcome="restart_requested")
        return {"action": "restart_requested", "reason": reason}
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
    return {"action": "killed", "reason": reason}
