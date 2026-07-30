"""Tests for TaskScheduler: DAG scheduling and CANCELLED cascade."""

import pytest
from datetime import datetime, timezone

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree, TaskStatus
from RxyCode.RxyCode1_1_0.execution.scheduler import TaskScheduler


def _make_node(id: str, title: str, depth: int = 1,
               parent_id: str = "root",
               deps: list[str] | None = None,
               status: TaskStatus = TaskStatus.PENDING) -> TaskNode:
    return TaskNode(
        id=id, title=title, depth=depth, parent_id=parent_id,
        dependent_tasks=deps or [], status=status,
    )


class TestTaskScheduler:
    def test_invalid_missing_dependency_is_rejected_before_scheduling(self):
        root = TaskNode(id="root", title="Root", depth=0, children_ids=["a"])
        task = _make_node("a", "A", deps=["missing"])
        tree = TaskTree(goal_id="root", nodes={"root": root, "a": task})

        with pytest.raises(ValueError, match="unknown dependency"):
            TaskScheduler(tree)

    def test_ready_tasks_no_deps(self):
        """All leaves with no dependencies should be ready."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A")
        b = _make_node("b", "B")
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        ready = sched.get_ready_tasks()
        assert {n.id for n in ready} == {"a", "b"}

    def test_ready_tasks_with_deps(self):
        """Only tasks whose deps are PASSED should be ready."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A")
        b = _make_node("b", "B", deps=["a"])
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        # Before A passes, only A is ready
        ready = sched.get_ready_tasks()
        assert [n.id for n in ready] == ["a"]

        # After A passes, B becomes ready
        a.status = TaskStatus.PASSED
        ready = sched.get_ready_tasks()
        assert [n.id for n in ready] == ["b"]

    def test_cancelled_cascade(self):
        """If a dependency is CANCELLED, downstream tasks should also be CANCELLED."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A", status=TaskStatus.CANCELLED)
        b = _make_node("b", "B", deps=["a"])
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        ready = sched.get_ready_tasks()
        assert ready == []  # nothing ready
        assert b.status == TaskStatus.CANCELLED  # cascade cancelled

    def test_cancelled_does_not_affect_independent(self):
        """Cancelled task should not affect tasks that don't depend on it."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A", status=TaskStatus.CANCELLED)
        b = _make_node("b", "B")  # no deps
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        ready = sched.get_ready_tasks()
        assert [n.id for n in ready] == ["b"]

    def test_failed_dep_blocks(self):
        """FAILED dependency should block the dependent task."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A", status=TaskStatus.FAILED)
        b = _make_node("b", "B", deps=["a"])
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        ready = sched.get_ready_tasks()
        assert ready == []  # b blocked by failed a

    def test_parallel_groups(self):
        """Tasks at the same dependency level should be grouped together."""
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A")
        b = _make_node("b", "B")
        c = _make_node("c", "C", deps=["a", "b"])
        root.children_ids = ["a", "b", "c"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b, "c": c})
        sched = TaskScheduler(tree)

        groups = sched.get_parallel_groups()
        # First group: a, b (no deps)
        assert len(groups) == 1
        assert {n.id for n in groups[0]} == {"a", "b"}

        # After a, b pass → c is ready
        a.status = TaskStatus.PASSED
        b.status = TaskStatus.PASSED
        groups = sched.get_parallel_groups()
        assert len(groups) == 1
        assert {n.id for n in groups[0]} == {"c"}

    def test_dag_export(self):
        root = TaskNode(id="root", title="Root", depth=0)
        a = _make_node("a", "A")
        b = _make_node("b", "B", deps=["a"])
        root.children_ids = ["a", "b"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "a": a, "b": b})
        sched = TaskScheduler(tree)

        dag = sched.build_dag()
        assert dag["a"] == []
        assert dag["b"] == ["a"]
        assert "root" not in dag  # root has children, not a leaf

