"""Core data structures: TaskNode, TaskTree, and AgentState.

This module defines the hierarchical task tree and the LangGraph state
that flows through the entire agent pipeline.
"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Task status enum
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Lifecycle status of a task node."""

    PENDING = "pending"           # 待执行
    WAITING = "waiting"           # 等待依赖完成
    RUNNING = "running"           # 执行中
    PASSED = "passed"             # 校验通过
    FAILED = "failed"             # 校验失败
    RE_PLANNING = "re_planning"   # 二次拆解中
    CANCELLED = "cancelled"       # 已取消


class TaskEffect(str, Enum):
    """Planner-declared maximum side-effect class for a task."""

    AUTO = "auto"
    READ = "read"
    WRITE = "write"
    DANGER = "danger"


class PlanValidationError(ValueError):
    """Raised when a task tree is not a valid rooted tree and dependency DAG."""


# ---------------------------------------------------------------------------
# TaskNode — a single node in the task tree
# ---------------------------------------------------------------------------

class TaskNode(BaseModel):
    """A single task node that can be nested into a tree."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str = ""
    requirement: str = ""                        # 验收标准 (给 Validator 用)
    status: TaskStatus = TaskStatus.PENDING
    parent_id: Optional[str] = None              # 父任务 ID
    children_ids: list[str] = Field(default_factory=list)
    dependent_tasks: list[str] = Field(default_factory=list)  # 依赖的任务 ID (DAG)
    depth: int = 0                               # 层级深度 (0 = 顶层目标)
    result: Optional[str] = None                 # 执行结果
    result_artifact: Optional[str] = None        # Archived full result after compaction
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: Optional[dict] = None     # 校验结果
    error_history: list[str] = Field(default_factory=list)
    reflections: list[dict[str, Any]] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    tools_hint: list[str] = Field(default_factory=list)  # 建议使用的工具
    effect: TaskEffect = TaskEffect.AUTO
    is_atomic: bool = False                       # True = do not decompose further
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        """Update the `updated_at` timestamp."""
        self.updated_at = datetime.now(timezone.utc)

    @field_validator("error_history", mode="before")
    @classmethod
    def _coerce_error_history(cls, v: object) -> object:
        """LLM output (and checkpoint reload) may emit ``null`` entries in
        ``error_history``; coerce them to ``""`` so the ``list[str]`` contract
        holds and downstream templates never receive ``None``.

        Repro: an agent run produced a TaskTree whose ``error_history.4`` was
        ``None``, raising ``validation error for TaskTree`` and failing the
        whole turn at orchestration time.
        """
        if isinstance(v, list):
            return [item if item is not None else "" for item in v]
        return v


# ---------------------------------------------------------------------------
# TaskTree — the full hierarchical task structure
# ---------------------------------------------------------------------------

class TaskTree(BaseModel):
    """A tree of TaskNodes rooted at a single goal node.

    Provides helpers for traversing, querying, and mutating the tree.
    """

    goal_id: str
    nodes: dict[str, TaskNode] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    output_format: str = "markdown"

    # -- accessors ----------------------------------------------------------

    def get_root(self) -> TaskNode:
        """Return the root (goal) node."""
        return self.nodes[self.goal_id]

    def get_children(self, node_id: str) -> list[TaskNode]:
        """Return direct children of the given node."""
        node = self.nodes[node_id]
        return [self.nodes[cid] for cid in node.children_ids if cid in self.nodes]

    def get_leaf_nodes(self) -> list[TaskNode]:
        """Return all leaf nodes (nodes with no children)."""
        return [n for n in self.nodes.values() if not n.children_ids]

    def get_pending_leaves(self) -> list[TaskNode]:
        """Return leaf nodes that are still PENDING."""
        return [
            n for n in self.nodes.values()
            if not n.children_ids and n.status == TaskStatus.PENDING
        ]

    def get_failed_nodes(self) -> list[TaskNode]:
        """Return nodes with FAILED status."""
        return [n for n in self.nodes.values() if n.status == TaskStatus.FAILED]

    def find_by_title(self, title: str) -> Optional[TaskNode]:
        """Find the first node whose title matches (case-insensitive)."""
        title_lower = title.strip().lower()
        for n in self.nodes.values():
            if n.title.strip().lower() == title_lower:
                return n
        return None

    # -- mutators -----------------------------------------------------------

    def add_node(self, node: TaskNode) -> None:
        """Add a node to the tree."""
        self.nodes[node.id] = node

    def update_node(self, node_id: str, **kwargs) -> None:
        """Update fields on an existing node."""
        node = self.nodes[node_id]
        for k, v in kwargs.items():
            if hasattr(node, k):
                setattr(node, k, v)
        node.touch()

    # -- queries ------------------------------------------------------------

    def is_complete(self) -> bool:
        """True when every leaf node is PASSED or CANCELLED."""
        leaves = self.get_leaf_nodes()
        if not leaves:
            return False
        return all(
            n.status in (TaskStatus.PASSED, TaskStatus.CANCELLED)
            for n in leaves
        )

    def to_dag(self) -> dict[str, list[str]]:
        """Export leaf-level DAG: {node_id: [dependent_ids]}."""
        dag: dict[str, list[str]] = {}
        for node in self.nodes.values():
            if not node.children_ids:  # leaf only
                dag[node.id] = list(node.dependent_tasks)
        return dag

    def validate_plan(self) -> list[str]:
        """Return all structural and dependency errors without mutating the plan.

        Validation covers the single root, references, bidirectional
        parent/child links, reachability, self-dependencies, and cycles in both
        the hierarchy and task dependency graph.
        """
        errors: list[str] = []
        root = self.nodes.get(self.goal_id)
        if root is None:
            errors.append(f"Root goal_id {self.goal_id!r} does not reference a node")
        elif root.parent_id is not None:
            errors.append(
                f"Root node {self.goal_id!r} must not have parent {root.parent_id!r}"
            )

        hierarchy: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        dependencies: dict[str, list[str]] = {
            node_id: [] for node_id in self.nodes
        }

        for node_id, node in self.nodes.items():
            if node.id != node_id:
                errors.append(
                    f"Node map key {node_id!r} does not match node id {node.id!r}"
                )

            if len(node.children_ids) != len(set(node.children_ids)):
                errors.append(f"Node {node_id!r} lists duplicate children")
            if len(node.dependent_tasks) != len(set(node.dependent_tasks)):
                errors.append(f"Node {node_id!r} lists duplicate dependencies")

            if node_id != self.goal_id:
                if node.parent_id is None:
                    errors.append(f"Non-root node {node_id!r} has no parent")
                elif node.parent_id not in self.nodes:
                    errors.append(
                        f"Node {node_id!r} references unknown parent {node.parent_id!r}"
                    )
                elif node_id not in self.nodes[node.parent_id].children_ids:
                    errors.append(
                        f"Parent {node.parent_id!r} does not list child {node_id!r}"
                    )

            for child_id in node.children_ids:
                if child_id == node_id:
                    errors.append(f"Node {node_id!r} lists itself as a child")
                if child_id not in self.nodes:
                    errors.append(
                        f"Node {node_id!r} references unknown child {child_id!r}"
                    )
                    continue
                hierarchy[node_id].append(child_id)
                child = self.nodes[child_id]
                if child.parent_id != node_id:
                    errors.append(
                        f"Child {child_id!r} points to parent {child.parent_id!r}, "
                        f"not {node_id!r}"
                    )

            for dependency_id in node.dependent_tasks:
                if dependency_id == node_id:
                    errors.append(f"Node {node_id!r} depends on itself")
                if dependency_id not in self.nodes:
                    errors.append(
                        f"Node {node_id!r} references unknown dependency "
                        f"{dependency_id!r}"
                    )
                    continue
                dependencies[node_id].append(dependency_id)

        def find_cycle(adjacency: dict[str, list[str]]) -> list[str] | None:
            colors: dict[str, int] = {node_id: 0 for node_id in adjacency}
            path: list[str] = []
            positions: dict[str, int] = {}

            def visit(node_id: str) -> list[str] | None:
                colors[node_id] = 1
                positions[node_id] = len(path)
                path.append(node_id)
                for neighbor in adjacency[node_id]:
                    if colors[neighbor] == 0:
                        cycle = visit(neighbor)
                        if cycle:
                            return cycle
                    elif colors[neighbor] == 1:
                        return path[positions[neighbor] :] + [neighbor]
                path.pop()
                positions.pop(node_id, None)
                colors[node_id] = 2
                return None

            for candidate in adjacency:
                if colors[candidate] == 0:
                    cycle = visit(candidate)
                    if cycle:
                        return cycle
            return None

        hierarchy_cycle = find_cycle(hierarchy)
        if hierarchy_cycle:
            errors.append(f"Hierarchy cycle detected: {' -> '.join(hierarchy_cycle)}")

        dependency_cycle = find_cycle(dependencies)
        if dependency_cycle:
            errors.append(
                f"Dependency cycle detected: {' -> '.join(dependency_cycle)}"
            )

        if root is not None:
            reachable: set[str] = set()
            pending = [self.goal_id]
            while pending:
                node_id = pending.pop()
                if node_id in reachable:
                    continue
                reachable.add(node_id)
                pending.extend(hierarchy[node_id])
            for node_id in self.nodes.keys() - reachable:
                errors.append(f"Node {node_id!r} is not reachable from the root")

        return errors

    def assert_valid_plan(self) -> None:
        """Raise :class:`PlanValidationError` when ``validate_plan`` fails."""
        errors = self.validate_plan()
        if errors:
            raise PlanValidationError("Invalid task plan: " + "; ".join(errors))

    # -- summary helpers ----------------------------------------------------

    def summary(self) -> str:
        """Human-readable summary of the tree."""
        lines = [f"Goal: {self.nodes[self.goal_id].title}"]
        for node in self.nodes.values():
            indent = "  " * node.depth
            status_icon = {
                TaskStatus.PENDING: "[ ]",
                TaskStatus.RUNNING: "[~]",
                TaskStatus.PASSED: "[x]",
                TaskStatus.FAILED: "[!]",
                TaskStatus.CANCELLED: "[-]",
                TaskStatus.RE_PLANNING: "[R]",
                TaskStatus.WAITING: "[w]",
            }.get(node.status, "[?]")
            lines.append(f"{indent}{status_icon} {node.title}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AgentState — the LangGraph state that flows through the graph
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Global state shared by every node in the LangGraph."""

    # -- input --------------------------------------------------------------
    user_input: str
    session_id: str

    # -- injected dependencies (not serialized) ----------------------------
    _llm: Any
    _memory: Any
    _tool_orchestrator: Any
    _tui: Any                     # TUI for progress reporting
    _tracer: Any                  # Optional runtime trace collector
    _checkpoint_store: Any        # Optional durable graph checkpoint store
    _checkpoint_mode: str         # Stable execution mode used in checkpoint ID
    _checkpoint_key_input: str    # Original request, even when graph input is expanded
    _hooks: Any                   # Optional lifecycle hook registry
    _hook_audit: Any              # Request-local hook audit sink
    _model_router: Any            # Optional role-aware model router
    _trajectory: Any              # Request-local durable trajectory logger

    # -- task tree ----------------------------------------------------------
    task_tree: TaskTree

    # -- memory -------------------------------------------------------------
    memory_context: str                      # 当前上下文摘要
    conversation_history: list[dict]         # 对话历史

    # -- execution ----------------------------------------------------------
    current_task_id: Optional[str]
    execution_results: Annotated[list[dict], operator.add]  # append-only
    parallel_tasks: list[str]  # task IDs for parallel execution (empty = serial)
    parallel_requested: bool   # explicit user request; still capped by max_parallel
    reflections: list[dict]
    failure_attribution: dict[str, int]
    replan_count: int
    reflection_action: Optional[str]
    final_verification: Optional[dict]
    compression_count: int

    # -- output -------------------------------------------------------------
    final_response: Optional[str]

    # -- control flow -------------------------------------------------------
    phase: str                               # planning | executing | validating | synthesizing | done
    error: Optional[str]
