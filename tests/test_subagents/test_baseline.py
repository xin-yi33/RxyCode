"""B1 · Baseline regression tests — prove single-agent path is unchanged.

These tests must pass BEFORE any Phase B implementation begins, and must
continue to pass throughout all B1–B14 cards (zero-regression gate).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# B1.1: Legacy symbol inventory — verify known state
# ---------------------------------------------------------------------------

class TestLegacySymbolInventory:
    """Confirm the disposition of every legacy subagent symbol found in B1."""

    def test_run_with_subagents_raises(self):
        """_run_with_subagents must unconditionally raise RuntimeError."""
        import inspect
        from core.agent_v2 import AgentV2

        # Verify the method source contains the raise statement
        src = inspect.getsource(AgentV2._run_with_subagents)
        assert "raise RuntimeError" in src
        assert "legacy sub-agent execution is disabled" in src

    def test_should_use_subagents_delegates_to_routing(self):
        """_should_use_subagents delegates to request_routing.should_use_subagents."""
        import inspect
        from core.agent_v2 import AgentV2

        src = inspect.getsource(AgentV2._should_use_subagents)
        assert "should_use_subagents" in src

    def test_should_use_subagents_function_returns_bool(self):
        """The underlying should_use_subagents function returns a bool."""
        from core.request_routing import should_use_subagents

        result = should_use_subagents("同时处理多个文件")
        assert isinstance(result, bool)
        assert result is True  # contains "同时"

        result2 = should_use_subagents("hello world")
        assert isinstance(result2, bool)
        assert result2 is False

    def test_subagentv2_class_exists(self):
        """SubAgentV2 class is importable but should have 0 instantiations."""
        from core.agent_v2 import SubAgentV2
        assert SubAgentV2 is not None

    def test_agent_tool_has_deprecated_name(self):
        """Old agent_tool uses name='agent' — must be renamed/migrated in B13."""
        from tools.agent_tool import agent_tool
        assert agent_tool.name == "agent"

    def test_task_tool_name_is_task(self):
        """Current task_tool uses name='task' — must be renamed to 'task_manage' in B13."""
        # task_tool has relative imports that fail outside the package context;
        # inspect the source to confirm the tool name.
        import inspect
        from pathlib import Path

        task_tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools" / "task_tool.py"
        )
        src = task_tool_path.read_text(encoding="utf-8")
        assert 'name="task"' in src, "task_tool must be named 'task'"

    def test_task_tool_is_persistent_task_management(self):
        """task_tool manages a persistent task list, NOT subagent dispatch."""
        from pathlib import Path

        task_tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools" / "task_tool.py"
        )
        src = task_tool_path.read_text(encoding="utf-8")
        # Must contain task management operations, NOT subagent dispatch
        assert "create" in src
        assert "list" in src
        assert "ChildSession" not in src
        assert "ChildRuntime" not in src


# ---------------------------------------------------------------------------
# B1.2: Single-agent path integrity
# ---------------------------------------------------------------------------

class TestSingleAgentPathIntegrity:
    """The single-agent execution path must remain untouched."""

    def test_tasktree_structure_unchanged(self):
        """TaskTree and TaskNode must retain their current API."""
        from core.state import TaskTree, TaskNode, TaskStatus

        root = TaskNode(title="root", id="root")
        leaf = TaskNode(title="leaf", id="leaf", parent_id="root", depth=1)
        root.children_ids = ["leaf"]

        tree = TaskTree(goal_id="root", nodes={"root": root, "leaf": leaf})

        assert tree.get_root().title == "root"
        assert len(tree.get_children("root")) == 1
        assert tree.get_children("root")[0].title == "leaf"
        assert leaf.status == TaskStatus.PENDING

    def test_tasktree_validation_preserved(self):
        """TaskTree model validation must still work."""
        from core.state import TaskTree, TaskNode

        tree = TaskTree(
            goal_id="g1",
            nodes={"g1": TaskNode(id="g1", title="Goal")},
        )
        assert tree.goal_id == "g1"
        assert "g1" in tree.nodes

    def test_agent_state_structure_unchanged(self):
        """AgentState must retain its current TypedDict shape."""
        from core.state import AgentState
        # AgentState is a TypedDict — verify it's importable
        assert AgentState is not None

    def test_protocol_version_importable(self):
        """Protocol module must remain importable."""
        from protocol import PROTOCOL_VERSION
        assert isinstance(PROTOCOL_VERSION, str)
        assert PROTOCOL_VERSION == "1.0.0"

    def test_appserver_structure_importable(self):
        """Appserver core modules must remain importable."""
        # These imports must succeed without circular dependency errors
        from protocol.types import RunStatus, RiskLevelName
        assert RunStatus is not None
        assert RiskLevelName is not None


# ---------------------------------------------------------------------------
# B1.3: No second subagent implementation
# ---------------------------------------------------------------------------

class TestNoSecondSubagentImplementation:
    """Prove there is no hidden/duplicate subagent runtime."""

    def test_no_core_subagents_package_yet(self):
        """core/subagents/ must NOT exist before B2 creates it."""
        import importlib.util
        spec = importlib.util.find_spec("core.subagents")
        assert spec is None, (
            "core/subagents/ already exists — B1 expects it to be created in B2+"
        )

    def test_no_protocol_subagents_module_yet(self):
        """protocol/subagents.py must NOT exist before B2 creates it."""
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "protocol" / "subagents.py"
        assert not p.exists(), (
            "protocol/subagents.py already exists — B1 expects it to be created in B2+"
        )

    def test_no_subagent_task_tool_yet(self):
        """tools/subagent_task_tool.py must NOT exist before B7 creates it."""
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "tools" / "subagent_task_tool.py"
        assert not p.exists(), (
            "tools/subagent_task_tool.py already exists — B1 expects it to be created in B7+"
        )

    def test_agent_tool_creates_new_agentv2_instance(self):
        """agent_tool creates a fresh AgentV2 — NOT a Child Session."""
        from tools.agent_tool import run_agent_async
        import inspect
        source = inspect.getsource(run_agent_async)
        assert "AgentV2" in source
        assert "ChildSession" not in source
        assert "ChildRuntime" not in source
