"""Tests for RePlanner: secondary decomposition of failed tasks."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree, TaskStatus
from RxyCode.RxyCode1_1_0.validation.re_planner import RePlanner


def _make_mock_llm(sub_tasks: list[dict]):
    import json

    llm = MagicMock()

    async def _ainvoke(messages):
        resp = MagicMock()
        resp.content = json.dumps(sub_tasks)
        return resp

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)
    return llm


class TestRePlanner:
    def test_plan_budget_configuration_is_validated(self):
        llm = MagicMock()

        with pytest.raises(ValueError, match="max_depth"):
            RePlanner(llm, max_depth=-1)
        with pytest.raises(ValueError, match="max_nodes"):
            RePlanner(llm, max_nodes=0)

    @pytest.mark.asyncio
    async def test_invalid_response_gets_one_repair_attempt(self):
        llm = MagicMock()
        responses = [
            '[{"title": 123}]',
            '[{"title": "Recovered", "is_atomic": true}]',
        ]

        async def _ainvoke(_messages):
            response = MagicMock()
            response.content = responses.pop(0)
            return response

        llm.ainvoke = AsyncMock(side_effect=_ainvoke)
        failed = TaskNode(id="f1", title="Failed", status=TaskStatus.FAILED)
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        assert await RePlanner(llm).replan(tree, "f1") is True
        assert tree.get_children("f1")[0].is_atomic is True
        assert llm.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_basic_replan(self):
        """A failed task should be decomposed into sub-tasks."""
        sub_tasks = [
            {
                "title": "Fix step 1",
                "description": "Fix the first part",
                "effect": "write",
            },
            {"title": "Fix step 2", "description": "Fix the second part"},
        ]
        llm = _make_mock_llm(sub_tasks)
        replanner = RePlanner(llm, max_retries=3)

        root = TaskNode(id="root", title="Root", depth=0)
        failed = TaskNode(
            id="f1", title="Failed Task", depth=1, parent_id="root",
            status=TaskStatus.FAILED,
            validation_result={"issues": ["incomplete"], "suggestion": "break it down"},
        )
        root.children_ids = ["f1"]
        tree = TaskTree(goal_id="root", nodes={"root": root, "f1": failed})

        result = await replanner.replan(tree, "f1")
        assert result is True

        # Failed task should now have children
        assert len(failed.children_ids) == 2
        assert failed.status == TaskStatus.RE_PLANNING
        assert failed.retry_count == 1
        assert tree.get_children(failed.id)[0].effect == "write"

    @pytest.mark.asyncio
    async def test_max_retries_cancels(self):
        """After max_retries, the task should be CANCELLED."""
        llm = _make_mock_llm([])
        replanner = RePlanner(llm, max_retries=2)

        failed = TaskNode(
            id="f1", title="Failed", depth=0,
            status=TaskStatus.FAILED, retry_count=2,
        )
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        result = await replanner.replan(tree, "f1")
        assert result is False
        assert failed.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_replan_with_dependencies(self):
        """Sub-tasks from re-planning should resolve dependencies by index."""
        sub_tasks = [
            {"title": "Step A", "description": "First"},
            {"title": "Step B", "description": "Second", "depends_on_index": [0]},
        ]
        llm = _make_mock_llm(sub_tasks)
        replanner = RePlanner(llm, max_retries=3)

        failed = TaskNode(id="f1", title="Failed", depth=0, status=TaskStatus.FAILED)
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        await replanner.replan(tree, "f1")

        children = tree.get_children("f1")
        assert len(children) == 2
        step_b = next(c for c in children if c.title == "Step B")
        assert len(step_b.dependent_tasks) == 1

    @pytest.mark.asyncio
    async def test_no_sub_tasks_marks_pending(self):
        """If LLM returns no sub-tasks, mark as PENDING for retry."""
        llm = _make_mock_llm([])
        replanner = RePlanner(llm, max_retries=3)

        failed = TaskNode(id="f1", title="Failed", depth=0, status=TaskStatus.FAILED)
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        result = await replanner.replan(tree, "f1")
        assert result is True
        assert failed.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_depth_budget_cancels_without_calling_model(self):
        llm = _make_mock_llm([
            {"title": "must not be created", "is_atomic": True},
        ])
        failed = TaskNode(
            id="f1",
            title="Failed",
            depth=2,
            status=TaskStatus.FAILED,
        )
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        result = await RePlanner(llm, max_depth=2).replan(tree, "f1")

        assert result is False
        assert failed.status == TaskStatus.CANCELLED
        assert not failed.children_ids
        assert "budget" in failed.error_history[-1]
        llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_global_node_budget_preserves_dependency_closure(self):
        llm = _make_mock_llm([
            {"title": "Fits", "is_atomic": True},
            {
                "title": "Needs first",
                "depends_on_index": [0],
                "is_atomic": True,
            },
        ])
        root = TaskNode(id="root", title="Root")
        failed = TaskNode(
            id="f1",
            title="Failed",
            depth=1,
            parent_id="root",
            status=TaskStatus.FAILED,
        )
        root.children_ids = [failed.id]
        tree = TaskTree(
            goal_id=root.id,
            nodes={root.id: root, failed.id: failed},
        )

        result = await RePlanner(llm, max_nodes=3).replan(tree, failed.id)

        assert result is True
        assert len(tree.nodes) == 3
        assert [child.title for child in tree.get_children(failed.id)] == ["Fits"]
        tree.assert_valid_plan()

    @pytest.mark.asyncio
    async def test_exhausted_node_budget_fails_closed(self):
        llm = _make_mock_llm([
            {"title": "must not be created", "is_atomic": True},
        ])
        failed = TaskNode(id="f1", title="Failed", status=TaskStatus.FAILED)
        tree = TaskTree(goal_id="f1", nodes={"f1": failed})

        result = await RePlanner(llm, max_nodes=1).replan(tree, "f1")

        assert result is False
        assert failed.status == TaskStatus.CANCELLED
        assert len(tree.nodes) == 1
        llm.ainvoke.assert_not_awaited()

