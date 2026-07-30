"""Persistent task queue with synchronous and native async execution."""
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config.settings import get_data_dir
from .atomic_file import atomic_write_text


def _queue_path() -> Path:
    path = get_data_dir() / "queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class QueueManager:
    """Persistent JSON-backed queue whose state transitions are atomic."""

    def __init__(self, storage_path: Path | None = None):
        self._path = Path(storage_path) if storage_path else _queue_path()
        self._lock = threading.RLock()

    def _load_unlocked(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"tasks": [], "next_id": 1}

    def _save_unlocked(self, data: dict) -> None:
        atomic_write_text(
            self._path,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def _claim(self, task_id: int) -> dict | None:
        with self._lock:
            data = self._load_unlocked()
            for task in data.get("tasks", []):
                if task.get("id") != task_id or task.get("status") != "pending":
                    continue
                task["status"] = "running"
                task["started"] = datetime.now().isoformat()
                task["finished"] = ""
                task["result"] = None
                self._save_unlocked(data)
                return dict(task)
        return None

    def _complete(self, task_id: int, status: str, result: str) -> dict | None:
        with self._lock:
            data = self._load_unlocked()
            for task in data.get("tasks", []):
                if task.get("id") != task_id:
                    continue
                task["status"] = status
                task["result"] = result
                task["finished"] = datetime.now().isoformat()
                self._save_unlocked(data)
                return dict(task)
        return None

    @staticmethod
    def _terminal_status(result: str) -> str:
        from ..log.log_helpers import classify_agent_result

        status, _ = classify_agent_result(result)
        return status

    def add_task(self, prompt: str) -> dict:
        """Add a task to the queue and return its persisted record."""
        with self._lock:
            data = self._load_unlocked()
            task_id = data.get("next_id", 1)
            task = {
                "id": task_id,
                "prompt": prompt,
                "status": "pending",
                "created": datetime.now().isoformat(),
                "started": "",
                "finished": "",
                "result": None,
            }
            data.setdefault("tasks", []).append(task)
            data["next_id"] = task_id + 1
            self._save_unlocked(data)
            return dict(task)

    async def run_task_async(
        self,
        task_id: int,
        runner: Callable[[str], Awaitable[object]],
    ) -> dict | None:
        """Claim and execute one task without moving work to another loop."""
        claimed = self._claim(task_id)
        if claimed is None:
            return None
        try:
            result = str(await runner(claimed["prompt"]))
        except asyncio.CancelledError:
            self._complete(task_id, "cancelled", "[cancelled: queue task]")
            raise
        except Exception as exc:
            return self._complete(task_id, "failed", f"Error: {exc}")
        return self._complete(task_id, self._terminal_status(result), result)

    async def run_all_async(
        self,
        runner: Callable[[str], Awaitable[object]],
    ) -> list[dict]:
        """Run every task that was pending when this call began."""
        pending_ids = [
            task["id"]
            for task in self.list_tasks()
            if task.get("status") == "pending"
        ]
        results = []
        for task_id in pending_ids:
            result = await self.run_task_async(task_id, runner)
            if result is not None:
                results.append(result)
        return results

    def run_task(self, task_id: int, agent) -> Optional[str]:
        """Synchronous compatibility wrapper used by the CLI."""
        claimed = self._claim(task_id)
        if claimed is None:
            return None
        try:
            result = str(asyncio.run(agent.run(claimed["prompt"], mode="build")))
        except Exception as exc:
            completed = self._complete(task_id, "failed", f"Error: {exc}")
        else:
            completed = self._complete(
                task_id, self._terminal_status(result), result
            )
        return completed.get("result") if completed else None

    def run_all(self, agent) -> list[dict]:
        """Synchronous compatibility wrapper used by the CLI."""
        pending_ids = [
            task["id"]
            for task in self.list_tasks()
            if task.get("status") == "pending"
        ]
        results = []
        for task_id in pending_ids:
            self.run_task(task_id, agent)
            task = next(
                (item for item in self.list_tasks() if item.get("id") == task_id),
                None,
            )
            if task is not None:
                results.append(
                    {
                        "id": task_id,
                        "status": task.get("status"),
                        "result": task.get("result"),
                    }
                )
        return results

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [dict(task) for task in self._load_unlocked().get("tasks", [])]

    def clear(self) -> None:
        with self._lock:
            self._save_unlocked({"tasks": [], "next_id": 1})

    def remove(self, task_id: int) -> bool:
        with self._lock:
            data = self._load_unlocked()
            tasks = data.get("tasks", [])
            remaining = [task for task in tasks if task.get("id") != task_id]
            if len(remaining) == len(tasks):
                return False
            data["tasks"] = remaining
            self._save_unlocked(data)
            return True
