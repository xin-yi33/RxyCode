"""
Tests for synthesis/synthesizer.py - Output synthesis.

Covers: collect_results, synthesize with mock LLM, empty tree handling.
"""
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock


class TestOutputSynthesizer:
    @staticmethod
    def _grounded_response(tree, *, pad: bool = False):
        from RxyCode.RxyCode1_1_0.validation.final_output import (
            build_grounding_sources,
        )

        sources = build_grounding_sources(tree)
        claims = [
            {
                "task_id": source.task_id,
                "source_id": source.source_id,
                "text": source.text,
            }
            for source in sources
        ]
        answer = "\n\n".join(claim["text"] for claim in claims)
        content = json.dumps({"answer": answer, "claims": claims})
        if pad:
            content = f"  {content}  \n"
        return MagicMock(content=content)

    def _make(self):
        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer
        mock_llm = MagicMock()
        return OutputSynthesizer(mock_llm)

    def _make_tree(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree
        task = TaskNode(title="goal", description="goal")
        tree = TaskTree(goal_id=task.id)
        return tree

    def test_init(self):
        synth = self._make()
        assert synth._llm is not None

    def test_collect_results_empty(self):
        synth = self._make()
        tree = self._make_tree()
        results = synth.collect_results(tree)
        assert results == []

    def test_collect_results_with_passed_tasks(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        synth = self._make()
        task = TaskNode(title="test", description="desc", depth=0)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = "test result"
        tree.nodes[task.id] = task
        results = synth.collect_results(tree)
        assert len(results) == 1
        assert results[0]["title"] == "test"
        assert results[0]["result"] == "test result"

    def test_collect_results_skips_non_passed(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        synth = self._make()
        task1 = TaskNode(title="passed", description="d", depth=0)
        tree = TaskTree(goal_id=task1.id)
        task1.status = TaskStatus.PASSED
        task1.result = "result1"
        tree.nodes[task1.id] = task1

        task2 = TaskNode(title="running", description="d", depth=0)
        task2.status = TaskStatus.RUNNING
        task2.result = "result2"
        tree.nodes[task2.id] = task2

        results = synth.collect_results(tree)
        assert len(results) == 1
        assert results[0]["title"] == "passed"

    def test_collect_results_skips_no_result(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        synth = self._make()
        task = TaskNode(title="no result", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = None
        tree.nodes[task.id] = task
        results = synth.collect_results(tree)
        assert results == []

    def test_collect_results_includes_fields(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        synth = self._make()
        task = TaskNode(title="test", description="d", depth=1)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = "result"
        tree.nodes[task.id] = task
        results = synth.collect_results(tree)
        assert "id" in results[0]
        assert "title" in results[0]
        assert "depth" in results[0]
        assert "result" in results[0]
        assert "parent_id" in results[0]

    def test_synthesize_empty_tree(self):
        synth = self._make()
        tree = self._make_tree()
        result = asyncio.run(synth.synthesize(tree, "user input"))
        assert "No completed tasks" in result

    def test_synthesize_with_results(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        mock_llm = MagicMock()
        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer

        task = TaskNode(title="test", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = "test result"
        tree.nodes[task.id] = task
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree)
        )
        synth = OutputSynthesizer(mock_llm)

        result = asyncio.run(synth.synthesize(tree, "user input"))
        assert result == "test result"

    def test_synthesize_discloses_cancelled_tasks_when_results_are_mixed(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer

        mock_llm = MagicMock()
        root = TaskNode(title="goal", description="goal")
        passed = TaskNode(
            title="completed analysis",
            description="analyze",
            parent_id=root.id,
            status=TaskStatus.PASSED,
            result="verified result",
        )
        cancelled = TaskNode(
            title="cancelled implementation",
            description="implement",
            parent_id=root.id,
            status=TaskStatus.CANCELLED,
            error_history=["stopped by operator"],
        )
        root.children_ids = [passed.id, cancelled.id]
        tree = TaskTree(
            goal_id=root.id,
            nodes={root.id: root, passed.id: passed, cancelled.id: cancelled},
        )
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree)
        )
        synth = OutputSynthesizer(mock_llm)

        result = asyncio.run(synth.synthesize(tree, "finish the feature"))

        assert result == "verified result"
        messages = mock_llm.ainvoke.await_args.args[0]
        user_msg = messages[1].content
        assert "Cancelled/incomplete sub-tasks" in user_msg
        assert "cancelled implementation" in user_msg
        assert "stopped by operator" in user_msg

    def test_synthesize_only_cancelled_tasks_fails_honestly_without_llm(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        synth = OutputSynthesizer(mock_llm)
        task = TaskNode(
            title="cancelled implementation",
            description="implement",
            status=TaskStatus.CANCELLED,
            error_history=["stopped by operator"],
        )
        tree = TaskTree(goal_id=task.id, nodes={task.id: task})

        result = asyncio.run(synth.synthesize(tree, "finish the feature"))

        assert result.startswith("[Build incomplete:")
        assert "No completed tasks" in result
        assert "cancelled implementation" in result
        mock_llm.ainvoke.assert_not_awaited()

    def test_synthesize_truncates_long_results(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        mock_llm = MagicMock()

        task = TaskNode(title="test", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = "x" * 3000  # Long result
        tree.nodes[task.id] = task
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree)
        )

        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer
        synth = OutputSynthesizer(mock_llm)

        asyncio.run(synth.synthesize(tree, "input"))
        # The result should be truncated in the LLM call
        # Check that ainvoke was called
        mock_llm.ainvoke.assert_called_once()

    def test_synthesize_strips_whitespace(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        mock_llm = MagicMock()

        task = TaskNode(title="test", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        task.status = TaskStatus.PASSED
        task.result = "result"
        tree.nodes[task.id] = task
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree, pad=True)
        )

        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer
        synth = OutputSynthesizer(mock_llm)

        result = asyncio.run(synth.synthesize(tree, "input"))
        assert result == "result"

    def test_synthesize_includes_constraints(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        mock_llm = MagicMock()

        task = TaskNode(title="test", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        tree.constraints = ["constraint1", "constraint2"]
        task.status = TaskStatus.PASSED
        task.result = "result"
        tree.nodes[task.id] = task
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree)
        )

        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer
        synth = OutputSynthesizer(mock_llm)

        asyncio.run(synth.synthesize(tree, "input"))
        # Check that constraints were included in the call
        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        user_msg = messages[1].content
        assert "constraint1" in user_msg
        assert "constraint2" in user_msg

    def test_synthesize_includes_output_format(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        mock_llm = MagicMock()

        task = TaskNode(title="test", description="d", depth=0)
        tree = TaskTree(goal_id=task.id)
        tree.output_format = "markdown"
        task.status = TaskStatus.PASSED
        task.result = "result"
        tree.nodes[task.id] = task
        mock_llm.ainvoke = AsyncMock(
            return_value=self._grounded_response(tree)
        )

        from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer
        synth = OutputSynthesizer(mock_llm)

        asyncio.run(synth.synthesize(tree, "input"))
        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        user_msg = messages[1].content
        assert "markdown" in user_msg
