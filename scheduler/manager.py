"""Task scheduler manager - runs scheduled tasks in background."""

import asyncio
import inspect
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Any

from .cron import parse_cron, CronExpression
from ..utils.atomic_file import atomic_write_text

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled task definition."""
    id: str
    cron_expr: str
    prompt: str
    enabled: bool = True
    created_at: str = ""
    last_run: str = ""
    run_count: int = 0
    last_status: str = ""
    last_result: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cron_expr": self.cron_expr,
            "prompt": self.prompt,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "last_status": self.last_status,
            "last_result": self.last_result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledTask":
        return cls(
            id=data.get("id", ""),
            cron_expr=data.get("cron_expr", ""),
            prompt=data.get("prompt", ""),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", ""),
            last_run=data.get("last_run", ""),
            run_count=data.get("run_count", 0),
            last_status=data.get("last_status", ""),
            last_result=data.get("last_result", ""),
        )


TaskCallback = Callable[[str], Any]


class TaskScheduler:
    """Background task scheduler using cron expressions."""

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        check_interval: float = 30.0,
    ):
        self._tasks: dict[str, ScheduledTask] = {}
        self._cron_cache: dict[str, CronExpression] = {}
        self._running_task_ids: set[str] = set()
        self._callback: Optional[TaskCallback] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._check_interval = max(0.01, float(check_interval))
        self._storage_path = Path(storage_path) if storage_path else None
        if self._storage_path:
            self._load()

    def set_callback(self, callback: TaskCallback):
        """Set the callback function invoked when a task fires.

        The callback receives the task's prompt string and should
        return the result (or raise on error).
        """
        self._callback = callback

    def add_task(self, cron_expr: str, prompt: str, task_id: str = None) -> ScheduledTask:
        """Add a new scheduled task."""
        parsed = parse_cron(cron_expr)

        task_id = task_id or uuid.uuid4().hex[:8]
        task = ScheduledTask(
            id=task_id,
            cron_expr=cron_expr,
            prompt=prompt,
            enabled=True,
            created_at=datetime.now().isoformat(),
        )

        with self._lock:
            self._tasks[task_id] = task
            self._cron_cache[task_id] = parsed

        self._save()
        logger.info(f"[Scheduler] Added task {task_id}: {cron_expr} -> {prompt[:60]}")
        return task

    def remove_task(self, task_id: str) -> bool:
        """Remove a scheduled task by ID."""
        with self._lock:
            if task_id not in self._tasks:
                return False
            del self._tasks[task_id]
            self._cron_cache.pop(task_id, None)
        self._save()
        logger.info(f"[Scheduler] Removed task {task_id}")
        return True

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[ScheduledTask]:
        """List all scheduled tasks."""
        with self._lock:
            return list(self._tasks.values())

    def run_task(
        self,
        task_id: str,
        callback: TaskCallback | None = None,
    ) -> bool:
        """Execute one scheduled task immediately through its callback."""
        task = self._claim_task(task_id)
        if task is None:
            return False
        try:
            self._execute_task(task, callback=callback)
            return True
        finally:
            self._release_task(task_id)

    async def run_task_async(
        self,
        task_id: str,
        callback: TaskCallback,
    ) -> bool:
        """Execute one task without hiding cancellation in a worker thread."""
        task = self._claim_task(task_id)
        if task is None:
            return False
        try:
            await self._execute_task_async(task, callback)
            return True
        finally:
            self._release_task(task_id)

    def _claim_task(
        self,
        task_id: str,
        *,
        cron_slot: datetime | None = None,
    ) -> ScheduledTask | None:
        """Atomically claim a task, optionally enforcing one run per cron slot."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task_id in self._running_task_ids:
                return None
            if cron_slot is not None and task.last_run:
                try:
                    last_slot = datetime.fromisoformat(task.last_run).replace(
                        second=0, microsecond=0
                    )
                except ValueError:
                    last_slot = None
                if last_slot == cron_slot:
                    return None
            self._running_task_ids.add(task_id)
            return task

    def _release_task(self, task_id: str) -> None:
        with self._lock:
            self._running_task_ids.discard(task_id)

    def enable_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.enabled = True
        self._save()
        return True

    def disable_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.enabled = False
        self._save()
        return True

    def start(self):
        """Start the background scheduler thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="scheduler")
        self._thread.start()
        logger.info("[Scheduler] Started")

    def stop(self):
        """Stop the background scheduler thread."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("[Scheduler] Stopped")

    def _run_loop(self):
        """Main scheduler loop - checks every 30 seconds."""
        while self._running:
            try:
                self._check_and_run()
            except Exception as e:
                logger.error(f"[Scheduler] Error in run loop: {e}")
            self._stop_event.wait(self._check_interval)

    def _check_and_run(self):
        """Check all tasks and run those that match the current time."""
        now = datetime.now().replace(second=0, microsecond=0)

        with self._lock:
            tasks_snapshot = list(self._tasks.items())

        for task_id, task in tasks_snapshot:
            if not task.enabled:
                continue

            cron = self._cron_cache.get(task_id)
            if not cron:
                try:
                    cron = parse_cron(task.cron_expr)
                    self._cron_cache[task_id] = cron
                except ValueError as e:
                    logger.error(f"[Scheduler] Invalid cron for task {task_id}: {e}")
                    continue

            if cron.matches(now):
                claimed = self._claim_task(task_id, cron_slot=now)
                if claimed is None:
                    continue
                try:
                    self._execute_task(claimed)
                finally:
                    self._release_task(task_id)

    def _execute_task(
        self,
        task: ScheduledTask,
        callback: TaskCallback | None = None,
    ):
        """Execute a single scheduled task."""
        active_callback = callback or self._callback
        if not active_callback:
            logger.warning(f"[Scheduler] No callback set, skipping task {task.id}")
            return

        logger.info(f"[Scheduler] Running task {task.id}: {task.prompt[:60]}")
        with self._lock:
            task.last_status = "running"
        self._save()
        try:
            result = active_callback(task.prompt)
            result_text = str(result) if result is not None else ""
            from ..log.log_helpers import classify_agent_result

            status, _ = classify_agent_result(result_text)
            with self._lock:
                task.last_run = datetime.now().isoformat()
                task.run_count += 1
                task.last_status = status
                task.last_result = result_text
            logger.info(f"[Scheduler] Task {task.id} completed: {status}")
        except Exception as exc:
            logger.error(f"[Scheduler] Task {task.id} failed: {exc}")
            with self._lock:
                task.last_run = datetime.now().isoformat()
                task.run_count += 1
                task.last_status = "failed"
                task.last_result = f"error: {exc}"
        self._save()

    async def _execute_task_async(
        self,
        task: ScheduledTask,
        callback: TaskCallback,
    ) -> None:
        """Async counterpart used by request-owned manual executions."""
        logger.info(f"[Scheduler] Running task {task.id}: {task.prompt[:60]}")
        with self._lock:
            task.last_status = "running"
        self._save()
        try:
            result = callback(task.prompt)
            if inspect.isawaitable(result):
                result = await result
            result_text = str(result) if result is not None else ""
            from ..log.log_helpers import classify_agent_result

            status, _ = classify_agent_result(result_text)
            with self._lock:
                task.last_run = datetime.now().isoformat()
                task.run_count += 1
                task.last_status = status
                task.last_result = result_text
            logger.info(f"[Scheduler] Task {task.id} completed: {status}")
        except asyncio.CancelledError:
            with self._lock:
                task.last_run = datetime.now().isoformat()
                task.run_count += 1
                task.last_status = "cancelled"
                task.last_result = "[cancelled: scheduled task]"
            raise
        except Exception as exc:
            logger.error(f"[Scheduler] Task {task.id} failed: {exc}")
            with self._lock:
                task.last_run = datetime.now().isoformat()
                task.run_count += 1
                task.last_status = "failed"
                task.last_result = f"error: {exc}"
        finally:
            self._save()

    def _save(self):
        """Persist tasks to disk."""
        if not self._storage_path:
            return
        try:
            with self._lock:
                data = [task.to_dict() for task in self._tasks.values()]
            atomic_write_text(
                self._storage_path,
                json.dumps(data, ensure_ascii=False, indent=2),
            )
        except Exception as e:
            logger.error(f"[Scheduler] Save failed: {e}")

    def _load(self):
        """Load tasks from disk."""
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                task = ScheduledTask.from_dict(item)
                self._tasks[task.id] = task
                try:
                    self._cron_cache[task.id] = parse_cron(task.cron_expr)
                except ValueError:
                    pass
            logger.info(f"[Scheduler] Loaded {len(self._tasks)} tasks")
        except Exception as e:
            logger.error(f"[Scheduler] Load failed: {e}")
