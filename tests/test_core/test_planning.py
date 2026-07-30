"""
Tests for planning/decomposer.py and planning/goal_planner.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSubTask:
    def test_create_subtask(self):
        from RxyCode.RxyCode1_1_0.planning.decomposer import SubTask
        task = SubTask(title="Test", description="A test task")
        assert task.title == "Test"
        assert task.description == "A test task"

    def test_subtask_has_title(self):
        from RxyCode.RxyCode1_1_0.planning.decomposer import SubTask
        task = SubTask(title="My Task")
        assert task.title == "My Task"


class TestSubTaskList:
    def test_empty_list(self):
        from RxyCode.RxyCode1_1_0.planning.decomposer import SubTaskList
        lst = SubTaskList(tasks=[])
        assert lst.tasks == []

    def test_add_task(self):
        from RxyCode.RxyCode1_1_0.planning.decomposer import SubTask, SubTaskList
        task = SubTask(title="Test")
        lst = SubTaskList(tasks=[task])
        assert len(lst.tasks) == 1


class TestHierarchicalDecomposer:
    def _make_decomposer(self):
        from RxyCode.RxyCode1_1_0.planning.decomposer import HierarchicalDecomposer
        mock_llm = MagicMock()
        return HierarchicalDecomposer(mock_llm)

    def test_init(self):
        dec = self._make_decomposer()
        assert dec is not None


class TestGoalPlanner:
    def _make_planner(self):
        from RxyCode.RxyCode1_1_0.planning.goal_planner import GoalPlanner
        mock_llm = MagicMock()
        return GoalPlanner(mock_llm)

    def test_init(self):
        planner = self._make_planner()
        assert planner is not None

    @pytest.mark.asyncio
    async def test_plan_repairs_invalid_json_and_preserves_nested_braces(self):
        from RxyCode.RxyCode1_1_0.planning.goal_planner import GoalPlanner

        llm = MagicMock()
        first = MagicMock()
        first.content = '{"goal": 42}'
        repaired = MagicMock()
        repaired.content = (
            '```json\n{"goal":"Build {safe} parser",'
            '"constraints":["keep {nested} literals"],"output_format":"code"}\n```'
        )
        llm.ainvoke = AsyncMock(side_effect=[first, repaired])

        result, tree = await GoalPlanner(llm).plan("build it")

        assert result.goal == "Build {safe} parser"
        assert tree.constraints == ["keep {nested} literals"]
        assert llm.ainvoke.await_count == 2
