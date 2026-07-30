"""
Tests for parallel execution support in core/graph.py.

Covers:
- route_next serial mode (default, parallel_enabled=False)
- route_next parallel mode (parallel_enabled=True sets parallel_tasks)
- executor_node parallel execution (mock LLM, asyncio.gather)
- executor_node serial fallback (parallel_tasks empty)
- max_parallel limit caps dispatched tasks
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree_with_independent_leaves(n: int = 3):
    """Create a TaskTree with *n* independent PENDING leaf tasks (no deps)."""
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree

    root = TaskNode(title="goal", description="g", id="goal-1")
    tree = TaskTree(goal_id="goal-1")
    tree.nodes[root.id] = root

    leaves = []
    for i in range(n):
        leaf = TaskNode(
            title=f"task-{i}",
            description=f"desc-{i}",
            id=f"leaf-{i}",
            parent_id=root.id,
            depth=1,
        )
        tree.nodes[leaf.id] = leaf
        root.children_ids.append(leaf.id)
        leaves.append(leaf)

    return tree, leaves


def _mock_memory():
    """Create a mock MemoryManager with async methods."""
    memory = MagicMock()
    memory.get_task_context = AsyncMock(return_value="ctx")
    memory.get_context = AsyncMock(return_value="")
    memory.store_execution = AsyncMock()
    memory.store_plan_experience = AsyncMock()
    memory.log_error = AsyncMock()
    memory.compress_if_needed = AsyncMock(return_value="")
    return memory


def _make_state(tree, parallel_tasks=None, current_task_id=None):
    """Build a minimal AgentState dict for route_next / executor_node tests."""
    llm = MagicMock()
    state = {
        "user_input": "test",
        "session_id": "sess-1",
        "task_tree": tree,
        "memory_context": "",
        "conversation_history": [],
        "current_task_id": current_task_id,
        "execution_results": [],
        "parallel_tasks": parallel_tasks or [],
        "final_response": None,
        "phase": "executing",
        "error": None,
        "_llm": llm,
        "_memory": _mock_memory(),
        "_tool_orchestrator": None,
        "_tui": None,
    }
    return state


def _config_patch(parallel_enabled=False, max_parallel=3):
    """Context manager that patches load_config with given execution settings."""
    return patch(
        "RxyCode.RxyCode1_1_0.config.settings.load_config",
        return_value={
            "execution": {
                "parallel_enabled": parallel_enabled,
                "max_parallel": max_parallel,
            }
        },
    )


def _executor_patch():
    """Patch Executor so each instance returns a unique result per task.

    The mock's ``execute_with_evidence`` method returns the task result and
    an empty evidence list.
    """
    mock_instance = MagicMock()
    mock_instance._llm = MagicMock()
    mock_instance.execute_with_evidence = AsyncMock(
        side_effect=lambda task, task_ctx="": (f"result-{task.id}", [])
    )
    return patch(
        "RxyCode.RxyCode1_1_0.execution.executor.Executor",
        return_value=mock_instance,
    )


# ---------------------------------------------------------------------------
# route_next tests
# ---------------------------------------------------------------------------

class TestRouteNextSerial:
    """Default (parallel_enabled=False): route_next picks ready[0], no parallel."""

    def test_serial_picks_first_ready(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        tree, leaves = _make_tree_with_independent_leaves(3)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=False):
            result = route_next(state)

        assert result == "execute"
        assert state["current_task_id"] == leaves[0].id
        assert state["parallel_tasks"] == []

    def test_serial_single_ready_task(self):
        """Even with parallel_enabled=True, a single ready task stays serial."""
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        tree, leaves = _make_tree_with_independent_leaves(1)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=True):
            result = route_next(state)

        assert result == "execute"
        assert state["current_task_id"] == leaves[0].id
        assert state["parallel_tasks"] == []


class TestRouteNextParallel:
    """parallel_enabled=True with multiple ready tasks sets parallel_tasks."""

    def test_parallel_sets_multiple_task_ids(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(3)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=True, max_parallel=3):
            result = route_next(state)

        assert result == "execute"
        assert len(state["parallel_tasks"]) == 3
        assert state["current_task_id"] == leaves[0].id
        # All ready tasks marked RUNNING
        for leaf in leaves:
            assert leaf.status == TaskStatus.RUNNING

    def test_parallel_respects_max_parallel(self):
        """If max_parallel=2 and 3 ready tasks, only 2 are dispatched."""
        from RxyCode.RxyCode1_1_0.core.graph import route_next
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(3)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=True, max_parallel=2):
            result = route_next(state)

        assert result == "execute"
        assert state["parallel_tasks"] == [leaves[0].id, leaves[1].id]
        assert leaves[0].status == TaskStatus.RUNNING
        assert leaves[1].status == TaskStatus.RUNNING
        assert leaves[2].status == TaskStatus.PENDING

    def test_explicit_parallel_request_overrides_default_off_but_keeps_cap(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        tree, leaves = _make_tree_with_independent_leaves(4)
        state = _make_state(tree)
        state["parallel_requested"] = True
        with _config_patch(parallel_enabled=False, max_parallel=2):
            result = route_next(state)

        assert result == "execute"
        assert state["parallel_tasks"] == [leaves[0].id, leaves[1].id]


# ---------------------------------------------------------------------------
# executor_node tests
# ---------------------------------------------------------------------------

class TestExecutorParallel:
    """executor_node with parallel_tasks > 1 runs all tasks via gather."""

    @pytest.mark.asyncio
    async def test_executor_parallel_executes_all(self):
        """When parallel_tasks has 2 IDs, both tasks are executed and results merged."""
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(2)
        # Mark tasks as RUNNING (route_next would do this)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING

        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id, leaves[1].id],
            current_task_id=leaves[0].id,
        )

        with _config_patch(parallel_enabled=True, max_parallel=3), \
             _executor_patch():
            result = await executor_node(state)

        # Results merged into execution_results
        er = result["execution_results"]
        assert len(er) == 2
        task_ids_in_results = {r["task_id"] for r in er}
        assert task_ids_in_results == {leaves[0].id, leaves[1].id}
        # Each result matches its task
        for r in er:
            assert r["result"] == f"result-{r['task_id']}"

    @pytest.mark.asyncio
    async def test_each_parallel_task_emits_its_own_lifecycle_hooks(self):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING
        state = _make_state(
            tree,
            parallel_tasks=[leaf.id for leaf in leaves],
            current_task_id=leaves[0].id,
        )
        hooks = HookRegistry()
        seen = []
        hooks.register("before", lambda context: seen.append(
            (context.phase.value, context.subject, context.payload["task_id"])
        ))
        hooks.register("after", lambda context: seen.append(
            (context.phase.value, context.subject, context.payload["task_id"])
        ))
        state["_hooks"] = hooks
        state["_hook_audit"] = []

        with _config_patch(parallel_enabled=True, max_parallel=2), \
             _executor_patch():
            await executor_node(state)

        task_events = [item for item in seen if item[1] == "task"]
        assert sorted(task_events) == sorted(
            [("before", "task", leaf.id) for leaf in leaves]
            + [("after", "task", leaf.id) for leaf in leaves]
        )
        assert all(item["subject"] == "task" for item in state["_hook_audit"])

    @pytest.mark.asyncio
    async def test_caught_executor_failure_emits_task_error_hook(self):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        leaves[0].status = TaskStatus.RUNNING
        state = _make_state(tree, current_task_id=leaves[0].id)
        hooks = HookRegistry()
        seen = []
        hooks.register("error", lambda context: seen.append(context))
        state["_hooks"] = hooks
        state["_hook_audit"] = []
        executor = MagicMock()
        executor._llm = MagicMock()
        executor.execute_with_evidence = AsyncMock(side_effect=RuntimeError("boom"))

        with _config_patch(), patch(
            "RxyCode.RxyCode1_1_0.execution.executor.Executor",
            return_value=executor,
        ):
            update = await executor_node(state)

        assert update["execution_results"][0]["result"].startswith(
            "[Executor error] RuntimeError: boom"
        )
        assert len(seen) == 1
        assert seen[0].subject == "task"
        assert seen[0].payload["status"] == "failed"

    @pytest.mark.asyncio
    async def test_executor_ignores_stale_parallel_task_ids(self):
        """Only RUNNING tasks belong to the current dispatch batch."""
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(2)
        leaves[0].status = TaskStatus.RUNNING

        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id, leaves[1].id, "nonexistent-id"],
            current_task_id=leaves[1].id,
        )

        with _config_patch(parallel_enabled=True, max_parallel=3), \
             _executor_patch():
            result = await executor_node(state)

        er = result["execution_results"]
        assert [item["task_id"] for item in er] == [leaves[0].id]
        assert result["current_task_id"] == leaves[0].id
        assert result["parallel_tasks"] == []

    @pytest.mark.asyncio
    async def test_executor_recovers_parallel_dispatch_from_running_tree(self):
        """Router-only scalar mutations may be absent from LangGraph state."""
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING
        state = _make_state(tree, parallel_tasks=[], current_task_id=None)

        with _config_patch(parallel_enabled=True, max_parallel=3), \
             _executor_patch():
            result = await executor_node(state)

        assert [item["task_id"] for item in result["execution_results"]] == [
            leaves[0].id,
            leaves[1].id,
        ]
        assert result["current_task_id"] == leaves[0].id
        assert result["parallel_tasks"] == [leaves[0].id, leaves[1].id]


class TestParallelValidation:
    """Every dispatched task is validated and persisted independently."""

    @pytest.mark.asyncio
    async def test_mixed_parallel_batch_validates_every_task(self):
        from RxyCode.RxyCode1_1_0.core.graph import (
            route_after_validator,
            validator_node,
        )
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING
            leaf.result = f"result-{leaf.id}"
            leaf.evidence = [{"tool": "read", "status": "succeeded"}]
        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id, leaves[1].id],
            current_task_id=leaves[0].id,
        )
        validator = MagicMock()
        validator.validate = AsyncMock(side_effect=[
            ValidationResult(
                passed=True,
                completeness_score=1,
                relevance_score=1,
                format_score=1,
            ),
            ValidationResult(passed=False, issues=["second task failed"]),
        ])

        with patch(
            "RxyCode.RxyCode1_1_0.validation.validator.Validator",
            return_value=validator,
        ):
            update = await validator_node(state)

        assert validator.validate.await_count == 2
        assert validator.validate.await_args_list[0].kwargs["result"] == "result-leaf-0"
        assert validator.validate.await_args_list[1].kwargs["result"] == "result-leaf-1"
        assert leaves[0].status == TaskStatus.PASSED
        assert leaves[1].status == TaskStatus.FAILED
        state["_memory"].store_execution.assert_awaited_once_with(
            "sess-1", leaves[0].id, "result-leaf-0"
        )
        state["_memory"].log_error.assert_awaited_once()
        assert update["parallel_tasks"] == []
        assert update["current_task_id"] == leaves[1].id

        routed_state = dict(state)
        routed_state.update(update)
        assert route_after_validator(routed_state) == "reflect"

    @pytest.mark.asyncio
    async def test_all_passing_parallel_batch_stores_every_result_and_clears_batch(self):
        from RxyCode.RxyCode1_1_0.core.graph import (
            route_after_validator,
            validator_node,
        )
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING
            leaf.result = f"result-{leaf.id}"
        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id, leaves[1].id],
            current_task_id=leaves[0].id,
        )
        passed = ValidationResult(
            passed=True,
            completeness_score=1,
            relevance_score=1,
            format_score=1,
        )
        validator = MagicMock()
        validator.validate = AsyncMock(side_effect=[passed, passed.model_copy()])

        with patch(
            "RxyCode.RxyCode1_1_0.validation.validator.Validator",
            return_value=validator,
        ):
            update = await validator_node(state)

        assert [leaf.status for leaf in leaves] == [
            TaskStatus.PASSED,
            TaskStatus.PASSED,
        ]
        assert state["_memory"].store_execution.await_count == 2
        assert update["parallel_tasks"] == []
        routed_state = dict(state)
        routed_state.update(update)
        assert route_after_validator(routed_state) == "synthesize"

    @pytest.mark.asyncio
    async def test_validator_node_rejects_unverified_side_effect_before_llm(self):
        from RxyCode.RxyCode1_1_0.core.graph import validator_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        task = leaves[0]
        task.status = TaskStatus.RUNNING
        task.title = "Create output file"
        task.description = "Write the requested content to output.txt"
        task.requirement = "output.txt exists"
        task.result = "Created output.txt"
        task.tools_hint = ["write"]
        state = _make_state(tree, current_task_id=task.id)
        state["_llm"].ainvoke = AsyncMock()

        update = await validator_node(state)

        assert task.status == TaskStatus.FAILED
        assert update["current_task_id"] == task.id
        assert any(
            "prose alone" in issue
            for issue in task.validation_result["issues"]
        )
        state["_llm"].ainvoke.assert_not_awaited()
        state["_memory"].store_execution.assert_not_awaited()
        state["_memory"].log_error.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_watchdog_does_not_stop_controlled_task_after_600_seconds(
        self,
    ):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        task = leaves[0]
        task.status = TaskStatus.RUNNING
        state = _make_state(tree, current_task_id=task.id)
        release = __import__("asyncio").Event()

        class ProgressTui:
            def write_progress(self, message):
                if "Working... 601s" in message:
                    release.set()

        async def controlled_execution(*_args, **_kwargs):
            await release.wait()
            return "controlled task completed", []

        executor = MagicMock()
        executor._llm = state["_llm"]
        executor.execute_with_evidence = AsyncMock(
            side_effect=controlled_execution
        )
        state["_tui"] = ProgressTui()
        clock_values = iter((0.0, 0.0, 601.0, 601.0))

        def virtual_time():
            return next(clock_values, 601.0)

        with (
            patch(
                "RxyCode.RxyCode1_1_0.config.settings.load_config",
                return_value={
                    "execution": {
                        "task_stall_timeout_seconds": 0,
                        "task_max_time_seconds": 7200,
                        "heartbeat_interval_seconds": 0.1,
                    }
                },
            ),
            patch(
                "RxyCode.RxyCode1_1_0.execution.executor.Executor",
                return_value=executor,
            ),
            patch("time.time", side_effect=virtual_time),
        ):
            update = await executor_node(state)

        assert update["execution_results"] == [
            {"task_id": task.id, "result": "controlled task completed"}
        ]
        assert task.result == "controlled task completed"

    @pytest.mark.asyncio
    async def test_validation_exception_is_isolated_to_one_parallel_task(self):
        from RxyCode.RxyCode1_1_0.core.graph import validator_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.RUNNING
            leaf.result = f"result-{leaf.id}"
        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id, leaves[1].id],
            current_task_id=leaves[0].id,
        )
        validator = MagicMock()
        validator.validate = AsyncMock(side_effect=[
            RuntimeError("validator unavailable"),
            ValidationResult(
                passed=True,
                completeness_score=1,
                relevance_score=1,
                format_score=1,
            ),
        ])

        with patch(
            "RxyCode.RxyCode1_1_0.validation.validator.Validator",
            return_value=validator,
        ):
            update = await validator_node(state)

        assert validator.validate.await_count == 2
        assert leaves[0].status == TaskStatus.FAILED
        assert "validator unavailable" in str(leaves[0].validation_result)
        assert leaves[1].status == TaskStatus.PASSED
        assert update["parallel_tasks"] == []
        assert update["current_task_id"] == leaves[0].id

    @pytest.mark.asyncio
    async def test_replanner_processes_every_failed_parallel_task(self):
        from RxyCode.RxyCode1_1_0.core.graph import re_planner_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(2)
        for leaf in leaves:
            leaf.status = TaskStatus.FAILED
        state = _make_state(
            tree,
            parallel_tasks=[],
            current_task_id=leaves[0].id,
        )
        replanner = MagicMock()
        replanner.replan = AsyncMock(return_value=True)

        with patch(
            "RxyCode.RxyCode1_1_0.validation.re_planner.RePlanner",
            return_value=replanner,
        ):
            update = await re_planner_node(state)

        assert [call.args[1] for call in replanner.replan.await_args_list] == [
            leaves[0].id,
            leaves[1].id,
        ]
        assert update["parallel_tasks"] == []


class TestExecutorSerialFallback:
    """When parallel_tasks is empty or has 1 item, serial path is used."""

    @pytest.mark.asyncio
    async def test_empty_parallel_tasks_uses_serial(self):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        leaves[0].status = TaskStatus.RUNNING

        state = _make_state(
            tree,
            parallel_tasks=[],
            current_task_id=leaves[0].id,
        )

        with _config_patch(parallel_enabled=False), \
             _executor_patch():
            result = await executor_node(state)

        er = result["execution_results"]
        assert len(er) == 1
        assert er[0]["task_id"] == leaves[0].id
        assert er[0]["result"] == f"result-{leaves[0].id}"

    @pytest.mark.asyncio
    async def test_executor_recovers_serial_dispatch_from_running_tree(self):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        leaves[0].status = TaskStatus.RUNNING
        state = _make_state(tree, parallel_tasks=[], current_task_id=None)

        with _config_patch(parallel_enabled=False), \
             _executor_patch():
            result = await executor_node(state)

        assert result["execution_results"][0]["task_id"] == leaves[0].id
        assert result["current_task_id"] == leaves[0].id
        assert result["parallel_tasks"] == []

    @pytest.mark.asyncio
    async def test_single_parallel_task_uses_serial(self):
        """A single-item parallel_tasks list also falls through to serial."""
        from RxyCode.RxyCode1_1_0.core.graph import executor_node
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus

        tree, leaves = _make_tree_with_independent_leaves(1)
        leaves[0].status = TaskStatus.RUNNING

        state = _make_state(
            tree,
            parallel_tasks=[leaves[0].id],
            current_task_id=leaves[0].id,
        )

        with _config_patch(parallel_enabled=False), \
             _executor_patch():
            result = await executor_node(state)

        er = result["execution_results"]
        assert len(er) == 1
        assert er[0]["task_id"] == leaves[0].id

    @pytest.mark.asyncio
    async def test_serial_task_not_found(self):
        from RxyCode.RxyCode1_1_0.core.graph import executor_node

        tree, _ = _make_tree_with_independent_leaves(0)
        state = _make_state(
            tree,
            parallel_tasks=[],
            current_task_id="missing-id",
        )

        with _config_patch(parallel_enabled=False):
            result = await executor_node(state)

        assert "error" in result
        assert "missing-id" in result["error"]


# ---------------------------------------------------------------------------
# max_parallel limit test
# ---------------------------------------------------------------------------

class TestMaxParallelLimit:
    """route_next caps parallel_tasks at max_parallel."""

    def test_five_ready_max_two_dispatches_two(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        tree, leaves = _make_tree_with_independent_leaves(5)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=True, max_parallel=2):
            result = route_next(state)

        assert result == "execute"
        assert len(state["parallel_tasks"]) == 2

    def test_three_ready_max_three_dispatches_three(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        tree, leaves = _make_tree_with_independent_leaves(3)
        state = _make_state(tree)
        with _config_patch(parallel_enabled=True, max_parallel=3):
            result = route_next(state)

        assert result == "execute"
        assert len(state["parallel_tasks"]) == 3
