from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _failed_state(*, issue: str, result: str = "attempt failed"):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

    root = TaskNode(id="root", title="goal")
    leaf = TaskNode(
        id="leaf",
        title="do work",
        description="perform the requested change",
        requirement="verified result",
        parent_id="root",
        depth=1,
        status=TaskStatus.FAILED,
        result=result,
        validation_result={"passed": False, "issues": [issue]},
    )
    root.children_ids = [leaf.id]
    tree = TaskTree(goal_id=root.id, nodes={root.id: root, leaf.id: leaf})
    memory = MagicMock()
    memory.log_error = AsyncMock()
    memory.store_execution = AsyncMock()
    memory.store_plan_experience = AsyncMock()
    return {
        "user_input": "do it",
        "session_id": "session-1",
        "task_tree": tree,
        "memory_context": "",
        "conversation_history": [],
        "current_task_id": leaf.id,
        "execution_results": [],
        "parallel_tasks": [],
        "parallel_requested": False,
        "final_response": None,
        "phase": "reflecting",
        "error": None,
        "reflections": [],
        "failure_attribution": {},
        "_llm": MagicMock(),
        "_memory": memory,
        "_tool_orchestrator": None,
        "_tui": None,
        "_tracer": None,
    }, leaf


@pytest.mark.asyncio
async def test_reflection_node_classifies_tool_failure_and_drives_retry():
    from RxyCode.RxyCode1_1_0.core.graph import (
        reflection_node,
        route_after_reflection,
    )

    state, leaf = _failed_state(issue="Tool timeout: bash did not complete")
    leaf.evidence = [{"tool": "bash", "status": "failed", "executed": True}]

    update = await reflection_node(state)
    state.update(update)

    assert leaf.reflections[-1]["failure_type"] == "tool_error"
    assert leaf.reflections[-1]["action"] == "retry"
    assert state["failure_attribution"] == {"tool_error": 1}
    assert route_after_reflection(state) == "error"
    assert state["error"]


@pytest.mark.asyncio
async def test_reflection_node_persists_failure_for_a_later_run(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "memory:\n  experience_cross_session: false\n",
        encoding="utf-8",
    )
    from RxyCode.RxyCode1_1_0.core.graph import reflection_node
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    state, leaf = _failed_state(
        issue="Tool timeout while running Redis database migration"
    )
    leaf.title = "Recover Redis database migration"
    leaf.requirement = "Rollback safely after timeout"
    leaf.evidence = [{"tool": "bash", "status": "failed", "executed": True}]
    state["_memory"] = MemoryManager(session_id="session-1")

    await reflection_node(state)

    restarted = MemoryManager(session_id="session-1")
    context = await restarted.get_context(
        "session-1",
        "Redis database migration rollback timeout",
    )
    assert "plan_reflection" in context
    assert '"failure_type":"tool_error"' in context
    assert "Do not treat optimistic model prose" in context


@pytest.mark.asyncio
async def test_ambiguous_reflection_uses_registered_structured_prompt():
    from RxyCode.RxyCode1_1_0.validation.reflection import Reflector

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=SimpleNamespace(
            content=(
                '{"failure_type":"reasoning_error","reason":"wrong approach",'
                '"action":"replan","corrective_action":"choose another approach",'
                '"verification_steps":["rerun tests"],"lessons":["inspect first"]}'
            )
        )
    )
    state, task = _failed_state(issue="The answer is incomplete")

    result = await Reflector(llm).reflect(task)

    assert result.failure_type == "reasoning_error"
    assert result.action == "replan"
    assert result.verification_steps == ["rerun tests"]
    prompt = llm.ainvoke.await_args.args[0][-1].content
    assert "Reflection stage" in prompt
    assert "The answer is incomplete" in prompt


@pytest.mark.asyncio
async def test_final_verifier_replaces_optimistic_claim_for_cancelled_work():
    from RxyCode.RxyCode1_1_0.core.graph import final_verifier_node
    from RxyCode.RxyCode1_1_0.core.state import TaskStatus

    state, leaf = _failed_state(issue="retry budget exhausted")
    leaf.status = TaskStatus.CANCELLED
    state["final_response"] = "Everything completed successfully."

    update = await final_verifier_node(state)

    assert update["phase"] == "done"
    assert update["final_verification"]["passed"] is False
    assert "构建流程未完成" in update["final_response"] or "校验" in update["final_response"]
    assert "Synthesizer" not in update["final_response"]
    state["_memory"].store_execution.assert_not_awaited()
    state["_memory"].store_plan_experience.assert_not_awaited()


def test_validator_failure_routes_through_reflection_before_replanning():
    from RxyCode.RxyCode1_1_0.core.graph import route_after_validator

    state, _ = _failed_state(issue="acceptance criteria were incomplete")

    assert route_after_validator(state) == "reflect"
