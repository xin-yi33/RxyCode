"""layer=e2e E-F4-E2E-05 graph resume（组合链路 2：生产链中断恢复）。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tests.support.scripted_llm import ScriptedChatModel

pytestmark = pytest.mark.e2e

KEY_INPUT = "two file build"
SESSION_ID = "sess_e05"


def _tree(*, t2_status="running"):
    root = TaskNode(id="root", title="Root", children_ids=["t1", "t2"])
    t1 = TaskNode(
        id="t1", title="write out1", parent_id="root", depth=1,
        status=TaskStatus.PASSED, result="wrote out1.txt",
    )
    t2 = TaskNode(
        id="t2", title="write out2", parent_id="root", depth=1,
        status=TaskStatus(t2_status), dependent_tasks=["t1"],
    )
    return TaskTree(goal_id="root", nodes={"root": root, "t1": t1, "t2": t2})


def _memory():
    return SimpleNamespace(
        get_task_context=AsyncMock(return_value=""),
        store_execution=AsyncMock(),
        store_plan_experience=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_e2e_f4_05_crash_resume_completed_write_not_repeated(tmp_path, monkeypatch):
    """layer=e2e E-F4-E2E-05
    setup：真 store/journal/orchestrator + 生产门 execute_tool 真写 out1.txt（journal reserve+complete）。
    扰动：observed_node 包裹的节点抛 CancelledError（生产 wrapper 落未完成 checkpoint）。
    断言：resume 走 _prepare_graph_state/route_entry（首节点非 goal_planner、TaskTree 对象化）、
    已完成写不重复（out1 content/mtime/journal 三锚）、production graph 跑到 done 收到真实 Final、
    resume 预算耗尽时诚实失败且现场保留。
    """
    from RxyCode.RxyCode1_1_0.core import graph as graph_module
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    ws = tmp_path / "ws"
    ws.mkdir()
    out1 = ws / "out1.txt"
    store = CheckpointStore(directory=tmp_path / "checkpoints")
    journal = ToolExecutionJournal(directory=tmp_path / "journal")
    attempt = store.begin_attempt(SESSION_ID, KEY_INPUT, "build")
    checkpoint_id = attempt["checkpoint_id"]
    orch = ToolOrchestrator()
    journal_token = ToolOrchestrator.bind_tool_journal(journal, attempt["attempt_id"], checkpoint_id)
    cfg = {"safety": {"enabled": False}, "execution": {"workspace_root": str(ws)}}

    # ---- 阶段 1：真实 build 第一腿（生产工具门真写文件，journal 记账）----
    written = await orch.execute_tool(
        "write", {"filePath": str(out1), "content": "A"}, cfg
    )
    assert "[error" not in written
    assert out1.read_text(encoding="utf-8") == "A"
    journal_doc = journal.load(attempt["attempt_id"])
    completed_entries = [e for e in journal_doc["entries"].values() if e["status"] == "completed"]
    assert len(completed_entries) == 1                     # t1 写调用恰 1 条

    # ---- 阶段 2：强制 cancel（生产 observed_node 落未完成现场）----
    crash_state = {
        "session_id": SESSION_ID,
        "user_input": KEY_INPUT,
        "task_tree": _tree(t2_status="running"),
        "phase": "executing",
        "current_task_id": "t2",
        "execution_results": [],
        "resume_attempts": 0,
        "_tracer": None,
        "_hooks": None,
        "_checkpoint_store": store,
        "_checkpoint_key_input": KEY_INPUT,
        "_checkpoint_mode": "build",
        "_memory": _memory(),
    }

    async def crash_node(_state):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await graph_module.observed_node("executor", crash_node)(crash_state)
    mtime_after_write = out1.stat().st_mtime_ns

    crashed = store.load(checkpoint_id)
    assert crashed["completed"] is False
    t2_disk = crashed["state"]["task_tree"]["nodes"]["t2"]
    assert t2_disk["status"] == "pending"                  # load 归一化（恢复快照面）

    # ---- 阶段 3：resume（既有 route_entry/_prepare_graph_state 链路）----
    ToolOrchestrator.reset_tool_journal(journal_token)
    ToolOrchestrator.bind_tool_journal(journal, attempt["attempt_id"], checkpoint_id)
    agent = object.__new__(AgentV2)
    agent._session_id = SESSION_ID
    agent._checkpoint_store = store
    agent._llm = ScriptedChatModel([AIMessage(content="t2 完成报告")])
    agent._memory = _memory()
    agent._tool_orchestrator = orch
    agent._tool_tracer = None

    async def _boom(_state):
        raise AssertionError("goal_planner must not re-run on resume")

    monkeypatch.setattr(graph_module, "goal_planner_node", _boom)
    hydrated = agent._prepare_graph_state(
        {"session_id": SESSION_ID, "user_input": KEY_INPUT},
        checkpoint_key_input=KEY_INPUT,
        mode="build",
    )
    assert isinstance(hydrated["task_tree"], TaskTree)   # 未重建 TaskTree dict
    assert hydrated["task_tree"].nodes["t2"].status == TaskStatus.PENDING
    hydrated["_tui"] = None
    hydrated["_capabilities"] = None
    hydrated["_model_router"] = None
    assert graph_module.route_entry(hydrated) == "execute"  # 首节点非 goal_planner

    graph = graph_module.build_graph()
    result = await graph.ainvoke(hydrated, {"recursion_limit": 30})
    assert result["phase"] == "done"                       # 收到真实 Final（生产图收尾）
    assert isinstance(result["final_response"], str) and result["final_response"] != ""
    assert out1.read_text(encoding="utf-8") == "A"         # 三锚①：内容不变
    assert out1.stat().st_mtime_ns == mtime_after_write    # 三锚②：未重放写
    journal_doc2 = journal.load(attempt["attempt_id"])
    out1_entries = [
        e for e in journal_doc2["entries"].values()
        if e["status"] == "completed"
    ]
    assert len(out1_entries) == 1                          # 三锚③：journal 无重复登记
    assert store.load(checkpoint_id)["completed"] is True  # 闭环：journal 无 pending → seal

    # ---- 阶段 4：预算耗尽 → 诚实失败、现场保留（独立请求键，隔离阶段 3 的 seal）----
    budget_input = "two file build budget-exhausted"
    doc2 = store.save(
        SESSION_ID, budget_input, "build",
        {"task_tree": _tree(t2_status="running"), "phase": "executing", "resume_attempts": 2},
    )
    from RxyCode.RxyCode1_1_0.core.graph import (
        resume_budget_exhausted,
        resume_exhausted_notice,
    )

    assert resume_budget_exhausted(doc2) is True
    notice = resume_exhausted_notice(doc2)
    assert "2/2" in notice
    assert doc2["checkpoint_id"] in notice
    assert doc2["completed"] is False                              # 耗尽现场保留，不 seal
    preserved = store.load(doc2["checkpoint_id"])
    assert preserved is not None
    assert preserved["completed"] is False
    assert store.begin_attempt(SESSION_ID, budget_input, "build")["attempt_id"] == doc2["attempt_id"]
