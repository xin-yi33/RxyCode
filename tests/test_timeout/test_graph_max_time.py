# tests/test_timeout/test_graph_max_time.py（文件头）
"""layer=unit P3"""
from __future__ import annotations

import asyncio
import time

import pytest

from RxyCode.RxyCode1_1_0.core import graph as graph_mod


class _Tracker:
    """与 _ProgressTracker 同构最小替身。"""
    def __init__(self):
        self.last_activity = time.monotonic()
        self.error_count = 0
        self.last_error = ""
        self.chunks_received = 0
        self.guidance_notes: list[str] = []

    def seconds_since_activity(self):
        return time.monotonic() - self.last_activity


class _StubEngine:
    """真实 decide / last_grant 接口形状的 stub（§1.9 名录形状，不是旧 granted_budget 调用形）。"""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.grants_read: list[tuple[str, str]] = []
        self._grant = None

    async def decide(self, evidence):
        from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse
        from RxyCode.RxyCode1_1_0.core.timeout_decision import Grant
        self.calls.append(evidence.model_dump())
        resp = TimeoutDecisionResponse(**self._responses.pop(0))
        if resp.action in ("continue", "steer"):
            self._grant = Grant(granted_seconds=resp.extend_seconds,
                                new_budget=evidence.budget_seconds + resp.extend_seconds)
        return resp

    def last_grant(self, scope):
        self.grants_read.append(tuple(scope))
        return self._grant

async def test_u_p3_01_continue_extends_and_task_survives(monkeypatch):
    """layer=unit U-P3-01 max_time 到点挂起不 return；continue → max_timeout 增加且任务存活"""
    engine = _StubEngine([
        {"action": "continue", "extend_seconds": 600.0, "note": "还大干", "confidence": 0.8},
    ])
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    tracker = _Tracker()
    tracker.last_activity = time.monotonic() - 0.1     # 活的心跳：不是 stall
    task = asyncio.create_task(graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: {"trigger_point": "graph_task_max_time"},
    ))
    await asyncio.sleep(0.5)                           # 早过 0.2s 现状死线
    assert not task.done()                             # 挂起而非 return "max_time"
    assert engine.calls and engine.calls[0]["trigger_point"] == "graph_task_max_time"
    assert len(engine.grants_read) == 1                  # 落地恰读一次 last_grant
    assert engine._grant.new_budget == 600.2             # 只用本次 Grant.new_budget 覆盖上限
    tracker.error_count = 3                            # 用 error 通道收尾
    assert await asyncio.wait_for(task, timeout=1.0) == "error"


async def test_u_p3_02_stop_byte_identical_to_status_quo(monkeypatch):
    """layer=unit U-P3-02 决策 stop → 返回串与现状 return "max_time" 逐字节一致"""
    engine = _StubEngine([
        {"action": "stop", "extend_seconds": 0.0, "note": "无望", "confidence": 0.9},
    ])
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    tracker = _Tracker()
    out = await graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: {"trigger_point": "graph_task_max_time"},
    )
    assert out == "max_time"
    reason = out
    result = f"[{reason}] Task '{'x'*50}' did not complete normally."
    assert result.startswith("[max_time] Task '")       # :568-569 现状拼装串锚点


async def test_u_p3_03_engine_disabled_returns_status_quo():
    """layer=unit U-P3-03 enabled=false：不摸引擎，直接 return "max_time"（逐字节现状路径）"""
    tracker = _Tracker()
    out = await graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": False}},
        evidence_factory=lambda: {"trigger_point": "graph_task_max_time"},
    )
    assert out == "max_time"

async def test_mo_p3_01_steer_injects_guidance_and_short_extension(monkeypatch):
    """layer=module MO-P3-01 steer → 注入指引（tracker.guidance_notes）+ 短延期 + tui 进度"""
    engine = _StubEngine([
        {"action": "steer", "extend_seconds": 30.0, "note": "先补单测再回头", "confidence": 0.7},
    ])
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    tracker = _Tracker()
    messages: list[str] = []

    class _FakeTui:
        def write_progress(self, s): messages.append(s)

    task = asyncio.create_task(graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: {"trigger_point": "graph_task_max_time"}, tui=_FakeTui(),
    ))
    await asyncio.sleep(0.4)
    assert not task.done()
    assert tracker.guidance_notes == ["先补单测再回头"]   # 指引注入证据链
    assert any("先补单测再回头" in m for m in messages)    # 用户可见引痕
    tracker.error_count = 3
    assert await asyncio.wait_for(task, timeout=1.0) == "error"
