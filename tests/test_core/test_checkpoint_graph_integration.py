"""Checkpoint wiring tests at real graph and AgentV2 boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _tree(status="pending"):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

    root = TaskNode(
        id="root",
        title="Root",
        status=TaskStatus(status),
    )
    return TaskTree(goal_id=root.id, nodes={root.id: root})


@pytest.mark.asyncio
async def test_observed_node_saves_before_and_after_and_seals_terminal_snapshot():
    from RxyCode.RxyCode1_1_0.core.graph import observed_node

    class Store:
        def __init__(self):
            self.saved = []
            self.completed = []

        def save(self, session_id, user_input, mode, state):
            self.saved.append((session_id, user_input, mode, state))
            return {"checkpoint_id": "checkpoint-1"}

        def mark_complete(self, checkpoint_id):
            self.completed.append(checkpoint_id)

    store = Store()
    state = {
        "session_id": "session-a",
        "user_input": "expanded prompt",
        "execution_results": [{"task_id": "old"}],
        "phase": "executing",
        "_checkpoint_store": store,
        "_checkpoint_key_input": "original request",
        "_checkpoint_mode": "build",
        "_tracer": None,
    }

    async def terminal_node(_state):
        return {
            "execution_results": [{"task_id": "new"}],
            "final_response": "done",
            "phase": "done",
        }

    update = await observed_node("terminal", terminal_node)(state)

    assert update["final_response"] == "done"
    assert len(store.saved) == 2
    assert store.saved[0][:3] == (
        "session-a",
        "original request",
        "build",
    )
    assert store.saved[1][3]["execution_results"] == [
        {"task_id": "old"},
        {"task_id": "new"},
    ]
    assert store.completed == ["checkpoint-1"]


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("planned", "decompose"),
        ("validating", "validate"),
        ("reflecting", "reflect"),
        ("verifying", "final_verify"),
        ("done", "end"),
    ],
)
def test_route_entry_resumes_at_next_uncommitted_boundary(phase, expected):
    from RxyCode.RxyCode1_1_0.core.graph import route_entry

    state = {"task_tree": _tree(), "phase": phase}

    assert route_entry(state) == expected


def test_agent_hydrates_active_checkpoint_and_reinjects_runtime_dependencies(tmp_path):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.core.state import TaskTree

    store = CheckpointStore(tmp_path)
    state = {
        "session_id": "session-a",
        "user_input": "request",
        "task_tree": _tree(),
        "execution_results": [],
        "parallel_tasks": [],
        "parallel_requested": False,
        "phase": "validating",
    }
    store.save("session-a", "request", "build", state)
    agent = object.__new__(AgentV2)
    agent._session_id = "session-a"
    agent._checkpoint_store = store
    agent._llm = MagicMock(name="llm")
    agent._memory = MagicMock(name="memory")
    agent._tool_orchestrator = MagicMock(name="tools")
    agent._tool_tracer = MagicMock(name="tracer")
    agent._hooks = MagicMock(name="hooks")
    agent._model_router = MagicMock(name="router")

    hydrated = agent._prepare_graph_state(
        {"session_id": "session-a", "user_input": "request", "task_tree": None},
        checkpoint_key_input="request",
        mode="build",
    )

    assert isinstance(hydrated["task_tree"], TaskTree)
    assert hydrated["phase"] == "validating"
    assert hydrated["_llm"] is agent._llm
    assert hydrated["_checkpoint_store"] is store


def test_agent_revalidates_checkpoint_plan_before_recovery(tmp_path):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.core.state import (
        PlanValidationError,
        TaskNode,
        TaskTree,
    )

    root = TaskNode(id="root", title="Root", children_ids=["task"])
    task = TaskNode(
        id="task",
        title="Task",
        parent_id="root",
        depth=1,
        dependent_tasks=["missing"],
    )
    store = CheckpointStore(tmp_path)
    store.save(
        "session-a",
        "request",
        "build",
        {
            "session_id": "session-a",
            "user_input": "request",
            "task_tree": TaskTree(
                goal_id="root", nodes={"root": root, "task": task}
            ),
            "phase": "executing",
        },
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "session-a"
    agent._checkpoint_store = store

    with pytest.raises(PlanValidationError, match="unknown dependency"):
        agent._prepare_graph_state(
            {"session_id": "session-a", "user_input": "request"},
            checkpoint_key_input="request",
            mode="build",
        )


@pytest.mark.asyncio
async def test_compiled_graph_resumes_verification_without_replanning(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import graph as graph_module

    planner = AsyncMock(side_effect=AssertionError("planner must not run"))
    monkeypatch.setattr(graph_module, "goal_planner_node", planner)
    graph = graph_module.build_graph()
    memory = SimpleNamespace(store_execution=AsyncMock())
    state = {
        "session_id": "session-a",
        "user_input": "request",
        "task_tree": _tree("cancelled"),
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
        "_llm": MagicMock(),
        "_memory": memory,
        "_tool_orchestrator": MagicMock(),
        "_tracer": None,
        "_tui": None,
        "_checkpoint_store": None,
        "_checkpoint_mode": "build",
        "_checkpoint_key_input": "request",
        "_hooks": None,
        "_model_router": None,
    }

    result = await graph.ainvoke(state, {"recursion_limit": 10})

    planner.assert_not_awaited()
    assert result["phase"] == "done"
    assert "构建流程未完成" in result["final_response"] or "校验" in result["final_response"]
    assert "Synthesizer" not in result["final_response"]


def test_default_config_has_bounded_graph_tool_and_checkpoint_controls():
    from RxyCode.RxyCode1_1_0.config.settings import _default_config

    cfg = _default_config()

    assert cfg["execution"]["max_graph_steps"] > 0
    assert cfg["execution"]["max_tool_rounds"] > 0
    assert cfg["execution"]["checkpoint_enabled"] is True
    assert cfg["execution"]["checkpoint_retention"] > 0
    assert cfg["execution"]["tool_journal_enabled"] is True
    assert cfg["execution"]["tool_journal_retention"] > 0
    assert cfg["execution"]["tool_journal_max_result_chars"] >= 1000
