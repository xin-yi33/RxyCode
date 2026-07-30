"""
Tests for recovery/error_recovery.py - Error handling and retry logic.

Covers: handle_error, get_error_summary, retry limits, cancellation.
"""
import pytest
from unittest.mock import MagicMock


class TestErrorRecovery:
    def _make(self, max_retries=3):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorRecovery
        return ErrorRecovery(max_retries=max_retries)

    def _make_tree(self):
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
        task = TaskNode(title="test task", description="test desc")
        tree = TaskTree(goal_id=task.id)
        tree.nodes[task.id] = task
        return tree, task

    def test_default_max_retries(self):
        er = self._make()
        assert er._max_retries == 3

    def test_custom_max_retries(self):
        er = self._make(max_retries=5)
        assert er._max_retries == 5

    def test_handle_error_task_not_found(self):
        er = self._make()
        tree, _ = self._make_tree()
        result = er.handle_error(tree, "nonexistent", "error")
        assert result == "skip"

    def test_handle_error_first_retry(self):
        er = self._make()
        tree, task = self._make_tree()
        result = er.handle_error(tree, task.id, "error 1")
        assert result == "retry"
        assert task.retry_count == 1

    def test_handle_error_multiple_retries(self):
        er = self._make(max_retries=3)
        tree, task = self._make_tree()
        er.handle_error(tree, task.id, "error 1")
        er.handle_error(tree, task.id, "error 2")
        result = er.handle_error(tree, task.id, "error 3")
        assert result == "retry"
        assert task.retry_count == 3

    def test_handle_error_exceeds_max_retries(self):
        er = self._make(max_retries=2)
        tree, task = self._make_tree()
        er.handle_error(tree, task.id, "error 1")
        er.handle_error(tree, task.id, "error 2")
        result = er.handle_error(tree, task.id, "error 3")
        assert result == "cancel"

    def test_handle_error_cancels_task(self):
        er = self._make(max_retries=1)
        tree, task = self._make_tree()
        er.handle_error(tree, task.id, "error 1")
        result = er.handle_error(tree, task.id, "error 2")
        assert result == "cancel"
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        assert task.status == TaskStatus.CANCELLED

    def test_handle_error_resets_to_pending(self):
        er = self._make()
        tree, task = self._make_tree()
        from RxyCode.RxyCode1_1_0.core.state import TaskStatus
        task.status = TaskStatus.RUNNING
        result = er.handle_error(tree, task.id, "error")
        assert result == "retry"
        assert task.status == TaskStatus.PENDING

    def test_handle_error_appends_to_history(self):
        er = self._make()
        tree, task = self._make_tree()
        er.handle_error(tree, task.id, "error message")
        assert len(task.error_history) == 1
        assert task.error_history[0] == "error message"

    def test_handle_error_multiple_errors_in_history(self):
        er = self._make(max_retries=5)
        tree, task = self._make_tree()
        for i in range(3):
            er.handle_error(tree, task.id, f"error {i}")
        assert len(task.error_history) == 3

    def test_get_error_summary_no_errors(self):
        er = self._make()
        tree, _ = self._make_tree()
        summary = er.get_error_summary(tree)
        assert "no errors" in summary.lower()

    def test_get_error_summary_with_errors(self):
        er = self._make()
        tree, task = self._make_tree()
        er.handle_error(tree, task.id, "first error")
        er.handle_error(tree, task.id, "second error")
        summary = er.get_error_summary(tree)
        assert "test task" in summary
        assert "2 errors" in summary

    def test_get_error_summary_truncates_long_errors(self):
        er = self._make()
        tree, task = self._make_tree()
        long_error = "x" * 300
        er.handle_error(tree, task.id, long_error)
        summary = er.get_error_summary(tree)
        # Should truncate to 200 chars
        assert len(summary) < 500

    def test_get_error_summary_shows_last_3(self):
        er = self._make(max_retries=10)
        tree, task = self._make_tree()
        for i in range(5):
            er.handle_error(tree, task.id, f"error {i}")
        summary = er.get_error_summary(tree)
        # Should only show last 3
        assert "error 2" in summary
        assert "error 3" in summary
        assert "error 4" in summary

    def test_handle_error_touches_task(self):
        er = self._make()
        tree, task = self._make_tree()
        original_updated = task.updated_at
        er.handle_error(tree, task.id, "error")
        assert task.updated_at >= original_updated

    def test_handle_error_zero_max_retries(self):
        er = self._make(max_retries=0)
        tree, task = self._make_tree()
        result = er.handle_error(tree, task.id, "error")
        assert result == "cancel"
