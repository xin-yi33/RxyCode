"""HierarchicalDecomposer: recursive task tree decomposition."""

from __future__ import annotations
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator
from RxyCode.RxyCode1_1_0.core.state import TaskEffect, TaskNode, TaskTree
from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt, build_user_message, get_role_prompt
from RxyCode.RxyCode1_1_0.planning.structured_output import (
    StructuredOutputError,
    invoke_structured_output,
)


class SubTask(BaseModel):
    title: str
    description: str = ""
    requirement: str = ""
    tools_hint: list[str] = Field(default_factory=list)
    effect: TaskEffect = TaskEffect.AUTO
    depends_on_index: list[int] = Field(default_factory=list)
    is_atomic: bool = False


class SubTaskList(BaseModel):
    tasks: list[SubTask] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "SubTaskList":
        """Reject invalid dependency indices and cycles before tree mutation."""
        count = len(self.tasks)
        adjacency: dict[int, list[int]] = {}
        for index, task in enumerate(self.tasks):
            dependencies = task.depends_on_index
            if len(dependencies) != len(set(dependencies)):
                raise ValueError(f"task {index} has duplicate dependencies")
            for dependency in dependencies:
                if dependency < 0 or dependency >= count:
                    raise ValueError(
                        f"task {index} dependency index {dependency} is out of range"
                    )
                if dependency == index:
                    raise ValueError(f"task {index} depends on itself")
            adjacency[index] = dependencies

        colors = [0] * count

        def visit(index: int) -> bool:
            colors[index] = 1
            for dependency in adjacency[index]:
                if colors[dependency] == 1:
                    return True
                if colors[dependency] == 0 and visit(dependency):
                    return True
            colors[index] = 2
            return False

        if any(colors[index] == 0 and visit(index) for index in range(count)):
            raise ValueError("task dependencies contain a cycle")
        return self


DEFAULT_MAX_PLAN_DEPTH = 4
DEFAULT_MAX_PLAN_NODES = 64


def select_task_indices_within_budget(
    tasks: list[SubTask],
    remaining_nodes: int,
) -> set[int]:
    """Select the largest dependency-closed prefix that fits the node budget."""
    remaining_nodes = max(0, int(remaining_nodes))
    selected_indices: set[int] = set()
    for index in range(len(tasks)):
        closure: set[int] = set()
        pending = [index]
        while pending:
            candidate = pending.pop()
            if candidate in closure:
                continue
            closure.add(candidate)
            pending.extend(tasks[candidate].depends_on_index)
        if len(selected_indices | closure) <= remaining_nodes:
            selected_indices.update(closure)
    return selected_indices


class HierarchicalDecomposer:
    def __init__(
        self,
        llm,
        max_depth: int = DEFAULT_MAX_PLAN_DEPTH,
        max_nodes: int = DEFAULT_MAX_PLAN_NODES,
    ):
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if max_nodes < 1:
            raise ValueError("max_nodes must be at least 1")
        self._llm = llm
        self._max_depth = max_depth
        self._max_nodes = max_nodes

    async def decompose(self, tree: TaskTree, memory_context: str = "") -> TaskTree:
        root = tree.get_root()
        await self._decompose_recursive(tree, root, memory_context)
        tree.assert_valid_plan()
        return tree

    async def _decompose_recursive(self, tree: TaskTree, node: TaskNode, memory_context: str) -> None:
        if (
            node.is_atomic
            or node.depth >= self._max_depth
            or len(tree.nodes) >= self._max_nodes
        ):
            return
        from langchain_core.messages import HumanMessage, SystemMessage
        task_content = f"Task: {node.title}\nDescription: {node.description}\nConstraints: {tree.constraints}"
        user_msg = build_user_message(get_role_prompt("decomposer"), task_content, memory_context)
        messages = [SystemMessage(content=get_system_prompt()), HumanMessage(content=user_msg)]
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
            return

        remaining = self._max_nodes - len(tree.nodes)
        selected_indices = select_task_indices_within_budget(
            result.tasks,
            remaining,
        )

        selected_tasks = [
            (index, task)
            for index, task in enumerate(result.tasks)
            if index in selected_indices
        ]
        created_children = []
        created_by_index: dict[int, TaskNode] = {}
        for original_index, st in selected_tasks:
            child = TaskNode(
                id=str(uuid4()),
                title=st.title,
                description=st.description,
                requirement=st.requirement,
                parent_id=node.id,
                depth=node.depth + 1,
                tools_hint=st.tools_hint,
                effect=st.effect,
                is_atomic=st.is_atomic,
            )
            tree.add_node(child)
            node.children_ids.append(child.id)
            created_children.append(child)
            created_by_index[original_index] = child
        for original_index, st in selected_tasks:
            for dep_index in st.depends_on_index:
                created_by_index[original_index].dependent_tasks.append(
                    created_by_index[dep_index].id
                )
        for child in created_children:
            await self._decompose_recursive(tree, child, memory_context)
