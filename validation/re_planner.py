"""RePlanner: secondary decomposition of failed tasks.

When a task fails validation, the RePlanner breaks it into finer-grained
sub-tasks and inserts them into the TaskTree. This is the core innovation
of the hierarchical plan-and-execute architecture.

FIX: Previously used a raw prompt.format() + bare HumanMessage without
a SystemMessage, breaking the DeepSeek context cache. Now uses the
shared prompt infrastructure (get_system_prompt + build_user_message +
get_role_prompt) consistent with all other pipeline stages.
"""

from __future__ import annotations

from uuid import uuid4

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.core.prompts import (
    get_system_prompt,
    build_user_message,
    get_role_prompt,
)
from RxyCode.RxyCode1_1_0.planning.structured_output import (
    StructuredOutputError,
    invoke_structured_output,
)


class RePlanner:
    """Decomposes failed tasks into finer-grained sub-tasks."""

    def __init__(
        self,
        llm,
        max_retries: int = 3,
        *,
        max_depth: int | None = None,
        max_nodes: int | None = None,
    ):
        from RxyCode.RxyCode1_1_0.planning.decomposer import (
            DEFAULT_MAX_PLAN_DEPTH,
            DEFAULT_MAX_PLAN_NODES,
        )

        resolved_depth = (
            DEFAULT_MAX_PLAN_DEPTH if max_depth is None else max_depth
        )
        resolved_nodes = (
            DEFAULT_MAX_PLAN_NODES if max_nodes is None else max_nodes
        )
        if resolved_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if resolved_nodes < 1:
            raise ValueError("max_nodes must be at least 1")
        self._llm = llm
        self._max_retries = max_retries
        self._max_depth = resolved_depth
        self._max_nodes = resolved_nodes

    async def replan(self, tree: TaskTree, task_id: str) -> bool:
        """Attempt to re-plan a failed task.

        If the task has exceeded max_retries, marks it CANCELLED.
        Otherwise, decomposes it into sub-tasks and inserts them into the tree.

        Returns:
            True if re-planning was performed, False if task was cancelled.
        """
        task = tree.nodes.get(task_id)
        if not task:
            return False

        tree.assert_valid_plan()

        if task.depth >= self._max_depth or len(tree.nodes) >= self._max_nodes:
            task.status = TaskStatus.CANCELLED
            task.error_history.append(
                "Re-planning stopped because the plan depth or node budget "
                "was exhausted"
            )
            task.touch()
            return False

        # Check retry limit
        if task.retry_count >= self._max_retries:
            task.status = TaskStatus.CANCELLED
            return False

        task.retry_count += 1
        task.status = TaskStatus.RE_PLANNING

        # Get validation info
        vr = task.validation_result or {}
        issues = vr.get("issues", [])
        suggestion = vr.get("suggestion", "")

        # Render role prompt from registry (with few-shot examples)
        role_prompt = get_role_prompt(
            "re_planner",
            title=task.title,
            description=task.description,
            requirement=task.requirement,
            validation_issues=issues,
            suggestion=suggestion,
            result=(task.result or "")[:500],
            reflection=(task.reflections[-1] if task.reflections else {}),
        )
        user_msg = build_user_message(role_prompt, "")

        # Call LLM with shared infrastructure (SystemMessage + HumanMessage)
        from RxyCode.RxyCode1_1_0.planning.decomposer import (
            SubTaskList,
            select_task_indices_within_budget,
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=user_msg),
        ]
        try:
            result = await invoke_structured_output(
                self._llm,
                messages,
                SubTaskList,
                root_key="tasks",
            )
        except StructuredOutputError:
            result = SubTaskList(tasks=[])

        if not result.tasks:
            # LLM decided no decomposition needed - mark as pending for retry
            task.status = TaskStatus.PENDING
            tree.assert_valid_plan()
            return True

        remaining = self._max_nodes - len(tree.nodes)
        selected_indices = select_task_indices_within_budget(
            result.tasks,
            remaining,
        )
        if not selected_indices:
            task.status = TaskStatus.CANCELLED
            task.error_history.append(
                "Re-planning produced no dependency-closed tasks that fit "
                "the remaining node budget"
            )
            task.touch()
            tree.assert_valid_plan()
            return False

        selected_tasks = [
            (index, sub_task)
            for index, sub_task in enumerate(result.tasks)
            if index in selected_indices
        ]

        # Create child nodes
        created: list[TaskNode] = []
        created_by_index: dict[int, TaskNode] = {}
        for original_index, st in selected_tasks:
            child = TaskNode(
                id=str(uuid4()),
                title=st.title,
                description=st.description,
                requirement=st.requirement,
                parent_id=task.id,
                depth=task.depth + 1,
                tools_hint=st.tools_hint,
                effect=st.effect,
                is_atomic=st.is_atomic,
            )
            tree.add_node(child)
            task.children_ids.append(child.id)
            created.append(child)
            created_by_index[original_index] = child

        # Resolve dependencies
        for original_index, st in selected_tasks:
            for dep_index in st.depends_on_index:
                created_by_index[original_index].dependent_tasks.append(
                    created_by_index[dep_index].id
                )

        tree.assert_valid_plan()
        return True
