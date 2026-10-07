"""layer=e2e E-F4-E2E-01 stall 分级全链路。"""
from __future__ import annotations

import pytest

from tests.e2e.fix4.helpers import (
    AppserverClient,
    appserver_env,
    collect_until,
    shutdown_appserver,
    spawn_appserver,
)

pytestmark = pytest.mark.e2e


def _stall_env(grace: str) -> dict:
    return appserver_env(
        {
            "RXYCODE_APPSERVER_STALL_SECONDS": "2",
            "RXYCODE_APPSERVER_HEARTBEAT_SECONDS": "1",
            "RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS": "0",   # 断 worker 心跳
            "RXYCODE_APPSERVER_STALL_GRACE_SECONDS": grace,      # F4-1 新增 env
        }
    )


def _stall_phases(events: list[dict]) -> list[str]:
    return [
        str((m.get("params") or {}).get("phase"))
        for m in events
        if m.get("method") == "event/stall_escalation"
    ]


def _stall_outcomes(events: list[dict]) -> list[str]:
    return [
        str((m.get("params") or {}).get("outcome"))
        for m in events
        if m.get("method") == "event/stall_escalation" and "outcome" in (m.get("params") or {})
    ]


def test_e2e_f4_01a_stall_interrupt_grace_kept_host_alive(tmp_path):
    """layer=e2e E-F4-E2E-01（kept 路径）
    阶段：setup（真 appserver 子进程 + stub agent）→ 扰动（turn 断心跳触发 stall
    → interrupt turn 级取消成功）→ 断言（事件序列 interrupt→grace_wait→grace_end(kept)；
    prompt 以 cancelled 语义的 RPC 响应结束而非 -32004；同一 host 上的后续 prompt 成功
    = 进程未被 kill；watchdog 未 degrade）。
    """
    proc = spawn_appserver(_stall_env("999"))       # grace 远大于观测窗：kept 必然在 grace 内发生
    client = AppserverClient(proc)
    try:
        session_id = client.initialize_and_session(str(tmp_path))
        prompt_id = client.send(
            "session/prompt",
            {"session_id": session_id, "text": "hang:forever"},
        )
        events = collect_until(
            client,
            lambda seen: "kept" in _stall_outcomes(seen)
            and any(m.get("id") == prompt_id and ("error" in m or "result" in m) for m in seen),
            timeout=30.0,
        )
        assert _stall_phases(events) == ["interrupt", "grace_wait", "grace_end"]
        assert _stall_outcomes(events) == ["kept"]
        job_states = [
            str((m.get("params") or {}).get("state"))
            for m in events
            if m.get("method") == "event/job_status"
        ]
        assert "failed" not in job_states
        prompt_done = next(m for m in events if m.get("id") == prompt_id)
        if "error" in prompt_done:
            assert prompt_done["error"]["code"] != -32004
            assert "cancel" in str(prompt_done["error"].get("message", "")).lower()
        else:
            assert prompt_done["result"].get("status") != "timeout"
        degraded = [
            bool((m.get("params") or {}).get("degraded"))
            for m in events
            if m.get("method") == "event/server_heartbeat"
        ]
        assert True not in degraded
        recovered = client.request(
            "session/prompt",
            {"session_id": session_id, "text": "hello after kept stall"},
            timeout=15.0,
        )
        assert recovered["status"] == "succeeded"     # 同 host 未被杀（kept 的证据）
        assert recovered["text"] == "stub:hello after kept stall"
    finally:
        shutdown_appserver(proc)


def test_e2e_f4_01b_stall_grace_expires_kills_and_recovers(tmp_path):
    """layer=e2e E-F4-E2E-01（killed 路径）
    扰动（interrupt 取消不动且 grace=1s 耗尽）→ 断言：interrupt→grace_wait→kill、
    prompt 收到 -32004、degraded 心跳出现、恢复后下一 prompt 成功（既有 recover 路径交叉断言）。
    """
    proc = spawn_appserver(_stall_env("1"))
    client = AppserverClient(proc)
    try:
        session_id = client.initialize_and_session(str(tmp_path))
        prompt_id = client.send(
            "session/prompt",
            {"session_id": session_id, "text": "hang:forever"},
        )
        def killed(seen):
            has_err = any(
                m.get("id") == prompt_id
                and "error" in m
                and m["error"].get("code") == -32004
                for m in seen
            )
            has_degraded = any(
                m.get("method") == "event/server_heartbeat"
                and bool((m.get("params") or {}).get("degraded"))
                for m in seen
            )
            return has_err and has_degraded

        events = collect_until(client, killed, timeout=30.0)
        assert killed(events), f"kill 路径未走完: {events[-3:] if events else []}"
        assert _stall_phases(events) == ["interrupt", "grace_wait", "kill"]
        assert _stall_outcomes(events) == ["killed"]
        job_states = [
            str((m.get("params") or {}).get("state"))
            for m in events
            if m.get("method") == "event/job_status"
        ]
        assert "failed" in job_states
        recovered = client.request(
            "session/prompt",
            {"session_id": session_id, "text": "hello after stalled job"},
            timeout=15.0,
        )
        assert recovered["status"] == "succeeded"
    finally:
        shutdown_appserver(proc)
