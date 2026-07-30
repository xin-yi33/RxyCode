"""
Tests for context engineering: task-level context isolation in MemoryManager.

Stitched from CrewAI task-level context passing + MetaGPT subscription-filter model.

Verifies that get_task_context:
1. Always includes long-term memory summary (truncated to 2000 chars)
2. Includes ancestor chain results when a TaskTree is provided
3. Includes parent task result when parent_id is provided
4. Includes current task description/requirement from the tree
5. Does NOT include all short-term memory (only task-relevant context)
6. Falls back gracefully when no tree is provided
"""
import asyncio

import pytest


class TestGetTaskContext:
    def _make_manager(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        # Create config.yaml to prevent legacy data migration
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager
        mm = MemoryManager(session_id="test-isolation")
        return mm

    def _make_tree(self):
        """Build a 3-level tree: Goal -> Parent -> Current."""
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode, TaskStatus

        goal = TaskNode(
            id="goal-1", title="Build a web app",
            description="Build a full-stack web app",
        )
        parent = TaskNode(
            id="parent-1", title="Create backend API",
            description="Create FastAPI backend with CRUD endpoints",
            parent_id="goal-1", depth=1,
            result="API is ready at /api/v1 with 5 endpoints",
        )
        current = TaskNode(
            id="current-1", title="Write frontend",
            description="Build React frontend consuming the API",
            requirement="Must connect to /api/v1",
            parent_id="parent-1", depth=2,
        )
        goal.children_ids = ["parent-1"]
        parent.children_ids = ["current-1"]

        tree = TaskTree(goal_id="goal-1")
        tree.nodes = {"goal-1": goal, "parent-1": parent, "current-1": current}
        return tree

    # ------------------------------------------------------------------
    # Basic structure tests
    # ------------------------------------------------------------------

    def test_returns_string(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "t1"))
        assert isinstance(result, str)

    def test_empty_result_when_no_data_and_no_tree(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "t1"))
        assert result == ""

    def test_long_term_memory_always_included(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        mm.long_term.save_session_context("This is important long-term context")
        result = asyncio.run(mm.get_task_context("s1", "t1"))
        assert "Long-term memory" in result
        assert "important long-term context" in result

    def test_long_term_memory_truncated_to_2000_chars(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        long_text = "A" * 3000
        mm.long_term.save_session_context(long_text)
        result = asyncio.run(mm.get_task_context("s1", "t1"))
        # Should be truncated
        assert len(result) < 3000
        assert "..." in result

    # ------------------------------------------------------------------
    # TaskTree ancestor chain tests
    # ------------------------------------------------------------------

    def test_includes_ancestor_results_with_tree(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        tree = self._make_tree()
        result = asyncio.run(mm.get_task_context("s1", "current-1", parent_id="parent-1", tree=tree))
        # Should include parent task result
        assert "Parent task" in result
        assert "API is ready" in result

    def test_includes_current_task_description_with_tree(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        tree = self._make_tree()
        result = asyncio.run(mm.get_task_context("s1", "current-1", parent_id="parent-1", tree=tree))
        assert "Current task" in result
        assert "Write frontend" in result
        assert "Build React frontend" in result

    def test_includes_current_task_requirement(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        tree = self._make_tree()
        result = asyncio.run(mm.get_task_context("s1", "current-1", parent_id="parent-1", tree=tree))
        assert "Requirement" in result
        assert "/api/v1" in result

    def test_ancestor_chain_walks_up_multiple_levels(self, tmp_path, monkeypatch):
        """Goal -> Parent -> Current: should include both goal and parent results."""
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode

        goal = TaskNode(
            id="g", title="Goal", description="The goal",
            result="Goal result: architecture decided",
        )
        parent = TaskNode(
            id="p", title="Parent", description="Parent task",
            parent_id="g", depth=1, result="Parent result: API built",
        )
        current = TaskNode(
            id="c", title="Current", description="Current task",
            parent_id="p", depth=2,
        )
        goal.children_ids = ["p"]
        parent.children_ids = ["c"]
        tree = TaskTree(goal_id="g")
        tree.nodes = {"g": goal, "p": parent, "c": current}

        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "c", parent_id="p", tree=tree))
        # Ancestor chain should include parent result
        assert "Parent result: API built" in result
        # Parent task section should also show parent result
        assert "Parent task" in result

    def test_no_ancestor_results_when_none_available(self, tmp_path, monkeypatch):
        """When ancestor tasks have no results, ancestor section is omitted."""
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode

        parent = TaskNode(id="p", title="Parent", description="Parent task", depth=0)
        current = TaskNode(id="c", title="Current", description="Current task", parent_id="p", depth=1)
        parent.children_ids = ["c"]
        tree = TaskTree(goal_id="p")
        tree.nodes = {"p": parent, "c": current}

        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "c", parent_id="p", tree=tree))
        # Parent task section: parent has no result, so omit it
        assert "Parent task" not in result
        assert "Ancestor task results" not in result
        # But current task should still be there
        assert "Current task" in result

    # ------------------------------------------------------------------
    # Context isolation tests (the key feature)
    # ------------------------------------------------------------------

    def test_does_not_include_short_term_memory(self, tmp_path, monkeypatch):
        """get_task_context should NOT dump all short-term memory."""
        mm = self._make_manager(tmp_path, monkeypatch)
        # Add some interactions to short-term memory
        mm.add_interaction("unrelated question about cooking", "answer about cooking")
        mm.add_interaction("another unrelated topic", "another answer")

        result = asyncio.run(mm.get_task_context("s1", "t1"))
        # Should NOT include the unrelated short-term interactions
        assert "cooking" not in result
        assert "another unrelated topic" not in result

    def test_with_tree_still_excludes_short_term(self, tmp_path, monkeypatch):
        mm = self._make_manager(tmp_path, monkeypatch)
        mm.add_interaction("unrelated history", "unrelated response")
        tree = self._make_tree()
        result = asyncio.run(mm.get_task_context("s1", "current-1", parent_id="parent-1", tree=tree))
        assert "unrelated history" not in result
        assert "unrelated response" not in result

    # ------------------------------------------------------------------
    # Fallback / edge cases
    # ------------------------------------------------------------------

    def test_fallback_without_tree(self, tmp_path, monkeypatch):
        """When tree=None, should still return long-term memory."""
        mm = self._make_manager(tmp_path, monkeypatch)
        mm.long_term.save_session_context("Global context")
        result = asyncio.run(mm.get_task_context("s1", "t1", parent_id="p1"))
        assert "Global context" in result

    def test_parent_id_without_tree_omits_parent_section(self, tmp_path, monkeypatch):
        """parent_id without tree can't look up parent -> omits parent section."""
        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "t1", parent_id="p1"))
        assert "Parent task" not in result

    def test_task_id_not_in_tree(self, tmp_path, monkeypatch):
        """If task_id is not in the tree, gracefully returns long-term only."""
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode

        goal = TaskNode(id="g", title="Goal")
        tree = TaskTree(goal_id="g")
        tree.nodes = {"g": goal}

        mm = self._make_manager(tmp_path, monkeypatch)
        mm.long_term.save_session_context("Global context")
        result = asyncio.run(mm.get_task_context("s1", "nonexistent", tree=tree))
        assert "Global context" in result
        assert "Current task" not in result

    def test_parent_result_truncated(self, tmp_path, monkeypatch):
        """Parent result longer than 1000 chars is truncated."""
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode

        long_result = "X" * 2000
        parent = TaskNode(
            id="p", title="Parent", description="Parent",
            result=long_result, depth=0,
        )
        current = TaskNode(id="c", title="Current", parent_id="p", depth=1)
        parent.children_ids = ["c"]
        tree = TaskTree(goal_id="p")
        tree.nodes = {"p": parent, "c": current}

        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "c", parent_id="p", tree=tree))
        # Should include truncated parent result
        assert "Parent task" in result
        assert "..." in result
        # The parent result in the "Parent task" section should be truncated
        assert len(result) < 2000 + 500  # well under 2000 chars of result + headers

    def test_backward_compatible_signature(self, tmp_path, monkeypatch):
        """Old callers passing only session_id and task_id should still work."""
        mm = self._make_manager(tmp_path, monkeypatch)
        # This should not raise
        result = asyncio.run(mm.get_task_context("s1", "t1"))
        assert isinstance(result, str)

    def test_backward_compatible_with_three_args(self, tmp_path, monkeypatch):
        """Old callers passing session_id, task_id, parent_id should still work."""
        mm = self._make_manager(tmp_path, monkeypatch)
        result = asyncio.run(mm.get_task_context("s1", "t1", "p1"))
        assert isinstance(result, str)

    def test_includes_only_passed_dag_dependencies_not_unrelated_siblings(
        self, tmp_path, monkeypatch,
    ):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

        root = TaskNode(id="root", title="Root")
        prerequisite = TaskNode(
            id="db", title="Build database", parent_id="root", depth=1,
            status=TaskStatus.PASSED, result="schema migration completed",
        )
        current = TaskNode(
            id="api", title="Build API", parent_id="root", depth=1,
            dependent_tasks=["db"],
        )
        unrelated = TaskNode(
            id="css", title="Style dashboard", parent_id="root", depth=1,
            status=TaskStatus.PASSED, result="unrelated magenta stylesheet",
        )
        failed_dependency = TaskNode(
            id="cache", title="Build cache", parent_id="root", depth=1,
            status=TaskStatus.FAILED, result="unverified cache output",
        )
        current.dependent_tasks.append("cache")
        root.children_ids = ["db", "api", "css", "cache"]
        tree = TaskTree(
            goal_id="root",
            nodes={node.id: node for node in (
                root, prerequisite, current, unrelated, failed_dependency,
            )},
        )
        mm = self._make_manager(tmp_path, monkeypatch)

        result = asyncio.run(mm.get_task_context(
            "s1", "api", parent_id="root", tree=tree,
        ))

        assert "schema migration completed" in result
        assert "unrelated magenta stylesheet" not in result
        assert "unverified cache output" not in result
