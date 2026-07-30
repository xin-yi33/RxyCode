"""TaskScheduler: DAG-based task scheduling (deterministic, no LLM).

Resolves dependencies from the TaskTree and determines which leaf tasks
are ready to execute. Handles CANCELLED cascade: if a dependency is
cancelled, downstream tasks are also cancelled.
"""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree


class TaskScheduler:
    """Deterministic DAG scheduler over a TaskTree.

    This is a pure utility class — not a LangGraph node.
    It is called by the route_next() / route_after_validator() functions.
    """

    def __init__(self, tree: TaskTree):
        tree.assert_valid_plan()
        self.tree = tree

    def get_ready_tasks(self) -> list[TaskNode]:
        """Return leaf tasks whose dependencies are all PASSED.

        Side effects:
        - Tasks whose dependencies are CANCELLED get marked CANCELLED.
        - Tasks whose dependencies are FAILED/WAITING stay PENDING.
        """
        ready: list[TaskNode] = []

        for node in self.tree.get_pending_leaves():
            deps_met = True
            for dep_id in node.dependent_tasks:
                dep_node = self.tree.nodes.get(dep_id)
                if dep_node is None:
                    raise ValueError(
                        f"Task {node.id!r} references missing dependency {dep_id!r}"
                    )

                if dep_node.status == TaskStatus.PASSED:
                    continue  # satisfied

                if dep_node.status == TaskStatus.CANCELLED:
                    # Cascade cancel
                    node.status = TaskStatus.CANCELLED
                    deps_met = False
                    break

                # PENDING / RUNNING / FAILED / RE_PLANNING / WAITING
                deps_met = False
                break

            if deps_met and node.status == TaskStatus.PENDING:
                ready.append(node)

        # Priority: shallower depth first, then earlier creation
        ready.sort(key=lambda n: (n.depth, n.created_at))
        return ready

    def get_parallel_groups(self) -> list[list[TaskNode]]:
        """Group ready tasks by dependency level for potential parallel execution."""
        ready = self.get_ready_tasks()
        groups: dict[int, list[TaskNode]] = {}
        for task in ready:
            dep_level = max(
                (self.tree.nodes[d].depth for d in task.dependent_tasks
                 if d in self.tree.nodes),
                default=-1,
            )
            groups.setdefault(dep_level, []).append(task)
        return list(groups.values())

    def build_dag(self) -> dict[str, list[str]]:
        """Export leaf-level DAG: {node_id: [dependency_ids]}."""
        dag: dict[str, list[str]] = {}
        for node in self.tree.nodes.values():
            if not node.children_ids:
                dag[node.id] = list(node.dependent_tasks)
        return dag

