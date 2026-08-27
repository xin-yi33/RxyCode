"""PhaseG-B16 asyncio scheduler. No OS cron/launchd/Task Scheduler."""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from scheduler.rules import next_fire, parse_rule
from utils.atomic_file import atomic_write_text

ACTIONS = ("session", "command", "skill")
MAX_PARALLEL = 2


class ScheduleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ScheduleService:
    def __init__(
        self,
        path: Path | None = None,
        *,
        persistent: bool = True,
        sessions: Any = None,
        permissions: Any = None,
        task_store: Any = None,
        max_parallel: int = MAX_PARALLEL,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.persistent = persistent
        self.path = path or Path("desktop") / "schedules.json"
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions = sessions
        self.permissions = permissions
        self.task_store = task_store
        self.max_parallel = max(1, int(max_parallel))
        self._runner = runner
        self._jobs: dict[str, dict[str, Any]] = {}
        self._queue: list[str] = []
        self._running: set[str] = set()
        self._audit: list[dict[str, Any]] = []
        self._sem = asyncio.Semaphore(self.max_parallel)
        self._load()
        self.restore_after_restart()

    def _load(self) -> None:
        if not self.persistent or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        jobs = raw.get("jobs") if isinstance(raw, dict) else raw
        if isinstance(jobs, list):
            for item in jobs:
                if isinstance(item, dict) and item.get("id"):
                    self._jobs[str(item["id"])] = item
        if isinstance(raw, dict):
            if isinstance(raw.get("audit"), list):
                self._audit = list(raw["audit"])[-200:]
            if isinstance(raw.get("queue"), list):
                self._queue = [str(item) for item in raw["queue"]]

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps(
            {"jobs": list(self._jobs.values()), "audit": self._audit[-200:], "queue": list(self._queue)},
            indent=2,
            ensure_ascii=False,
        )
        atomic_write_text(self.path, payload)

    def _audit_row(self, **fields: Any) -> None:
        self._audit.append({"at": _iso(_now()), **fields})
        self._save()

    def _validate_action(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str((action or {}).get("kind") or "")
        if kind not in ACTIONS:
            raise ScheduleError("SCHEDULE_ACTION_INVALID", "action kind must be session, command, or skill")
        if not action.get("session_id"):
            raise ScheduleError("SCHEDULE_ACTION_INVALID", "action requires session_id for B5 Thread")
        return dict(action)

    def restore_after_restart(self) -> list[dict[str, Any]]:
        orphans = []
        for job in self._jobs.values():
            if job.get("run_status") == "running":
                job["run_status"] = "recovery_required"
                job["orphan"] = True
                orphans.append(dict(job))
                self._audit_row(action="recover", job_id=job["id"], status="recovery_required")
        self._running.clear()
        self._queue = []
        self._save()
        return orphans

    def reclaim_orphans(self) -> list[dict[str, Any]]:
        reclaimed = []
        for job in self._jobs.values():
            if job.get("orphan") or job.get("run_status") == "recovery_required":
                job["orphan"] = False
                job["run_status"] = "idle"
                reclaimed.append(job["id"])
                self._audit_row(action="reclaim", job_id=job["id"], status="idle")
        self._save()
        return [{"id": job_id} for job_id in reclaimed]

    def list_jobs(self) -> dict[str, Any]:
        return {"jobs": list(self._jobs.values()), "queue": list(self._queue), "running": sorted(self._running)}

    def create(
        self,
        *,
        rule: dict[str, Any],
        action: dict[str, Any],
        enabled: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        parsed = parse_rule(rule)
        checked = self._validate_action(action)
        job_id = "sch_" + uuid.uuid4().hex[:10]
        stamp = now or _now()
        job = {
            "id": job_id,
            "rule": parsed,
            "action": checked,
            "enabled": bool(enabled),
            "next_fire": _iso(next_fire(parsed, stamp)),
            "run_status": "idle",
            "orphan": False,
            "created_at": _iso(stamp),
            "last_result": None,
        }
        self._jobs[job_id] = job
        self._audit_row(action="create", job_id=job_id)
        self._save()
        return dict(job)

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise ScheduleError("SCHEDULE_NOT_FOUND", f"unknown schedule: {job_id}")
        if "rule" in fields and fields["rule"] is not None:
            job["rule"] = parse_rule(fields["rule"])
            job["next_fire"] = _iso(next_fire(job["rule"], _now()))
        if "action" in fields and fields["action"] is not None:
            job["action"] = self._validate_action(fields["action"])
        if "enabled" in fields and fields["enabled"] is not None:
            job["enabled"] = bool(fields["enabled"])
        self._audit_row(action="update", job_id=job_id)
        self._save()
        return dict(job)

    def delete(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.pop(job_id, None)
        if job is None:
            raise ScheduleError("SCHEDULE_NOT_FOUND", f"unknown schedule: {job_id}")
        self._queue = [item for item in self._queue if item != job_id]
        self._running.discard(job_id)
        self._audit_row(action="delete", job_id=job_id)
        self._save()
        return {"ok": True, "id": job_id}

    def toggle(self, job_id: str, enabled: bool | None = None) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise ScheduleError("SCHEDULE_NOT_FOUND", f"unknown schedule: {job_id}")
        job["enabled"] = (not job.get("enabled")) if enabled is None else bool(enabled)
        if not job["enabled"]:
            self._queue = [item for item in self._queue if item != job_id]
        self._audit_row(action="toggle", job_id=job_id, enabled=job["enabled"])
        self._save()
        return dict(job)

    def due(self, now: datetime | None = None) -> list[str]:
        stamp = now or _now()
        due_ids = []
        for job in self._jobs.values():
            if not job.get("enabled"):
                continue
            nxt = datetime.fromisoformat(job["next_fire"]) if job.get("next_fire") else None
            if nxt is not None and nxt.tzinfo is not None:
                nxt = nxt.replace(tzinfo=None)
            if nxt is not None and nxt <= stamp:
                due_ids.append(job["id"])
        return due_ids

    def fire(self, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        return self._sync(self.fire_async(job_id, now=now))

    def tick(self, now: datetime | None = None) -> list[dict[str, Any]]:
        return self._sync(self.tick_async(now))

    def _sync(self, coro: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise ScheduleError("SCHEDULE_ASYNC", "call fire_async/tick_async inside a running loop")

    async def fire_async(self, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise ScheduleError("SCHEDULE_NOT_FOUND", f"unknown schedule: {job_id}")
        if not job.get("enabled"):
            raise ScheduleError("SCHEDULE_DISABLED", f"{job_id} is disabled")
        if job_id in self._running:
            return {"ok": False, "queued": False, "id": job_id, "reason": "already-running"}
        if len(self._running) >= self.max_parallel or self._sem.locked() and self._sem._value == 0:
            if job_id not in self._queue:
                self._queue.append(job_id)
                self._save()
            self._audit_row(action="queue", job_id=job_id)
            return {"ok": False, "queued": True, "id": job_id, "queue": list(self._queue)}
        return await self._execute_async(job, now or _now())

    async def tick_async(self, now: datetime | None = None) -> list[dict[str, Any]]:
        stamp = now or _now()
        due_ids = [job_id for job_id in self.due(stamp) if job_id not in self._queue and job_id not in self._running]
        ready = due_ids[: self.max_parallel]
        for extra in due_ids[self.max_parallel :]:
            if extra not in self._queue:
                self._queue.append(extra)
        self._save()
        started = [asyncio.create_task(self.fire_async(job_id, now=stamp)) for job_id in ready]
        drain: list[str] = []
        while self._queue and len(drain) + len(self._running) + len(started) < self.max_parallel:
            drain.append(self._queue.pop(0))
        started.extend(asyncio.create_task(self.fire_async(job_id, now=stamp)) for job_id in drain)
        if started:
            return list(await asyncio.gather(*started))
        return []

    async def _execute_async(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        job_id = job["id"]
        self._running.add(job_id)
        job["run_status"] = "running"
        self._save()
        async with self._sem:
            try:
                result = self._run_action(job)
                if inspect.isawaitable(result):
                    result = await result
                job["run_status"] = "idle"
                job["last_result"] = result
                if (job.get("rule") or {}).get("once"):
                    job["enabled"] = False
                    job["next_fire"] = None
                else:
                    job["next_fire"] = _iso(next_fire(job["rule"], now))
                self._audit_row(action="fire", job_id=job_id, status="ok", result=result)
                return {"ok": True, "id": job_id, "result": result}
            except ScheduleError as exc:
                job["run_status"] = "failed"
                job["last_result"] = {"error_code": exc.code, "message": exc.message}
                if (job.get("rule") or {}).get("once"):
                    job["enabled"] = False
                    job["next_fire"] = None
                else:
                    job["next_fire"] = _iso(next_fire(job["rule"], now))
                self._audit_row(action="fire", job_id=job_id, status="failed", error_code=exc.code)
                return {"ok": False, "id": job_id, "error_code": exc.code, "message": exc.message}
            except Exception as exc:
                job["run_status"] = "failed"
                job["last_result"] = {"error_code": "SCHEDULE_FAILED", "message": str(exc)}
                if (job.get("rule") or {}).get("once"):
                    job["enabled"] = False
                    job["next_fire"] = None
                else:
                    job["next_fire"] = _iso(next_fire(job["rule"], now))
                self._audit_row(action="fire", job_id=job_id, status="failed", error_code="SCHEDULE_FAILED")
                return {"ok": False, "id": job_id, "error_code": "SCHEDULE_FAILED", "message": str(exc)}
            finally:
                self._running.discard(job_id)
                self._save()

    def _run_action(self, job: dict[str, Any]) -> Any:
        action = job.get("action") or {}
        kind = str(action.get("kind") or "")
        if self.permissions is None or self.sessions is None:
            raise ScheduleError("SCHEDULE_DENIED", "B5 session/permission required; cannot bypass")
        session_id = str(action.get("session_id") or "")
        session = self.sessions.get(session_id)
        if session is None:
            raise ScheduleError("SCHEDULE_NO_THREAD", f"unknown session {session_id}")
        if getattr(session, "trashed_at", None):
            session = self.sessions.restore(session_id)
        workspace = str(getattr(session, "workspace_root", None) or ".")
        verdict = self.permissions.evaluate(
            action="session.prompt",
            actor="scheduler",
            session_id=session.session_id,
            workspace=workspace,
            scope=workspace,
        )
        if verdict != "allow":
            raise ScheduleError("SCHEDULE_DENIED", "B5 permission denied scheduled action")
        usage = getattr(session, "usage", None) or {}
        budget = getattr(session, "budget", None) or {}
        if int(usage.get("budget_exhausted") or 0):
            raise ScheduleError("SCHEDULE_BUDGET", "session budget exhausted")
        used = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        limit = int(budget.get("max_tokens") or 0)
        if limit and used >= limit:
            raise ScheduleError("SCHEDULE_BUDGET", "session token budget exhausted")
        text = str(action.get("message") or action.get("command") or action.get("skill") or "")
        delivered = self.sessions.enqueue_scheduled(session.session_id, kind=kind, text=text)
        return {"kind": kind, "delivered": True, **delivered}

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


async def schedule_loop(service: ScheduleService, sleep: Callable[[float], Awaitable[None]], interval_s: float = 1.0) -> None:
    service.reclaim_orphans()
    while True:
        try:
            await service.tick_async()
        except Exception:
            service._audit_row(action="loop", status="tick-failed")
        await sleep(interval_s)
