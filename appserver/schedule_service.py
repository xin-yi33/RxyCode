"""PhaseG-B16 asyncio scheduler. No OS cron/launchd/Task Scheduler."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from scheduler.rules import next_fire, parse_rule
from utils.atomic_file import atomic_write_text

ACTIONS = ("session", "command", "skill")
MAX_PARALLEL = 2
# F4-6：无消费窗口时的 execution 标记（测试包钉死唯一真值）。
# "turn" 只表示投递给了已附着的消费窗口，由该窗口既有消费链执行。
# 本模块不构造无人窗口的 prompt。
SCHEDULED_PENDING = "scheduled_pending"


class ScheduleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def schedule_tick_seconds(default: float = 30.0) -> float:
    """Read ``RXYCODE_APPSERVER_SCHEDULE_TICK_SECONDS``.

    废弃代码（2026-10-08 版）：appserver 把 30 秒写死传给 schedule_loop。
    已路由到该环境变量；未设置、无法解析、非有限数或非正数时仍用调用方默认值。
    这是调度节拍，不是 config.timeouts 注册表里的用户时钟。
    """
    raw = os.environ.get("RXYCODE_APPSERVER_SCHEDULE_TICK_SECONDS", "")
    if not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def _revive_orphans_on_restore() -> bool:
    """None 形参走 config。缺省 False，与重启后只标记 orphan 的旧行为一致。"""
    try:
        from config.settings import load_config
    except ImportError:
        from RxyCode.RxyCode1_1_0.config.settings import load_config
    cfg = load_config() or {}
    schedule = cfg.get("schedule") if isinstance(cfg, dict) else None
    if not isinstance(schedule, dict):
        return False
    return bool(schedule.get("revive_orphans_on_restore", False))


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
        # 废弃代码（2026-09-22）：多窗口时构造函数无条件 restore_after_restart。
        # 第二扇窗口会把第一扇正在跑的 /loop 标成 recovery_required。
        # self.restore_after_restart()
        if os.environ.get("RXYCODE_APPSERVER_MULTI") != "1":
            self.restore_after_restart()
        # None: this process may fire every job. A set: only this window's sessions.
        self.local_session_ids: set[str] | None = None

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

    def restore_after_restart(self, *, revive_orphans: bool | None = None) -> list[dict[str, Any]]:
        # 废弃代码（2026-10-08 版）：重启只把 running 标成 recovery_required，不补发。
        # 已路由到 revive_orphans。None 读 schedule.revive_orphans_on_restore，默认 False，
        # 该路径与旧行为逐字节一致。True 时对每个仍启用的 orphan fire-once，不补积压。
        if revive_orphans is None:
            revive_orphans = _revive_orphans_on_restore()
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
        if revive_orphans:
            for orphan_job in orphans:
                job_id = str(orphan_job["id"])
                live = self._jobs.get(job_id) or {}
                if not live.get("enabled", True):
                    self._audit_row(action="revive", job_id=job_id, status="skipped")
                    continue
                try:
                    self.revive_orphan(job_id)
                except ScheduleError:
                    self._audit_row(action="revive", job_id=job_id, status="skipped")
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

    def revive_orphan(self, job_id: str, *, now=None) -> dict[str, Any]:
        """复活单个 orphan：立即 fire-once（本轮只跑一次，不补积压），清除 orphan。

        非 orphan → raise ScheduleError("SCHEDULE_NOT_ORPHAN", "job is not an orphan")
        （message 含小写 "orphan"，pytest match 锚）。
        ``execution == "turn"`` 只表示补发进了已附着窗口的队列。
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise ScheduleError("SCHEDULE_NOT_FOUND", f"unknown schedule: {job_id}")
        if not (job.get("orphan") or job.get("run_status") == "recovery_required"):
            raise ScheduleError("SCHEDULE_NOT_ORPHAN", "job is not an orphan")
        if not job.get("enabled", True):
            raise ScheduleError("SCHEDULE_DISABLED", f"{job_id} is disabled")
        stamp = now or _now()
        # Dedupe this attempt, not every past success. A persisted inflight_slot
        # is the round that died before its fire row. No inflight slot plus an
        # existing ok fire means the tick already finished; keep that row and
        # do not append another. A crash that never succeeded still dispatches.
        slot = job.get("inflight_slot")
        delivered_slot = slot or job.get("next_fire")
        if slot:
            should_dispatch = not self._slot_delivered(job_id, slot)
        else:
            should_dispatch = not self._slot_delivered(job_id, None)
        result = job.get("last_result")
        if should_dispatch:
            # 同步补投。不走 fire()/_sync：在已有事件循环里会留下未 await 的协程，
            # 并且失败时已经把 orphan 清掉。失败必须原样抛出，让 restore 记 skipped。
            result = self._run_action(job)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise ScheduleError("SCHEDULE_ASYNC", "revive dispatch must be synchronous")
        job["orphan"] = False
        job["run_status"] = "idle"
        self._running.discard(job_id)
        if (job.get("rule") or {}).get("once"):
            job["enabled"] = False
            job["next_fire"] = None
        else:
            # 从 now 重算，不回填已经错过的 interval。
            job["next_fire"] = _iso(next_fire(job["rule"], stamp))
        job["last_result"] = result
        job["inflight_slot"] = None
        if should_dispatch:
            self._audit_row(
                action="fire",
                job_id=job_id,
                status="ok",
                result=result,
                slot=delivered_slot,
            )
        self._audit_row(action="revive", job_id=job_id, status="revived")
        self._save()
        return {"id": job_id, "ok": True, "orphan": False, "dispatch": result}

    def _slot_delivered(self, job_id: str, slot: str | None) -> bool:
        """True when this job already has an ok fire.

        A slot limits the match to that round. None means any ok fire.
        """
        for row in self._audit:
            if row.get("action") != "fire" or row.get("status") != "ok":
                continue
            if row.get("job_id") != job_id:
                continue
            if slot is None or row.get("slot") == slot:
                return True
        return False

    def _open_inflight(self, job: dict[str, Any]) -> None:
        """Save the slot about to be delivered. Revive replays only this slot."""
        job["run_status"] = "running"
        job["inflight_slot"] = job.get("next_fire")
        self._save()

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

    def _job_is_local(self, job_id: str) -> bool:
        owned = self.local_session_ids
        if owned is None:
            return True
        job = self._jobs.get(job_id) or {}
        session_id = str((job.get("action") or {}).get("session_id") or "")
        return session_id in owned

    async def tick_async(self, now: datetime | None = None) -> list[dict[str, Any]]:
        stamp = now or _now()
        due_ids = [job_id for job_id in self.due(stamp) if job_id not in self._queue and job_id not in self._running and self._job_is_local(job_id)]
        ready = due_ids[: self.max_parallel]
        for extra in due_ids[self.max_parallel :]:
            if extra not in self._queue:
                self._queue.append(extra)
        self._save()
        started = [asyncio.create_task(self.fire_async(job_id, now=stamp)) for job_id in ready]
        drain: list[str] = []
        while self._queue and len(drain) + len(self._running) + len(started) < self.max_parallel:
            nxt = self._queue.pop(0)
            if self._job_is_local(nxt):
                drain.append(nxt)
        started.extend(asyncio.create_task(self.fire_async(job_id, now=stamp)) for job_id in drain)
        if started:
            return list(await asyncio.gather(*started))
        return []

    async def _execute_async(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        job_id = job["id"]
        self._running.add(job_id)
        slot = job.get("next_fire")
        self._open_inflight(job)
        async with self._sem:
            try:
                result = self._run_action(job)
                if inspect.isawaitable(result):
                    result = await result
                job["run_status"] = "idle"
                job["inflight_slot"] = None
                job["last_result"] = result
                if (job.get("rule") or {}).get("once"):
                    job["enabled"] = False
                    job["next_fire"] = None
                else:
                    job["next_fire"] = _iso(next_fire(job["rule"], now))
                self._audit_row(
                    action="fire", job_id=job_id, status="ok", result=result, slot=slot
                )
                return {"ok": True, "id": job_id, "result": result}
            except ScheduleError as exc:
                job["run_status"] = "failed"
                job["inflight_slot"] = None
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
                job["inflight_slot"] = None
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
        usage = getattr(session, "usage", None) or {}
        budget = getattr(session, "budget", None) or {}
        if int(usage.get("budget_exhausted") or 0):
            raise ScheduleError("SCHEDULE_BUDGET", "session budget exhausted")
        used = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        limit = int(budget.get("max_tokens") or 0)
        if limit and used >= limit:
            raise ScheduleError("SCHEDULE_BUDGET", "session token budget exhausted")
        # 裁定 2026-10-08：没有 delivery_approval_id 时照旧询问权限档。
        # 默认 ask 档因此仍是 SCHEDULE_DENIED。批准只来自 schedule/create 记下的显式 allow，
        # 用一次就消费，成功后再签下一轮，避免 interval 第二次被误拒。
        approval_id = str(job.get("delivery_approval_id") or "").strip() or None
        verdict = self.permissions.evaluate(
            action="session.prompt",
            actor="scheduler",
            session_id=session.session_id,
            workspace=workspace,
            scope=workspace,
            approval_id=approval_id,
        )
        if verdict != "allow":
            raise ScheduleError("SCHEDULE_DENIED", "B5 permission denied scheduled action")
        if approval_id is not None and hasattr(self.permissions, "decide"):
            renewed = self.permissions.decide(
                session_id=session.session_id,
                action="session.prompt",
                actor="scheduler",
                scope=workspace,
                decision="allow",
                reason="schedule_delivery_next",
                consumed=False,
            )
            job["delivery_approval_id"] = str(renewed.get("approval_id") or "")
        text = str(action.get("message") or action.get("command") or action.get("skill") or "")
        # enqueue_scheduled 签名不动。去重沿用持久化 next_fire 与 session/events cursor。
        delivered = self.sessions.enqueue_scheduled(session.session_id, kind=kind, text=text)
        probe = getattr(self.sessions, "is_consumer_attached", None)
        attached = bool(probe(session.session_id)) if callable(probe) else False
        # 废弃代码（2026-10-08 版）：成功入队只返回 delivered，看不出有没有消费窗口。
        # 已路由到 execution。turn = 投递给已附着窗口；scheduled_pending = 已入队但无窗口。
        # 这里不发起 prompt。
        return {
            "kind": kind,
            "delivered": True,
            **delivered,
            "execution": "turn" if attached else SCHEDULED_PENDING,
        }

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


async def schedule_loop(service: ScheduleService, sleep: Callable[[float], Awaitable[None]], interval_s: float = 1.0) -> None:
    # 废弃代码（2026-09-22）：每个窗口的循环一启动就 reclaim_orphans。
    # 多窗口时那会把另一扇窗口正在跑的 /loop 标成孤儿再重跑。
    # service.reclaim_orphans()
    if service.local_session_ids is None:
        service.reclaim_orphans()
    while True:
        try:
            await service.tick_async()
        except Exception:
            service._audit_row(action="loop", status="tick-failed")
        await sleep(interval_s)
