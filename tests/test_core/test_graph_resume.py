"""layer=unit/module F4-5 既有恢复链（route_entry/_prepare_graph_state）回归与上限。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _tree_two_tasks(*, t1_status="passed", t2_status="pending"):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

    root = TaskNode(id="root", title="Root", children_ids=["t1", "t2"])
    t1 = TaskNode(
        id="t1", title="Task 1", parent_id="root", depth=1,
        status=TaskStatus(t1_status), result="t1 result",
    )
    t2 = TaskNode(
        id="t2", title="Task 2", parent_id="root", depth=1,
        status=TaskStatus(t2_status), dependent_tasks=["t1"],
    )
    return TaskTree(goal_id="root", nodes={"root": root, "t1": t1, "t2": t2})


def _agent_hydrator(store, **overrides):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._session_id = "sess_f45"
    agent._checkpoint_store = store
    agent._llm = MagicMock(name="llm")
    agent._memory = MagicMock(name="memory")
    agent._tool_orchestrator = MagicMock(name="tools")
    agent._tool_tracer = MagicMock(name="tracer")
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def test_u_f4_5_01_route_entry_resumes_at_next_uncommitted_boundary():
    """layer=unit U-F4-5-01（既有恢复链回归）
    加载未完成 checkpoint → route_entry 按 durable phase 进对节点：
    未到/无树 → goal_plan；planned→decompose；validating→validate；reflecting→reflect；
    verifying→final_verify；done→end；executing + 残留 pending 叶 → execute。
    """
    from RxyCode.RxyCode1_1_0.core.graph import route_entry

    assert route_entry({"task_tree": None}) == "goal_plan"
    cases = {
        "planning": "decompose",
        "planned": "decompose",
        "validating": "validate",
        "reflecting": "reflect",
        "verifying": "final_verify",
        "done": "end",
    }
    for phase, expected in cases.items():
        assert route_entry({"task_tree": _tree_two_tasks(), "phase": phase}) == expected, phase
    executing = route_entry({
        "task_tree": _tree_two_tasks(),
        "phase": "executing",
        "conversation_history": [],
        "memory_context": "",
        "compression_count": 0,
        "parallel_requested": False,
    })
    assert executing == "execute"


def test_u_f4_5_02_hydrate_restores_tree_object_once(tmp_path):
    """layer=unit U-F4-5-02（既有恢复链 + 还原唯一性）
    hydrate 后 task_tree 是 TaskTree 对象不是 dict；磁盘文档的 dict 不被改写为对象；
    两次 hydrate 产出两个独立对象（单点还原、无二次 dict 覆盖）；runtime 键注入不覆盖 durable 键。
    """
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.core.state import TaskTree

    store = CheckpointStore(directory=tmp_path / "checkpoints")
    store.save(
        "sess_f45", "build login", "build",
        {"task_tree": _tree_two_tasks(), "phase": "executing", "resume_attempts": 0},
    )
    agent = _agent_hydrator(store)

    hydrated1 = agent._prepare_graph_state(
        {"session_id": "sess_f45", "user_input": "build login"},
        checkpoint_key_input="build login",
        mode="build",
    )
    assert isinstance(hydrated1["task_tree"], TaskTree)          # 对象，不是 dict
    assert hydrated1["phase"] == "executing"
    assert hydrated1["_llm"] is agent._llm                        # runtime 注入位
    assert hydrated1["task_tree"].nodes["t1"].status.value == "passed"
    assert hydrated1["task_tree"].get_pending_leaves()[0].id == "t2"

    on_disk = store.load(store.checkpoint_id("sess_f45", "build login", "build"))
    assert isinstance(on_disk["state"]["task_tree"], dict)        # 盘上仍是 dict（未被对象污染）
    assert on_disk["state"]["task_tree"]["nodes"]["t1"]["status"] == "passed"

    hydrated2 = agent._prepare_graph_state(
        {"session_id": "sess_f45", "user_input": "build login"},
        checkpoint_key_input="build login",
        mode="build",
    )
    assert isinstance(hydrated2["task_tree"], TaskTree)
    assert hydrated2["task_tree"] is not hydrated1["task_tree"]  # 单点还原，各一次


def test_u_f4_5_03_resume_budget_exhaustion_honest_failure_and_preserved(tmp_path):
    """layer=unit U-F4-5-03（resume 上限）
    第 1/2 次放行（exhausted False）；attempts=2 → exhausted True；诚实失败文案
    必含 "2/2" 与 checkpoint_id；checkpoint 文件保留（completed 仍 False（供人工）；
    attempt_id 不变（禁"全新 attempt"绕过）。
    """
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.core.graph import (
        RESUME_MAX_ATTEMPTS,
        resume_budget_exhausted,
        resume_exhausted_notice,
    )

    assert RESUME_MAX_ATTEMPTS == 2
    store = CheckpointStore(directory=tmp_path / "checkpoints")
    doc = store.save(
        "sess_f45", "build login", "build",
        {"task_tree": _tree_two_tasks(), "phase": "executing", "resume_attempts": 0},
    )
    assert resume_budget_exhausted(doc) is False                  # 第 1 次放行
    doc["state"]["resume_attempts"] = 1
    assert resume_budget_exhausted(doc) is False                  # 第 2 次放行
    doc = store.save(
        "sess_f45", "build login", "build",
        {"task_tree": _tree_two_tasks(), "phase": "executing", "resume_attempts": 2},
    )
    assert resume_budget_exhausted(doc) is True                   # 第 3 次拒绝
    notice = resume_exhausted_notice(doc)
    assert "2/2" in notice
    assert doc["checkpoint_id"] in notice
    reloaded = store.begin_attempt("sess_f45", "build login", "build")
    assert reloaded["attempt_id"] == doc["attempt_id"]            # 不换 attempt
    assert reloaded["completed"] is False                         # 现场保留可人工
    assert (tmp_path / "checkpoints" / f"{doc['checkpoint_id']}.json").exists()


def test_u_f4_5_04_interrupted_running_task_normalized_to_pending(tmp_path):
    """layer=unit U-F4-5-04（现状恢复守卫回归：checkpoints.py:427-470）
    running 任务 load 时归一为 pending（记 recovery_notes、phase=executing）；
    validating + 已提交 result 的 running 任务不重置（防重复副作用的现状豁免）。
    """
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore(directory=tmp_path / "checkpoints")
    store.save(
        "sess_f45", "build login", "build",
        {"task_tree": _tree_two_tasks(t2_status="running"), "phase": "executing"},
    )
    loaded = store.load(store.checkpoint_id("sess_f45", "build login", "build"))
    t2 = loaded["state"]["task_tree"]["nodes"]["t2"]
    assert t2["status"] == "pending"
    assert loaded["state"]["phase"] == "executing"
    recovered = [n for n in loaded["recovery_notes"] if n.get("event") == "interrupted_task_recovered"]
    assert len(recovered) == 1
    assert recovered[0]["from_status"] == "running"
    assert recovered[0]["to_status"] == "pending"

    store2 = CheckpointStore(directory=tmp_path / "checkpoints2")
    tree = _tree_two_tasks(t2_status="running")
    tree.nodes["t2"].result = "t2 submitted before validation"
    store2.save(
        "sess_f45", "build login", "build",
        {"task_tree": tree, "phase": "validating"},
    )
    loaded2 = store2.load(store2.checkpoint_id("sess_f45", "build login", "build"))
    assert loaded2["state"]["task_tree"]["nodes"]["t2"]["status"] == "running"  # 现状豁免不重置


def test_mo_f4_5_01_tool_journal_pending_blocks_repeat_write(tmp_path):
    """layer=module MO-F4-5-01（tool journal 对齐）
    预置 pending 写调用（crash 在 reserve 后、complete 前）→ resume（同一 attempt）后
    同签名调用 reserve 返回 "uncertain"（阻塞重复副作用）；无重复文件写入；
    attempt_id 不变（禁"全新 attempt"绕过断言）；complete 后同签名 reserve 为 "reuse"。
    """
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

    store = CheckpointStore(directory=tmp_path / "checkpoints")
    journal = ToolExecutionJournal(directory=tmp_path / "journal")
    doc = store.save(
        "sess_f45", "build login", "build",
        {"task_tree": _tree_two_tasks(), "phase": "executing", "resume_attempts": 0},
    )
    attempt = store.begin_attempt("sess_f45", "build login", "build")
    assert attempt["attempt_id"] == doc["attempt_id"]
    checkpoint_id = doc["checkpoint_id"]
    binding = journal.binding(doc["attempt_id"], checkpoint_id)
    out_file = tmp_path / "written.txt"
    call = binding.next_call("write_file", {"path": str(out_file), "content": "A"})
    reservation = journal.reserve(doc["attempt_id"], call, checkpoint_id=checkpoint_id)
    assert reservation.action == "execute"                        # 首跑获批
    # —— 模拟 crash：reserve 之后进程死了，complete 从未发生 ——
    assert journal.has_pending(doc["attempt_id"]) is True

    attempt2 = store.begin_attempt("sess_f45", "build login", "build")
    assert attempt2["attempt_id"] == doc["attempt_id"]            # 禁 fresh attempt 绕过
    binding2 = journal.binding(doc["attempt_id"], checkpoint_id)
    call2 = binding2.next_call("write_file", {"path": str(out_file), "content": "A"})
    assert call2.key == call.key                                   # 同签名 → 同 stable key
    reservation2 = journal.reserve(doc["attempt_id"], call2, checkpoint_id=checkpoint_id)
    assert reservation2.action == "uncertain"                     # 阻塞，不重放副作用
    assert not out_file.exists()                                  # 无重复文件写入

    cleaned = journal.complete(doc["attempt_id"], call, "write ok")
    assert cleaned == "write ok"
    reservation3 = journal.reserve(doc["attempt_id"], call2, checkpoint_id=checkpoint_id)
    assert reservation3.action == "reuse"
    assert reservation3.result == "write ok"


@pytest.mark.asyncio
async def test_mo_f4_5_02_real_store_hydrate_compiled_graph_resume(tmp_path, monkeypatch):
    """layer=module MO-F4-5-02（既有恢复链端到端，生产 LangGraph）
    真 CheckpointStore 的种子现场（phase=verifying）→ _prepare_graph_state hydrate →
    生产 build_graph().ainvoke：goal_planner 绝不重复执行（恢复后首次节点非 goal_planner）、
    跑到 done、checkpoint 被 mark_complete。
    """
    from RxyCode.RxyCode1_1_0.core import graph as graph_module
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore(directory=tmp_path / "checkpoints")
    base_state = {
        "session_id": "sess_f45",
        "user_input": "build login",
        "task_tree": _tree_two_tasks(t1_status="cancelled", t2_status="cancelled"),
        "execution_results": [],
        "parallel_tasks": [],
        "parallel_requested": False,
        "reflections": [],
        "failure_attribution": {},
        "replan_count": 0,
        "reflection_action": None,
        "final_verification": None,
        "compression_count": 0,
        "final_response": "optimistic answer",
        "phase": "verifying",
        "error": None,
        "resume_attempts": 0,
    }
    store.save("sess_f45", "build login", "build", base_state)

    planner_calls = 0

    async def boom_planner(_state):
        nonlocal planner_calls
        planner_calls += 1
        raise AssertionError("goal_planner must not re-run on resume")

    monkeypatch.setattr(graph_module, "goal_planner_node", boom_planner)
    agent = _agent_hydrator(store)
    agent._memory = SimpleNamespace(store_execution=AsyncMock())   # synthesizer 通道的现状契约
    hydrated = agent._prepare_graph_state(
        {k: v for k, v in base_state.items() if not k.startswith("_")},
        checkpoint_key_input="build login",
        mode="build",
    )
    from RxyCode.RxyCode1_1_0.core.state import TaskTree

    assert isinstance(hydrated["task_tree"], TaskTree)             # 未重建 TaskTree dict
    graph = graph_module.build_graph()
    result = await graph.ainvoke(hydrated, {"recursion_limit": 10})
    assert planner_calls == 0                                      # 恢复后首次节点非 goal_planner
    assert result["phase"] == "done"
    reloaded = store.load(store.checkpoint_id("sess_f45", "build login", "build"))
    assert reloaded["completed"] is True                           # 真 store 落盘闭环
