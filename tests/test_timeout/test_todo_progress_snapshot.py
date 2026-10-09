"""P8 production evidence consumer regressions."""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


class _DecisionEngine:
    def __init__(self, action: str = "stop") -> None:
        from RxyCode.RxyCode1_1_0.core.timeout_decision import Grant

        self.action = action
        self.calls = []
        self._grant = Grant(granted_seconds=1.0, new_budget=1000.0)

    async def decide(self, evidence):
        from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse

        self.calls.append(evidence)
        extend = 1.0 if self.action == "continue" else 0.0
        return TimeoutDecisionResponse(
            action=self.action,
            extend_seconds=extend,
            note="test",
            confidence=0.8,
        )

    def last_grant(self, _scope):
        return self._grant


def _write_todo(session_id: str, *, content: str = "编译", status: str = "in_progress"):
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    return todo_write(
        [{"id": "t1", "content": content, "status": status}],
        merge=False,
        session_id=session_id,
    )


def test_todo_progress_snapshot_projects_all_five_statuses_exactly():
    from RxyCode.RxyCode1_1_0.core.timeout_decision import todo_progress_snapshot
    from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot

    snapshot = TodoSnapshot(
        session_id="five-state",
        root_session_id="five-state",
        list_id="default",
        revision=4,
        scope="turn",
        source="model",
        items=[
            TodoItem(id="p", content="pending", status="pending"),
            TodoItem(id="i", content="active", status="in_progress"),
            TodoItem(id="c", content="done", status="completed"),
            TodoItem(id="b", content="blocked", status="blocked"),
            TodoItem(id="x", content="cancelled", status="cancelled"),
        ],
        updated_at="2026-10-09T00:00:00Z",
    )

    assert todo_progress_snapshot(snapshot) == (
        "[1/5] pending pending | in_progress active | completed done | "
        "blocked blocked | cancelled cancelled"
    )


@pytest.mark.parametrize(
    "handle",
    [None, SimpleNamespace(items=[]), SimpleNamespace(items=[SimpleNamespace(status="bad")])],
    ids=["none", "empty", "malformed"],
)
def test_todo_progress_snapshot_empty_or_malformed_handle_is_empty(handle):
    from RxyCode.RxyCode1_1_0.core.timeout_decision import todo_progress_snapshot

    assert todo_progress_snapshot(handle) == ""


def test_todo_progress_reads_latest_authoritative_snapshot_and_isolates_scopes(
    isolated_runtime, monkeypatch
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.core.timeout_decision import todo_progress_for_session
    from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot
    from RxyCode.RxyCode1_1_0.tools import todo_events
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_summary_llm_calls

    session_id = "p8-parent"
    _write_todo(session_id, content="旧计划")
    assert "旧计划" in todo_progress_for_session(session_id)
    _write_todo(session_id, content="新计划")
    assert "新计划" in todo_progress_for_session(session_id)
    assert "旧计划" not in todo_progress_for_session(session_id)

    _write_todo("p8-sibling", content="兄弟计划")
    assert "兄弟计划" not in todo_progress_for_session(session_id)
    assert todo_progress_for_session("p8-child") == ""

    path = Path(os.environ["RXYCODE_DATA_DIR"]) / "tasks" / session_id / "tasks.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert todo_progress_for_session(session_id)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert todo_progress_for_session("p8-empty") == ""
    invalid_path = Path(os.environ["RXYCODE_DATA_DIR"]) / "tasks" / "p8-invalid" / "tasks.json"
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_text("{not-json", encoding="utf-8")
    invalid_before = invalid_path.read_bytes()
    assert todo_progress_for_session("p8-invalid") == ""
    assert invalid_path.read_bytes() == invalid_before

    valid = TodoSnapshot(
        session_id=session_id,
        root_session_id=session_id,
        list_id="default",
        revision=9,
        scope="turn",
        source="model",
        items=[TodoItem(id="t1", content="x", status="pending")],
        updated_at="2026-10-09T00:00:00Z",
    )
    for wrong in (
        valid.model_copy(update={"root_session_id": "p8-other"}),
        valid.model_copy(update={"list_id": "other"}),
        valid.model_copy(update={"scope": "goal"}),
    ):
        monkeypatch.setattr(todo_events, "read_todo_snapshot", lambda _sid, wrong=wrong: wrong)
        assert todo_progress_for_session(session_id) == ""

    monkeypatch.setattr(todo_events, "read_todo_snapshot", lambda _sid: None)
    assert todo_progress_for_session(session_id) == ""
    assert todo_summary_llm_calls == 0


async def test_pipeline_timeout_evidence_consumes_real_todo_snapshot(
    isolated_runtime, monkeypatch
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_module
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    session_id = "p8-pipeline"
    _write_todo(session_id, content="pipeline step")
    engine = _DecisionEngine("continue")
    agent = AgentV2.__new__(AgentV2)
    agent._timeout_engine = engine
    agent._session_id = session_id
    agent._pipeline_scope_run_id = None
    agent._pipeline_extension_index = 0
    agent._last_timeout_note = None
    monkeypatch.setattr(agent_module, "get_current_run_id", lambda: "p8-run")
    graph_task = asyncio.create_task(asyncio.sleep(30))
    try:
        stopped, budget = await agent._pipeline_budget_branch(
            graph_task, soft_budget=100.0, elapsed=101.0
        )
    finally:
        graph_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await graph_task
    assert stopped is False
    assert budget == 1000.0
    assert "pipeline step" in engine.calls[0].progress


class _Tracker:
    def __init__(self) -> None:
        self.error_count = 0
        self.last_error = ""
        self.chunks_received = 0
        self.guidance_notes = []

    def seconds_since_activity(self) -> float:
        return 0.0


async def test_graph_timeout_evidence_reads_snapshot_before_decision(
    isolated_runtime, monkeypatch
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.core import graph as graph_module

    session_id = "p8-graph"
    _write_todo(session_id, content="graph step")
    engine = _DecisionEngine("stop")
    monkeypatch.setattr(graph_module, "_timeout_engine", lambda _cfg: engine)
    result = await graph_module.run_task_watchdog(
        _Tracker(),
        check_interval=0.01,
        stall_timeout=0.0,
        max_timeout=0.01,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: {
            "session_id": session_id,
            "_todo_session_id": session_id,
            "run_id": "p8-graph-run",
            "subject_id": "task-1",
            "task_hint": "graph",
        },
    )
    assert result == "max_time"
    assert "graph step" in engine.calls[0].progress


async def test_executor_node_factory_does_not_read_anonymous_graph_bucket(
    isolated_runtime, monkeypatch
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.core import graph as graph_module
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

    _write_todo("graph", content="poison from anonymous bucket")
    root = TaskNode(id="goal", title="goal", children_ids=["leaf"])
    leaf = TaskNode(
        id="leaf", title="leaf", parent_id="goal", status=TaskStatus.RUNNING
    )
    tree = TaskTree(goal_id="goal", nodes={"goal": root, "leaf": leaf})
    engine = _DecisionEngine("stop")

    class _Memory:
        async def get_task_context(self, *_args, **_kwargs):
            return ""

    class _HangingExecutor:
        def __init__(self, *_args, **_kwargs):
            self._llm = SimpleNamespace()

        async def execute_with_evidence(self, *_args, **_kwargs):
            await asyncio.Event().wait()

    monkeypatch.setattr(graph_module, "_timeout_engine", lambda _cfg: engine)
    monkeypatch.setattr(
        graph_module, "resolve_graph_watch_clocks", lambda _cfg: (0.0, 0.01, 0.01)
    )
    monkeypatch.setattr(graph_module._settings, "load_config", lambda: {})
    monkeypatch.setattr(graph_module._executor_module, "Executor", _HangingExecutor)
    state = {
        "session_id": "",
        "task_tree": tree,
        "_llm": SimpleNamespace(),
        "_memory": _Memory(),
        "_tool_orchestrator": None,
        "_tui": None,
        "parallel_tasks": [],
        "current_task_id": "leaf",
        "execution_results": [],
    }

    await graph_module.executor_node(state)

    assert engine.calls
    assert engine.calls[0].progress == ""


async def test_generic_graph_evidence_preserves_non_todo_progress(
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0.core import graph as graph_module

    engine = _DecisionEngine("stop")
    monkeypatch.setattr(graph_module, "_timeout_engine", lambda _cfg: engine)
    result = await graph_module.run_task_watchdog(
        _Tracker(),
        check_interval=0.01,
        stall_timeout=0.0,
        max_timeout=0.01,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: {
            "session_id": "",
            "run_id": "generic-run",
            "subject_id": "generic-task",
            "progress": "tool-side progress",
        },
    )

    assert result == "max_time"
    assert engine.calls[0].progress == "tool-side progress"


async def test_tool_timeout_evidence_reads_snapshot_from_real_orchestrator(
    isolated_runtime,
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    session_id = "p8-tool"
    _write_todo(session_id, content="tool step")
    engine = _DecisionEngine("stop")
    orchestrator = ToolOrchestrator(timeout_engine=engine)
    orchestrator._owner_agent = SimpleNamespace(_session_id=session_id)
    release = asyncio.Event()

    async def invoke():
        await release.wait()

    try:
        with pytest.raises(asyncio.TimeoutError):
            await orchestrator._await_tool_with_decision(
                invoke,
                SimpleNamespace(),
                "p8-tool-call",
                {},
                0.01,
                "call-1",
            )
    finally:
        orchestrator.shutdown_sync_executor(wait=True)
    assert "tool step" in engine.calls[0].progress


async def test_appserver_stall_evidence_reads_snapshot_after_consumer_rebuild(
    isolated_runtime, monkeypatch
):
    del isolated_runtime
    from RxyCode.RxyCode1_1_0.core import timeout_decision as decision_module
    from RxyCode.RxyCode1_1_0.appserver.server import AppServer
    from RxyCode.RxyCode1_1_0.appserver.watchdog import ActiveJob

    session_id = "p8-stall"
    _write_todo(session_id, content="stall step")
    engine = _DecisionEngine("continue")
    server = AppServer(stub=True)
    server._timeout_engine = engine
    server._timeout_section_cache = {
        "enabled": True,
        "restart_grant_base_seconds": 900.0,
        "max_restarts": 2,
        "restart_total_wall_seconds": 7200.0,
    }
    job = ActiveJob(
        session_id=session_id,
        job_id="job-1",
        started_at=time.monotonic() - 2.0,
    )
    server._job_prompts[job.job_id] = {"text": "stall"}
    assert await server._stall_decision_hook({"job": job, "reason": "dead"}) == "continue"
    assert "stall step" in engine.calls[0].progress

    _write_todo(session_id, content="stall resumed")
    engine2 = _DecisionEngine("continue")
    server2 = AppServer(stub=True)
    server2._timeout_engine = engine2
    server2._timeout_section_cache = server._timeout_section_cache
    job2 = ActiveJob(
        session_id=session_id,
        job_id="job-2",
        started_at=time.monotonic() - 2.0,
    )
    server2._job_prompts[job2.job_id] = {"text": "stall resumed"}
    assert await server2._stall_decision_hook({"job": job2, "reason": "dead"}) == "continue"
    assert "stall resumed" in engine2.calls[0].progress
    assert "stall step" not in engine2.calls[0].progress

    captured = []
    original_event_from_decision = decision_module.event_from_decision

    def capture_event(response, evidence, **kwargs):
        captured.append(evidence)
        return original_event_from_decision(response, evidence, **kwargs)

    async def capture_model(_event):
        return None

    monkeypatch.setattr(decision_module, "event_from_decision", capture_event)
    server2._emit_model = capture_model
    await server2._emit_restart_interrupt_stop(job2)
    assert captured and "stall resumed" in captured[0].progress
