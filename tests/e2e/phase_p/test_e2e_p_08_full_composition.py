"""layer=e2e E-P-E2E-08"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core import graph as graph_mod
from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.compaction import compact_messages
from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
from tests.e2e.phase_p import helpers

pytestmark = pytest.mark.e2e


class _Tracker:
    def __init__(self):
        self.last_activity = time.monotonic()
        self.error_count = 0
        self.last_error = ""
        self.chunks_received = 0
        self.guidance_notes = []

    def seconds_since_activity(self):
        return time.monotonic() - self.last_activity


def _steer(note, extend=60):
    import json

    return json.dumps({"action": "steer", "extend_seconds": extend, "note": note, "confidence": 0.75})


async def test_e2e_p_08_todo_steer_compact_hooks_rewind(monkeypatch, tmp_path):
    """layer=e2e E-P-E2E-08 长任务综合：五机制组合、最终状态一致、无跨机制污染"""
    # ── 阶段 1 setup：权威 TodoSnapshot（P8 只投影）+ 真实 hooks + 真实 engine（steer）──
    from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot
    todo = TodoSnapshot(
        session_id="sess_long", root_session_id="sess_long", list_id="default",
        revision=1, scope="turn", source="model",
        items=[TodoItem(id="T1", content="搭骨架", status="completed"),
               TodoItem(id="T2", content="装依赖", status="in_progress"),
               TodoItem(id="T3", content="跑构建", status="pending")],
        updated_at="2026-10-02T00:00:00Z")
    todo_items_ids_before = [i.id for i in todo.items]
    hooks = HookRegistry(default_timeout_seconds=1.0)
    seq: list[str] = []
    for phase in ("before", "after"):
        hooks.register(phase, lambda ctx, p=phase: seq.append(f"{p}/{ctx.subject}"))
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([_steer("压缩后先验依赖清单")]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=ledger, sink=(collect := []), hooks=hooks)
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    # ── 阶段 2 扰动：watchdog 到点（steer 救回）→ 压缩 fold → rewind ──
    tracker = _Tracker()
    watcher = asyncio.create_task(graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: helpers.evidence_dict(
            progress=td.todo_progress_snapshot(todo))))
    await asyncio.sleep(0.5)
    assert not watcher.done()
    snap = td.todo_progress_snapshot(todo)
    assert snap == "[1/3] completed 搭骨架 | in_progress 装依赖 | pending 跑构建"  # 交叉①todo×证据包
    msgs = [SimpleNamespace(type="human", content="做构建系统", tool_calls=None),
            *[SimpleNamespace(type=t, content=f"m{i}", tool_calls=None)
              for i, t in enumerate(("ai", "human") * 4)]]
    await hooks.emit("before", "compact", {})
    folded = compact_messages(msgs, tail_turns=1, return_telemetry=False)     # 交叉③压缩
    await hooks.emit("after", "compact", {})
    assert len(folded) <= len(msgs)
    agent = AgentV2.__new__(AgentV2)
    s1 = "S1-FROZEN-BYTES"
    agent._agent_prefix_messages = [SystemMessage(content=s1), HumanMessage(content="u1"),
                                    AIMessage(content="a1")]
    agent._truncate_agent_prefix(keep=1)                                      # 交叉④rewind（F4-4 产物）
    assert agent._agent_prefix_messages[0].content == s1                      # S1 前缀纪律不破
    tracker.error_count = 3
    assert await asyncio.wait_for(watcher, timeout=2.0) == "error"
    # ── 阶段 3 断言：终态一致、无跨机制污染 ──
    assert tracker.guidance_notes == ["压缩后先验依赖清单"]                    # steer 注入
    assert ledger.count(("sess_e2e", "task_e2e")) == 1                        # scope 键
    assert [e["action"] for e in collect] == ["steer"]
    assert collect[0]["note"] == "压缩后先验依赖清单"
    head = [s for s in seq if "timeout_decision" in s]
    assert head[:2] == ["before/timeout_decision", "after/timeout_decision"]  # 交叉②决策×hooks 序
    assert seq[-2:] == ["before/compact", "after/compact"]
    assert [i.id for i in todo.items] == todo_items_ids_before                 # 压缩/rewind 未污染快照
    assert td.todo_progress_snapshot(todo) == snap                             # 快照复现
