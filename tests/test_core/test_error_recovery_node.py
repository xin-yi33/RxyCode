"""
Tests for core/graph.py error_recovery_node — the previously broken link.

Covers:
- node reads _memory / session_id from state (no NameError)
- "retry" decision: task reset to PENDING so route_next sends it back to executor
- "cancel" decision: task CANCELLED and scheduler cascade-cancel still works
- error cleared from state after handling
- errors logged via memory.log_error (not conversation memory)

LLM is mocked; no real model calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_state(with_task=True, error="boom"):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree, TaskStatus

    task = TaskNode(title="t1", description="d1")
    task.status = TaskStatus.RUNNING
    tree = TaskTree(goal_id=task.id)
    tree.nodes[task.id] = task

    memory = MagicMock()
    memory.log_error = AsyncMock()

    state = {
        "user_input": "do something",
        "session_id": "sess-1",
        "task_tree": tree,
        "memory_context": "",
        "conversation_history": [],
        "current_task_id": task.id if with_task else None,
        "execution_results": [],
        "final_response": None,
        "phase": "executing",
        "error": error,
        "_llm": MagicMock(),
        "_memory": memory,
        "_tool_orchestrator": None,
        "_tui": None,
    }
    return state, tree, task, memory


class TestErrorRecoveryNodeRetry:
    @pytest.mark.asyncio
    async def test_retry_path_resets_task_to_pending(self):
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        state, tree, task, memory = _make_state()
        # first error -> retry
        result = await error_recovery_node(state)

        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 1
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_retry_path_logs_error_to_memory(self):
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node

        state, tree, task, memory = _make_state(error="network glitch")
        await error_recovery_node(state)

        memory.log_error.assert_awaited_once_with("sess-1", task.id, "network glitch")

    @pytest.mark.asyncio
    async def test_retry_path_makes_task_ready_for_executor(self):
        """After retry, route_next must be able to pick the task up again."""
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node, route_next

        state, tree, task, memory = _make_state()
        result = await error_recovery_node(state)
        # Apply partial update like LangGraph would
        state.update(result)

        nxt = route_next(state)
        assert nxt == "execute"
        assert state["current_task_id"] == task.id


class TestErrorRecoveryNodeCancel:
    @pytest.mark.asyncio
    async def test_cancel_path_marks_task_cancelled(self):
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        state, tree, task, memory = _make_state()
        task.retry_count = task.max_retries  # exhaust retries
        result = await error_recovery_node(state)

        assert task.status == TaskStatus.CANCELLED
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_cancel_path_cascades_to_dependents(self):
        """CANCELLED task must cascade-cancel its dependents via scheduler."""
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        from RxyCode.RxyCode1_1_0.execution.scheduler import TaskScheduler

        state, tree, task, memory = _make_state()
        task.retry_count = task.max_retries

        dep = TaskNode(
            title="dep",
            description="depends on t1",
            parent_id=task.id,
            depth=task.depth + 1,
        )
        dep.dependent_tasks = [task.id]
        task.children_ids.append(dep.id)
        tree.nodes[dep.id] = dep

        await error_recovery_node(state)

        scheduler = TaskScheduler(tree)
        scheduler.get_ready_tasks()  # triggers cascade
        assert tree.nodes[dep.id].status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_path_tree_completes(self):
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node, route_next

        state, tree, task, memory = _make_state()
        task.retry_count = task.max_retries
        result = await error_recovery_node(state)
        state.update(result)

        # All leaves cancelled -> tree complete -> synthesize
        assert route_next(state) == "synthesize"


class TestErrorRecoveryNodeEdgeCases:
    @pytest.mark.asyncio
    async def test_no_current_task_does_not_raise(self):
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node

        state, tree, task, memory = _make_state(with_task=False)
        result = await error_recovery_node(state)
        assert result.get("error") is None
        memory.log_error.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_state_memory_and_session(self):
        """Node must pull _memory and session_id from state (regression: NameError)."""
        from RxyCode.RxyCode1_1_0.core.graph import error_recovery_node

        state, tree, task, memory = _make_state()
        # If the node referenced bare `memory`/`session_id` names this raises NameError
        result = await error_recovery_node(state)
        assert isinstance(result, dict)
