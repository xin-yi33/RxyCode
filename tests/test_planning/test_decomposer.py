"""Tests for the HierarchicalDecomposer (with mock LLM)."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree
from RxyCode.RxyCode1_1_0.planning.decomposer import HierarchicalDecomposer


def _make_mock_llm(sub_tasks: list[dict], recursive: bool = False):
    """Create a mock LLM that returns JSON sub-tasks via ainvoke (matches production code).

    If recursive=False (default), the LLM returns sub-tasks only on the first call
    and empty list on subsequent calls (so decomposition stops at depth 1).
    If recursive=True, it always returns the same sub-tasks (use with max_depth=1).
    """
    llm = MagicMock()
    call_count = {"n": 0}

    async def _ainvoke(messages):
        call_count["n"] += 1
        if call_count["n"] == 1 or recursive:
            tasks = sub_tasks
        else:
            tasks = []
        resp = MagicMock()
        resp.content = json.dumps(tasks)
        return resp

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)
    return llm


def _make_simple_tree() -> TaskTree:
    """Create a tree with just a root node."""
    root = TaskNode(id="root", title="Build a REST API", description="Build a user management API", depth=0)
    return TaskTree(goal_id="root", nodes={"root": root})


class TestHierarchicalDecomposer:
    @pytest.mark.asyncio
    async def test_balanced_json_and_repair_retry_are_used(self):
        llm = MagicMock()
        responses = [
            "The task list is: [{\"title\": 123}]",
            "```json\n[{\"title\": \"Fixed\", \"is_atomic\": true, "
            "\"description\": \"Contains [nested] text\"}]\n```",
        ]

        async def _ainvoke(_messages):
            resp = MagicMock()
            resp.content = responses.pop(0)
            return resp

        llm.ainvoke = AsyncMock(side_effect=_ainvoke)
        result = await HierarchicalDecomposer(llm).decompose(_make_simple_tree())

        assert [leaf.title for leaf in result.get_leaf_nodes()] == ["Fixed"]
        assert llm.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_atomic_children_are_not_recursively_decomposed(self):
        sub_tasks = [
            {"title": "Atomic", "description": "One tool call", "is_atomic": True},
            {"title": "Composite", "description": "Needs another split", "is_atomic": False},
        ]
        llm = _make_mock_llm(sub_tasks, recursive=True)

        result = await HierarchicalDecomposer(llm, max_depth=2).decompose(_make_simple_tree())

        atomic = result.find_by_title("Atomic")
        assert atomic is not None
        assert atomic.is_atomic is True
        assert atomic.children_ids == []
        assert len(result.nodes) == 5

    @pytest.mark.asyncio
    async def test_max_nodes_is_a_global_hard_budget(self):
        sub_tasks = [
            {"title": f"Task {index}", "description": "Split again"}
            for index in range(5)
        ]
        llm = _make_mock_llm(sub_tasks, recursive=True)

        result = await HierarchicalDecomposer(
            llm,
            max_depth=4,
            max_nodes=7,
        ).decompose(_make_simple_tree())

        assert len(result.nodes) == 7
        assert llm.ainvoke.await_count < 5**4

    @pytest.mark.asyncio
    async def test_budget_never_keeps_a_task_without_its_dependency(self):
        sub_tasks = [
            {"title": "Dependent", "depends_on_index": [1], "is_atomic": True},
            {"title": "Prerequisite", "is_atomic": True},
        ]
        llm = _make_mock_llm(sub_tasks)

        result = await HierarchicalDecomposer(
            llm,
            max_nodes=2,
        ).decompose(_make_simple_tree())

        leaves = result.get_leaf_nodes()
        assert [leaf.title for leaf in leaves] == ["Prerequisite"]
        assert leaves[0].dependent_tasks == []

    @pytest.mark.asyncio
    async def test_dependency_cycle_is_repaired_before_tree_mutation(self):
        llm = MagicMock()
        responses = [
            '[{"title":"A","depends_on_index":[1]},'
            '{"title":"B","depends_on_index":[0]}]',
            '[{"title":"Recovered","is_atomic":true}]',
        ]

        async def _ainvoke(_messages):
            response = MagicMock()
            response.content = responses.pop(0)
            return response

        llm.ainvoke = AsyncMock(side_effect=_ainvoke)

        result = await HierarchicalDecomposer(llm).decompose(_make_simple_tree())

        assert [leaf.title for leaf in result.get_leaf_nodes()] == ["Recovered"]
        assert llm.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_basic_decomposition(self):
        sub_tasks = [
            {"title": "Design schema", "description": "Design the database schema", "tools_hint": ["write"]},
            {"title": "Implement routes", "description": "Implement API routes", "tools_hint": ["write", "read"], "effect": "write"},
            {"title": "Write tests", "description": "Write unit tests", "tools_hint": ["write", "bash"]},
        ]
        llm = _make_mock_llm(sub_tasks)
        decomposer = HierarchicalDecomposer(llm, max_depth=4)

        tree = _make_simple_tree()
        result = await decomposer.decompose(tree)

        # Root should have 3 children
        root = result.get_root()
        assert len(root.children_ids) == 3

        # All children should be leaves (depth 1, no further decomposition because LLM returns empty for them)
        leaves = result.get_leaf_nodes()
        assert len(leaves) == 3
        routes = next(node for node in leaves if node.title == "Implement routes")
        assert routes.effect == "write"

    @pytest.mark.asyncio
    async def test_dependency_resolution(self):
        sub_tasks = [
            {"title": "Step 1", "description": "First step"},
            {"title": "Step 2", "description": "Depends on step 1", "depends_on_index": [0]},
            {"title": "Step 3", "description": "Depends on steps 1 and 2", "depends_on_index": [0, 1]},
        ]
        llm = _make_mock_llm(sub_tasks)
        decomposer = HierarchicalDecomposer(llm, max_depth=4)

        tree = _make_simple_tree()
        result = await decomposer.decompose(tree)

        leaves = result.get_leaf_nodes()
        # Find step 2 and step 3
        step2 = next(n for n in leaves if n.title == "Step 2")
        step3 = next(n for n in leaves if n.title == "Step 3")

        # Step 2 should depend on step 1
        assert len(step2.dependent_tasks) == 1
        # Step 3 should depend on step 1 and step 2
        assert len(step3.dependent_tasks) == 2

    @pytest.mark.asyncio
    async def test_no_decomposition_needed(self):
        """If LLM returns empty list, the node stays as-is."""
        llm = _make_mock_llm([])
        decomposer = HierarchicalDecomposer(llm, max_depth=4)

        tree = _make_simple_tree()
        result = await decomposer.decompose(tree)

        # Root should have no children
        assert len(result.get_root().children_ids) == 0

    @pytest.mark.asyncio
    async def test_max_depth_respected(self):
        """At max_depth, decomposition should stop."""
        sub_tasks = [{"title": "Sub", "description": "A sub-task"}]
        llm = _make_mock_llm(sub_tasks)
        decomposer = HierarchicalDecomposer(llm, max_depth=1)

        tree = _make_simple_tree()
        result = await decomposer.decompose(tree)

        # Root gets children at depth 1, but depth 1 == max_depth, so no further decomposition
        root = result.get_root()
        assert len(root.children_ids) == 1
        child = result.nodes[root.children_ids[0]]
        assert child.depth == 1
        assert len(child.children_ids) == 0  # not decomposed further

    @pytest.mark.asyncio
    async def test_dag_export(self):
        sub_tasks = [
            {"title": "A", "description": "Task A"},
            {"title": "B", "description": "Task B", "depends_on_index": [0]},
        ]
        llm = _make_mock_llm(sub_tasks)
        decomposer = HierarchicalDecomposer(llm, max_depth=4)

        tree = _make_simple_tree()
        result = await decomposer.decompose(tree)

        dag = result.to_dag()
        assert len(dag) == 2  # two leaf nodes
        # One of them should have a dependency
        deps = [v for v in dag.values() if v]
        assert len(deps) == 1

