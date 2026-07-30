"""
Tests for utils/queue.py - Task queue management.
"""
import pytest
from pathlib import Path


class TestQueueManager:
    def _make_queue(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.utils.queue import QueueManager
        return QueueManager()

    def test_empty_queue(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        assert q.list_tasks() == []

    def test_add_task(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.add_task("test task")
        tasks = q.list_tasks()
        assert len(tasks) == 1

    def test_add_multiple_tasks(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.add_task("task 1")
        q.add_task("task 2")
        q.add_task("task 3")
        assert len(q.list_tasks()) == 3

    def test_clear(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.add_task("task 1")
        q.add_task("task 2")
        q.clear()
        assert q.list_tasks() == []

    def test_remove_existing(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.add_task("task 1")
        tasks = q.list_tasks()
        q.remove(tasks[0]["id"])
        assert len(q.list_tasks()) == 0

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        assert q.remove("nonexistent") is False

    def test_persistence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.utils.queue import QueueManager
        q1 = QueueManager()
        q1.add_task("persisted task")
        q2 = QueueManager()
        tasks = q2.list_tasks()
        assert len(tasks) == 1

    def test_run_task_nonexistent(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        # run_task requires an agent argument; with nonexistent task_id it returns None
        from unittest.mock import MagicMock
        mock_agent = MagicMock()
        assert q.run_task(9999, mock_agent) is None

    def test_run_all_empty(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        from unittest.mock import MagicMock
        mock_agent = MagicMock()
        result = q.run_all(mock_agent)
        assert result == []

    def test_add_task_returns_id(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        task_id = q.add_task("test")
        assert task_id is not None

    def test_list_task_fields(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.add_task("my prompt")
        tasks = q.list_tasks()
        assert "id" in tasks[0] or "prompt" in tasks[0]

    def test_clear_on_empty_queue(self, tmp_path, monkeypatch):
        q = self._make_queue(tmp_path, monkeypatch)
        q.clear()
        assert q.list_tasks() == []

    @pytest.mark.asyncio
    async def test_async_cancellation_records_terminal_state(
        self, tmp_path, monkeypatch
    ):
        import asyncio

        queue = self._make_queue(tmp_path, monkeypatch)
        queued = queue.add_task("wait forever")
        started = asyncio.Event()

        async def runner(_prompt):
            started.set()
            await asyncio.Event().wait()

        operation = asyncio.create_task(
            queue.run_task_async(queued["id"], runner)
        )
        await started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

        [task] = queue.list_tasks()
        assert task["status"] == "cancelled"
        assert task["result"] == "[cancelled: queue task]"
        assert task["finished"]

    @pytest.mark.asyncio
    async def test_async_result_is_persisted_without_truncation(
        self, tmp_path, monkeypatch
    ):
        queue = self._make_queue(tmp_path, monkeypatch)
        queued = queue.add_task("long result")
        expected = "result:" + "x" * 2000

        completed = await queue.run_task_async(
            queued["id"], lambda _prompt: _return(expected)
        )

        assert completed["status"] == "succeeded"
        assert queue.list_tasks()[0]["result"] == expected


async def _return(value):
    return value
