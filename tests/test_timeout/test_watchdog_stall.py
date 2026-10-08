"""layer=unit P5"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.appserver.watchdog import ActiveJob, WatchdogState


class _StubEngine:
    def __init__(self, action):
        self._action = action
        self.calls = []

    async def decide(self, evidence):
        from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse
        self.calls.append(evidence.model_dump())
        extend = 600.0 if self._action == "continue" else 0.0
        return TimeoutDecisionResponse(action=self._action, extend_seconds=extend,
                                       note="n", confidence=0.8)


async def test_u_p5_01_stop_keeps_kill_host_status_quo():
    """layer=unit U-P5-01 turn-cancel 失败后决策 stop → _fail_job(kill_host=True) 与现状一致"""
    server = AppServer(stub=True)
    server._timeout_engine = _StubEngine("stop")
    server._try_turn_cancel = AsyncMock(return_value=False)     # F4-1 桩：turn 级 cancel 失败
    server._restart_worker_continue = AsyncMock()
    server._fail_job = AsyncMock()
    server._watchdog = WatchdogState()
    await server._handle_stalled_job(ActiveJob(session_id="sess_w", job_id="j9", request_id=3))
    server._fail_job.assert_awaited_once()
    kw = server._fail_job.await_args.kwargs
    assert kw["session_id"] == "sess_w" and kw["code"] == -32004
    assert kw["kill_host"] is True                              # 现状逐字节保持
    server._restart_worker_continue.assert_not_awaited()
    assert server._timeout_engine.calls[0]["trigger_point"] == "watchdog_stall"


def test_u_p5_02_live_worker_never_enters_decision():
    """layer=unit U-P5-02 worker 未死（心跳新鲜）→ stalled_jobs 空 → 决策零触发"""
    state = WatchdogState()
    state.register_job("j1", "sess_live")
    state.touch_job("j1")
    assert state.stalled_jobs() == []                           # 模型静默不算 stall 的另一面
    server = AppServer(stub=True)
    engine = _StubEngine("continue")
    server._timeout_engine = engine
    server._windows_spawn_helper = None
    assert engine.calls == []                                   # 无 stall → 无决策（防御断言）


async def test_u_p5_03_decision_hook_is_truly_awaited_and_restart_once():
    """layer=unit U-P5-03 行为验收：async decision hook 真被 await（calls==1）；
    restart_requested 后外壳重启函数被调恰好一次；自然恢复（turn-cancel 成功）不进 hook"""
    from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse

    class _Hook:
        """记录调用次数的 async 决策 hook——契约钉死（与 escalade 同源）：
        入参 dict（job = evidence["job"]）、返回 "continue"/None 字符串。
        实现若是同步误调（未 await），escalate 后本测试断言时刻 calls 仍为 0 → 永远红（负例钉）；
        实现若返回 TimeoutDecisionResponse 对象而非字符串，escalade 的
        `resp == "continue"` 比较恒假 → calls==1 但 action=killed → 本测试同样必红。"""

        def __init__(self, action):
            self._action = action
            self.calls = 0

        async def __call__(self, evidence: dict):
            self.calls += 1
            _ = evidence["job"]                     # 契约：dict 入参，非 ActiveJob 本体
            return "continue" if self._action == "continue" else None

    # —— escalate 路径：turn-cancel 失败 → hook continue → 重启恰好一次 ——
    server = AppServer(stub=True)
    hook = _Hook("continue")
    server._stall_decision_hook = hook
    server._try_turn_cancel = AsyncMock(return_value=False)
    server._restart_worker_continue = AsyncMock()
    server._fail_job = AsyncMock()
    server._watchdog = WatchdogState()
    await server._handle_stalled_job(ActiveJob(session_id="sess_h", job_id="j_h", request_id=7))
    assert hook.calls == 1                                       # 恰好一次、且真被 await
    server._restart_worker_continue.assert_awaited_once()
    server._fail_job.assert_not_awaited()
    # —— 自然恢复：turn-cancel 成功 → 恢复路径不进决策 hook、不重启 ——
    server2 = AppServer(stub=True)
    hook2 = _Hook("continue")
    server2._stall_decision_hook = hook2
    server2._try_turn_cancel = AsyncMock(return_value=True)      # F4-1 救活
    server2._restart_worker_continue = AsyncMock()
    server2._fail_job = AsyncMock()
    server2._watchdog = WatchdogState()
    await server2._handle_stalled_job(ActiveJob(session_id="sess_r", job_id="j_r", request_id=9))
    assert hook2.calls == 0                                      # 自然恢复仍 kept、不走决策
    server2._restart_worker_continue.assert_not_awaited()
    server2._fail_job.assert_not_awaited()


def test_u_p5_04_persistent_restart_gate_forces_stop_regardless_of_ledger():
    """layer=unit U-P5-04 裁定 C：appserver 持久闸在 task_store 持久层——
    restart_count 达 max_restarts(=2) 或 total_wall 超限 → 强制 stop，与 worker ledger 无关；
    新 job_id 不重置该计数（闸键是 session_id）"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import restart_gate_verdict

    section = {"max_restarts": 2, "restart_total_wall_seconds": 7200.0}
    # restart_count 达闸：ledger 是空也不放行
    assert restart_gate_verdict({"restart_count": 2, "first_restart_at": 9000.0},
                                section, now=9500.0) == "max_restarts"
    # total_wall 超限
    assert restart_gate_verdict({"restart_count": 1, "first_restart_at": 0.0},
                                section, now=7200.1) == "total_wall"
    # 未达闸：放行
    assert restart_gate_verdict({"restart_count": 1, "first_restart_at": 9000.0},
                                section, now=9500.0) is None
    # 新 job_id：计数键是 session_id，换 job 不构成清零（job 字段不参与判定）
    assert restart_gate_verdict({"restart_count": 2, "first_restart_at": 9000.0,
                                 "last_job_id": "job_new"},
                                section, now=9500.0) == "max_restarts"


async def test_u_p5_05_first_legal_restart_is_not_misjudged_as_capped():
    """layer=unit U-P5-05 三轮复审 #2 回归锚：真实 Policy + 默认配置下，
    首次合法恢复（budget=restart_grant_base 900.0 < cap 1800）**不得**被误判封顶。
    （防的是「total_wall 剩余量 7080 被填进 budget_seconds → pre_check 立即 stop」
    这类预算混用——budget_seconds 只许取 restart_grant_base_seconds。）"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import (
        DecisionPolicy, timeout_decision_config,
    )
    from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence

    policy = DecisionPolicy(timeout_decision_config({"timeout_decision": {"enabled": True}}))
    ev = TimeoutEvidence(                          # 字段全集（§1.4）：缺一即 ValidationError
        trigger_point="watchdog_stall", session_id="s", run_id="r1", subject_id="job_1",
        task_hint="stall job", elapsed_seconds=130.0,
        budget_seconds=900.0, extension_index=0,
        progress="working on build", last_error="",
    )
    # pre_check 不得触发封顶（budget 900 < cap 1800；k=1 ≤ max_extensions=2）
    assert policy.pre_check(ev, k=1) is None
    # grant 合法：room = 1800 - 900 = 900 ≥ requested 600 → 全额授予
    g = policy.grant(trigger_point="watchdog_stall", budget=900.0, k=1, extend_seconds=600.0)
    assert (g.granted_seconds, g.new_budget) == (600.0, 1500.0)
    # 负例：若有人把 total_wall 剩余量填进来（如 7080 ≥ cap 1800）→ pre_check 必 stop
    bad = ev.model_copy(update={"budget_seconds": 7080.0})
    stop = policy.pre_check(bad, k=1)
    assert stop is not None and stop.action == "stop"
    assert stop.note.startswith("[policy] absolute cap reached")


def test_mo_p5_01_restart_worker_continue_seams_present():
    """layer=module MO-P5-01 接缝存在性（注意：这不是「调用序验收」——GPT 审计后
    顺序 mock 断言删除；真实执行语义验收在 E-P-E2E-03 生产链上）"""
    server = AppServer(stub=True)
    for name in ("_restart_worker_continue", "_try_turn_cancel",
                     "_spawn_session_host", "_kill_session_host"):
        assert callable(getattr(server, name, None)), name
    assert callable(getattr(server._sessions, "hydrate", None))


def test_mo_p5_02_worker_restart_ledger_starts_from_zero():
    """layer=module MO-P5-02 appserver ledger 纪律：每 session 独立、worker 重启从 0 不继承"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import ExtensionLedger

    old_worker = ExtensionLedger()
    scope = ("sess_r", "j_r")
    old_worker.record(scope, 900.0)
    old_worker.record(scope, 1800.0)
    assert old_worker.count(scope) == 2
    new_worker = ExtensionLedger()                      # 新进程实例：额度不继承
    assert new_worker.count(scope) == 0
    assert new_worker.total_extended(scope) == 0.0
    assert old_worker.count(("sess_r2", "j_r")) == 0    # 每 session 独立（同 ledger 内 scope 隔离）


@pytest.mark.asyncio
async def test_mo_p5_03_resume_write_blocked_with_real_orchestrator(tmp_path):
    """layer=module MO-P5-03（五轮复审 #2：at-most-once **接线级**验收）
    「恢复后同一写被阻止重放」必须经**真实 ToolOrchestrator 的 journal binding**
    验证（stub worker 不执行真实工具；E2E 上写 reserve/uncertain 断言只能验证
    journal 自身）。手法照抄既有真实接线测试
    `tests/test_core/test_tool_journal.py:108`（16 passed）。
    三段钉死 + 一段假阳性防线：
      ① pending 组：恢复后同一 attempt 再试同一写 → blocked 文案命中、底层写零执行；
      ② 对照组：空值班 attempt 同一写执行一次、计数 1、产物存在；
      ③ 假阳性防线：不绑定 journal 的同一写必然执行——若它也 blocked，
         说明断言根本没在测 binding（接线断开必须让整案失败）。
    """
    from pathlib import Path
    from unittest.mock import patch

    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal, new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    # 六轮复审实测修正三处夹具错误（执行即可复现红→绿）：
    # ① attempt 合法性：`att_` 后须 32 位 hex（execution/tool_journal.py:36 校验），
    #   用 new_attempt_id()，禁止非法固定值（'att_e2e03' 会被 ValueError 拒）；
    # ② 工具必须 StructuredTool 包装——执行器调的是 .invoke()/.ainvoke()，
    #   裸函数不会被调用（手法照抄 tests/test_core/test_tool_journal.py:12-21）；
    # ③ 成功路径会自动 journal.complete（tool_orchestrator.py:828-831），
    #   不能在回调里 return "written" 然后假定保持 pending——必须仅第一次调用
    #   注入提交失败，真实制造「写已执行，结果未提交」。
    counter = {"calls": 0}

    async def _counting_write(path: str, content: str) -> str:
        counter["calls"] += 1
        Path(path).write_text(content, encoding="utf-8")
        return "written"

    write_tool = StructuredTool.from_function(            # ② StructuredTool 包装
        coroutine=_counting_write, name="write", description="counting write",
    )
    orch = ToolOrchestrator()
    orch.register("write", write_tool)
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()                         # ① 合法 attempt ID
    cfg = {"safety": {"enabled": False}}
    args = {"path": str(tmp_path / "m.txt"), "content": "x"}

    # ③ 仅第一次调用注入提交失败（patch journal.complete，tool_journal.py:387）
    with patch.object(journal, "complete", side_effect=OSError("simulated lost commit")):
        tok = orch.bind_tool_journal(journal, attempt_id)
        try:
            await orch.execute_tool("write", dict(args), config=cfg)
        finally:
            orch.reset_tool_journal(tok)
    assert counter["calls"] == 1
    assert journal.has_pending(attempt_id) is True

    # ① pending 组：恢复后同一 attempt 再试同一写（真实执行面 + 真 binding）
    tok = orch.bind_tool_journal(journal, attempt_id)
    try:
        blocked = await orch.execute_tool(
            "write", {"path": str(tmp_path / "m.txt"), "content": "x"}, config=cfg)
    finally:
        orch.reset_tool_journal(tok)
    assert "[blocked: previous outcome unknown" in blocked   # tool_orchestrator.py:724 生产文案
    assert counter["calls"] == 1                              # 底层写零执行

    # ② 对照组：空值班 attempt（干净 journal 段）同一写执行一次、产物存在
    tok = orch.bind_tool_journal(journal, new_attempt_id())
    try:
        await orch.execute_tool("write", {"path": str(tmp_path / "c.txt"), "content": "x"}, config=cfg)
    finally:
        orch.reset_tool_journal(tok)
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "x"
    assert counter["calls"] == 2

    # ③ 假阳性防线：不绑定 journal 的同一写必然执行——上面的 blocked 若在这条
    #    同样出现，说明断言根本没在测 binding。
    await orch.execute_tool("write", {"path": str(tmp_path / "u.txt"), "content": "x"}, config=cfg)
    assert (tmp_path / "u.txt").exists()
    assert counter["calls"] == 3
