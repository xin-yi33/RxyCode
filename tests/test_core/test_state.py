"""
Tests for core/state.py - TaskNode, TaskTree, AgentState.

Covers: task status, tree operations, DAG export, summary, queries.
"""
import pytest


class TestTaskStatus:
    def test_status_values(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.PASSED == "passed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"
        assert TaskStatus.WAITING == "waiting"
        assert TaskStatus.RE_PLANNING == "re_planning"

    def test_status_is_string_enum(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        assert isinstance(TaskStatus.PENDING, str)
        assert TaskStatus.PENDING == "pending"


class TestTaskNode:
    def _make_node(self, title="Test Task", **kwargs):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        return TaskNode(title=title, **kwargs)

    def test_default_values(self):
        node = self._make_node()
        assert node.title == "Test Task"
        assert node.description == ""
        assert node.status.value == "pending"
        assert node.children_ids == []
        assert node.dependent_tasks == []
        assert node.depth == 0
        assert node.result is None
        assert node.retry_count == 0
        assert node.max_retries == 3
        assert node.effect == "auto"

    def test_custom_values(self):
        node = self._make_node(
            title="Custom",
            description="A description",
            depth=2,
            tools_hint=["read", "write"],
            effect="write",
        )
        assert node.title == "Custom"
        assert node.description == "A description"
        assert node.depth == 2
        assert node.tools_hint == ["read", "write"]
        assert node.effect == "write"

    def test_has_unique_id(self):
        n1 = self._make_node()
        n2 = self._make_node()
        assert n1.id != n2.id

    def test_id_is_string(self):
        node = self._make_node()
        assert isinstance(node.id, str)

    def test_touch_updates_timestamp(self):
        node = self._make_node()
        old = node.updated_at
        node.touch()
        assert node.updated_at >= old

    def test_error_history_default_empty(self):
        node = self._make_node()
        assert node.error_history == []

    def test_validation_result_default_none(self):
        node = self._make_node()
        assert node.validation_result is None

    def test_parent_id_default_none(self):
        node = self._make_node()
        assert node.parent_id is None

    def test_created_at_is_datetime(self):
        from datetime import datetime
        node = self._make_node()
        assert isinstance(node.created_at, datetime)

    def test_serialization(self):
        node = self._make_node(title="Serialize Me")
        d = node.model_dump()
        assert d["title"] == "Serialize Me"
        assert d["status"] == "pending"
        assert d["effect"] == "auto"

    def test_deserialization(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        node = TaskNode(title="X", id="test-123", depth=1)
        d = node.model_dump()
        restored = TaskNode(**d)
        assert restored.title == "X"
        assert restored.id == "test-123"


class TestTaskTree:
    def _make_tree(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskTree, TaskNode
        goal = TaskNode(title="Goal", id="goal-1")
        tree = TaskTree(goal_id="goal-1")
        tree.nodes[goal.id] = goal
        return tree, goal

    def test_get_root(self):
        tree, goal = self._make_tree()
        assert tree.get_root() is goal

    def test_get_children_empty(self):
        tree, _ = self._make_tree()
        assert tree.get_children("goal-1") == []

    def test_get_children_with_nodes(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        child = TaskNode(title="Child", id="child-1", parent_id="goal-1", depth=1)
        goal.children_ids.append(child.id)
        tree.nodes[child.id] = child
        children = tree.get_children("goal-1")
        assert len(children) == 1
        assert children[0].title == "Child"

    def test_get_leaf_nodes(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        child1 = TaskNode(title="C1", id="c1", depth=1)
        child2 = TaskNode(title="C2", id="c2", depth=1)
        goal.children_ids = ["c1", "c2"]
        tree.nodes["c1"] = child1
        tree.nodes["c2"] = child2
        leaves = tree.get_leaf_nodes()
        assert len(leaves) == 2

    def test_get_pending_leaves(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        tree, goal = self._make_tree()
        pending = TaskNode(title="P", id="p1", depth=1)
        done = TaskNode(title="D", id="d1", depth=1, status=TaskStatus.PASSED)
        goal.children_ids = ["p1", "d1"]
        tree.nodes["p1"] = pending
        tree.nodes["d1"] = done
        pending_leaves = tree.get_pending_leaves()
        assert len(pending_leaves) == 1
        assert pending_leaves[0].title == "P"

    def test_get_failed_nodes(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        tree, goal = self._make_tree()
        failed = TaskNode(title="F", id="f1", depth=1, status=TaskStatus.FAILED)
        ok = TaskNode(title="OK", id="ok1", depth=1)
        goal.children_ids = ["f1", "ok1"]
        tree.nodes["f1"] = failed
        tree.nodes["ok1"] = ok
        failed_nodes = tree.get_failed_nodes()
        assert len(failed_nodes) == 1

    def test_find_by_title(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        child = TaskNode(title="Find Me", id="c1", depth=1)
        tree.nodes["c1"] = child
        goal.children_ids = ["c1"]
        found = tree.find_by_title("find me")
        assert found is not None
        assert found.id == "c1"

    def test_find_by_title_not_found(self):
        tree, _ = self._make_tree()
        assert tree.find_by_title("nonexistent") is None

    def test_find_by_title_case_insensitive(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        child = TaskNode(title="MyTask", id="c1", depth=1)
        tree.nodes["c1"] = child
        goal.children_ids = ["c1"]
        assert tree.find_by_title("MYTASK") is not None

    def test_add_node(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, _ = self._make_tree()
        new_node = TaskNode(title="New", id="new-1")
        tree.add_node(new_node)
        assert "new-1" in tree.nodes

    def test_update_node(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, _ = self._make_tree()
        node = TaskNode(title="Original", id="n1")
        tree.add_node(node)
        tree.update_node("n1", title="Updated")
        assert tree.nodes["n1"].title == "Updated"

    def test_is_complete_all_passed(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        tree, goal = self._make_tree()
        c1 = TaskNode(title="C1", id="c1", depth=1, status=TaskStatus.PASSED)
        c2 = TaskNode(title="C2", id="c2", depth=1, status=TaskStatus.PASSED)
        goal.children_ids = ["c1", "c2"]
        tree.nodes["c1"] = c1
        tree.nodes["c2"] = c2
        assert tree.is_complete() is True

    def test_is_complete_with_pending(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        c1 = TaskNode(title="C1", id="c1", depth=1)
        goal.children_ids = ["c1"]
        tree.nodes["c1"] = c1
        assert tree.is_complete() is False

    def test_is_complete_with_cancelled(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        tree, goal = self._make_tree()
        c1 = TaskNode(title="C1", id="c1", depth=1, status=TaskStatus.CANCELLED)
        goal.children_ids = ["c1"]
        tree.nodes["c1"] = c1
        assert tree.is_complete() is True

    def test_is_complete_no_leaves(self):
        tree, _ = self._make_tree()
        assert tree.is_complete() is False

    def test_to_dag(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        c1 = TaskNode(title="C1", id="c1", depth=1, dependent_tasks=["c2"])
        c2 = TaskNode(title="C2", id="c2", depth=1)
        goal.children_ids = ["c1", "c2"]
        tree.nodes["c1"] = c1
        tree.nodes["c2"] = c2
        dag = tree.to_dag()
        assert "c1" in dag
        assert dag["c1"] == ["c2"]
        assert dag["c2"] == []

    def test_to_dag_excludes_non_leaf(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode
        tree, goal = self._make_tree()
        child = TaskNode(title="Child", id="child", depth=1)
        grandchild = TaskNode(title="GC", id="gc", depth=2, parent_id="child")
        child.children_ids = ["gc"]
        goal.children_ids = ["child"]
        tree.nodes["child"] = child
        tree.nodes["gc"] = grandchild
        dag = tree.to_dag()
        assert "gc" in dag
        assert "child" not in dag

    def test_summary_contains_goal_title(self):
        tree, goal = self._make_tree()
        summary = tree.summary()
        assert "Goal" in summary

    def test_summary_shows_status_icons(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus
        tree, goal = self._make_tree()
        c1 = TaskNode(title="Pending", id="c1", depth=1)
        c2 = TaskNode(title="Done", id="c2", depth=1, status=TaskStatus.PASSED)
        goal.children_ids = ["c1", "c2"]
        tree.nodes["c1"] = c1
        tree.nodes["c2"] = c2
        summary = tree.summary()
        assert "[ ]" in summary  # pending
        assert "[x]" in summary  # passed

    def test_constraints_default_empty(self):
        tree, _ = self._make_tree()
        assert tree.constraints == []

    def test_output_format_default(self):
        tree, _ = self._make_tree()
        assert tree.output_format == "markdown"

    def test_nodes_is_dict(self):
        tree, _ = self._make_tree()
        assert isinstance(tree.nodes, dict)

    def test_validate_plan_accepts_a_consistent_tree_and_dag(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode

        tree, goal = self._make_tree()
        first = TaskNode(id="first", title="First", parent_id=goal.id, depth=1)
        second = TaskNode(
            id="second",
            title="Second",
            parent_id=goal.id,
            depth=1,
            dependent_tasks=[first.id],
        )
        goal.children_ids = [first.id, second.id]
        tree.nodes.update({first.id: first, second.id: second})

        assert tree.validate_plan() == []
        tree.assert_valid_plan()

    def test_validate_plan_reports_missing_root(self):
        tree, _ = self._make_tree()
        tree.goal_id = "missing"

        assert any("root" in issue.lower() for issue in tree.validate_plan())

    def test_validate_plan_reports_broken_references(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode

        tree, goal = self._make_tree()
        goal.children_ids.append("missing-child")
        orphan = TaskNode(id="orphan", title="Orphan", parent_id="missing-parent")
        tree.nodes[orphan.id] = orphan

        issues = tree.validate_plan()

        assert any("unknown child" in issue.lower() for issue in issues)
        assert any("unknown parent" in issue.lower() for issue in issues)

    def test_validate_plan_reports_parent_child_mismatch_and_self_dependency(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode

        tree, goal = self._make_tree()
        child = TaskNode(
            id="child",
            title="Child",
            parent_id=goal.id,
            dependent_tasks=["child"],
        )
        tree.nodes[child.id] = child

        issues = tree.validate_plan()

        assert any("does not list" in issue.lower() for issue in issues)
        assert any("depends on itself" in issue.lower() for issue in issues)

    def test_validate_plan_detects_dependency_cycle(self):
        from RxyCode.RxyCode1_1_0.core.state import (
            PlanValidationError,
            TaskNode,
        )

        tree, goal = self._make_tree()
        first = TaskNode(id="first", title="First", parent_id=goal.id, dependent_tasks=["second"])
        second = TaskNode(id="second", title="Second", parent_id=goal.id, dependent_tasks=["first"])
        goal.children_ids = [first.id, second.id]
        tree.nodes.update({first.id: first, second.id: second})

        assert any("dependency cycle" in issue.lower() for issue in tree.validate_plan())
        with pytest.raises(PlanValidationError):
            tree.assert_valid_plan()

    def test_validate_plan_detects_hierarchy_cycle(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode

        tree, goal = self._make_tree()
        first = TaskNode(id="first", title="First", parent_id="second", children_ids=["second"])
        second = TaskNode(id="second", title="Second", parent_id="first", children_ids=["first"])
        tree.nodes.update({first.id: first, second.id: second})

        issues = tree.validate_plan()

        assert any("hierarchy cycle" in issue.lower() for issue in issues)
        assert any("not reachable" in issue.lower() for issue in issues)


class TestAgentState:
    def test_state_is_typed_dict(self):
        from RxyCode.RxyCode1_1_0.core.state import AgentState
        # AgentState is a TypedDict, just verify it exists
        assert AgentState is not None
