"""layer=e2e E-P-E2E-03

StubAgent 诚实注记：worker agent 为 StubAgent（appserver/bootstrap.py:31-36）；
本链验证协议/调度/重启接线，不验证 AgentV2 行为。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.execution import tool_journal as tj
from RxyCode.RxyCode1_1_0.protocol.version import PROTOCOL_VERSION
from tests.e2e.phase_p import helpers
from tests.test_appserver.test_stdio_integration import AppserverClient, _appserver_env
from tests.contract.test_timeout_cancel import _marker_pids

pytestmark = pytest.mark.e2e
REPO = Path(__file__).resolve().parents[3]


def _spawn(tmp_path: Path, *, decision_lines, prompt_lines, extra_env=()):
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_TIMEOUT_DECISION_STUB_FILE"] = str(tmp_path / "decisions.jsonl")
    env["RXYCODE_STUB_PROMPT_REPLIES_FILE"] = str(tmp_path / "prompts.jsonl")
    for kv in extra_env:
        k, _, v = kv.partition("=")
        env[k] = v
    (tmp_path / "decisions.jsonl").write_text(
        "\n".join(decision_lines), encoding="utf-8")
    (tmp_path / "prompts.jsonl").write_text(
        "\n".join(prompt_lines), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"], cwd=REPO, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1)
    return proc, AppserverClient(proc)


def _collect_until(client: AppserverClient, pred, timeout=30.0):
    """读通知直到 pred 命中或超时；返回全部通知列表。"""
    deadline = time.monotonic() + timeout
    seen: list[dict] = []
    while time.monotonic() < deadline:
        note = client.readline(timeout=1.0)
        if note is None:
            continue
        seen.append(note)
        if pred(note):
            return seen
    raise AssertionError(f"condition not met in {timeout}s; seen={seen}")


def test_e2e_p_03_restart_worker_continue(tmp_path):
    """layer=e2e E-P-E2E-03 生产链：stall→决策 continue→真实 restart→新 worker 重跑产出 Final

    三轮复审 #4 修正：interrupt 语义改「RPC 成功但 cancelled=False」
    （RXYCODE_STUB_INTERRUPT_NO_CANCEL）——继续场景不得用 INTERRUPT_FAILS
    （按 F4-1 那是 host 已死、跳过决策）；journal pending 绑定**原任务实际
    attempt**（RXYCODE_STUB_ATTEMPT_ID 固定），观察的是该写是否被阻止重放，
    而不是无关 attempt 的条目存在。
    """
    # ── 阶段 1 setup：真实 appserver 子进程 + 预置绑定原 attempt 的 pending journal ──
    proc, client = _spawn(
        tmp_path,
        decision_lines=[helpers.cont(600, "重启接续")],
        prompt_lines=["(stalled-worker-silence)", "E2E03-FINAL"],
        extra_env=("RXYCODE_STUB_STALL_AFTER_PROMPT=1",
                   "RXYCODE_STUB_INTERRUPT_NO_CANCEL=1",
                   "RXYCODE_STUB_ATTEMPT_ID=att_0123456789abcdef0123456789abcdef"),
    )
    try:
        client.request("initialize",
                       {"client_name": "e2e", "protocol_version": PROTOCOL_VERSION}, timeout=10.0)
        sess = client.request("session/new", {"workspace_root": str(tmp_path)}, timeout=10.0)
        sid = sess["session_id"]
        # tool journal：pending 写条目绑定 run 将使用的固定 attempt（后门注入）——
        # 只用 execution/tool_journal.py 既有真实接口（禁发明 for_session/pending_calls）
        journal = tj.ToolExecutionJournal()
        attempt_id = "att_0123456789abcdef0123456789abcdef"   # 合法：att_ + 32 hex（tool_journal.py:36）
        digest = tj.arguments_digest({"path": "marker-should-not-rerun.txt"})
        call = tj.JournalCall(key=tj.stable_call_key("write", digest, 0),
                              tool="write", args_digest=digest, ordinal=0)
        assert journal.reserve(attempt_id, call).action == "execute"
        assert journal.has_pending(attempt_id) is True
        marker_file = tmp_path / "marker-should-not-rerun.txt"
        # ── 阶段 2 扰动：发 prompt（worker 即刻失联，stall 2s 后进入决策环）──
        _prompt_id = client.send("session/prompt", {"session_id": sid, "text": "跑一个 10 分钟构建"})
        assert _marker_pids("e2e-03-worker-marker")            # 失联 worker 进程树在
        # ── 阶段 3 断言：事件 → 唯一终态 → Final 重启执行 ──
        seen = _collect_until(client, lambda n: n.get("method") == "event/timeout_decision")
        decision_events = [n for n in seen if n.get("method") == "event/timeout_decision"]
        assert len(decision_events) == 1
        d0 = decision_events[0].get("params", decision_events[0])
        helpers.assert_event_fields(d0, trigger_point="watchdog_stall",
                                    action="continue", fail_closed=False)
        seen = _collect_until(client, lambda n: n.get("method") == "event/final")
        finals = [n for n in seen if n.get("method") == "event/final"]
        assert len(finals) == 1                                  # (b) 原 prompt 恰好一次终态
        f0 = finals[0].get("params", finals[0])
        assert f0["text"] == "E2E03-FINAL"                       # (c) 新 worker 重跑产出真实 Final
        assert _marker_pids("e2e-03-worker-marker") == set()     # (a) 旧进程树被回收
        # (d) at-most-once 锚点（五轮复审 #2 修正）：run 使用绑定 attempt（journal
        #     文件可核）；「恢复后同一写被阻止重放」的**接线级事实**验收在
        #     **MO-P5-03**（真实 ToolOrchestrator + 真 binding + 假阳性防线），
        #     不在本 E2E——stub worker 不执行真实工具，在此处写 reserve/uncertain
        #     断言只能验证 journal 自身。本 E2E 只保留位置可核的 pending 锚：
        doc = journal.load(attempt_id)
        assert doc["entries"][call.key]["status"] == "pending"
        assert set(doc["entries"]) == {call.key}
        assert not marker_file.exists()
        assert proc.poll() is None                               # appserver 不降级不退化
    finally:
        proc.kill()


def test_e2e_p_03_killed_by_interrupt_fallback(tmp_path):
    """layer=e2e E-P-E2E-03 killed_by_interrupt_fallback（四轮复审 #3 语义修正）：
    **首次** interrupt 成功但 cancelled=False（NO_CANCEL，否则会违背 F4-1：
    首次 RPC 失败 = host 已死 = 跳过决策直接 fallback）→ 决策 continue、restart 启动；
    **restart 阶段** interrupt RPC 失败 → fallback 终局（action=stop、outcome 如实、
    不再二次 kill）。
    （语义对照组「首次 interrupt RPC 失败 → 直接 fallback、决策调用零次」的断言
    已含在 U-P5-01/02 的 killed_by_interrupt_fallback 分支，E2E 不再重复。）"""
    proc, client = _spawn(
        tmp_path,
        decision_lines=[helpers.cont(600, "复活它")],
        prompt_lines=["(stalled-worker-silence)", "E2E03-FALLBACK-FINAL"],
        extra_env=("RXYCODE_STUB_STALL_AFTER_PROMPT=1",
                   "RXYCODE_STUB_INTERRUPT_NO_CANCEL=1",
                   "RXYCODE_STUB_RESTART_INTERRUPT_PHASE_FAILS=1"),  # 仅 restart 阶段的 interrupt 炸
    )
    try:
        client.request("initialize",
                       {"client_name": "e2e", "protocol_version": PROTOCOL_VERSION}, timeout=10.0)
        sess = client.request("session/new", {"workspace_root": str(tmp_path)}, timeout=10.0)
        sid = sess["session_id"]
        client.send("session/prompt", {"session_id": sid, "text": "长任务"})
        is_decision = lambda n: n.get("method") == "event/timeout_decision"
        # 第 1 条事件：决策 continue（restart 流程启动）
        batch1 = _collect_until(client, is_decision)
        # 第 2 条事件：restart 内 interrupt RPC 失败 → fallback 终局（action=stop）
        batch2 = _collect_until(client, is_decision)
        decisions = [(m.get("params", m)) for m in (batch1 + batch2) if is_decision(m)]
        assert len(decisions) == 2                               # 恰两条，不再二次 kill
        helpers.assert_event_fields(decisions[0], trigger_point="watchdog_stall",
                                    action="continue")
        helpers.assert_event_fields(decisions[1], trigger_point="watchdog_stall",
                                    action="stop")
        assert "killed_by_interrupt_fallback" in decisions[1]["note"]   # outcome 如实记
        terminal = _collect_until(
            client, lambda n: n.get("error") is not None
            or n.get("method") in ("event/final", "event/error"))
        terminal_notes = [n for n in terminal
                          if n.get("error") or n.get("method") in ("event/final", "event/error")]
        assert len(terminal_notes) == 1                          # 唯一终态，按 stop 落地
        assert _marker_pids("e2e-03-worker-marker") == set()
    finally:
        proc.kill()
