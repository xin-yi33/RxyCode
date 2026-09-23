"""T4 watchdog state for appserver (heartbeat + degrade)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


def heartbeat_interval_seconds() -> float:
    raw = os.environ.get("RXYCODE_APPSERVER_HEARTBEAT_SECONDS", "15")
    return max(1.0, float(raw))


def stall_timeout_seconds() -> float:
    raw = os.environ.get("RXYCODE_APPSERVER_STALL_SECONDS", "120")
    return max(1.0, float(raw))


@dataclass
class ActiveJob:
    session_id: str
    job_id: str
    request_id: Any | None = None
    started_at: float = field(default_factory=time.monotonic)
    last_progress_at: float = field(default_factory=time.monotonic)


@dataclass
class WatchdogState:
    started_at: float = field(default_factory=time.monotonic)
    degraded: bool = False
    degrade_reason: str = ""
    jobs: dict[str, ActiveJob] = field(default_factory=dict)

    @property
    def active_jobs(self) -> int:
        return len(self.jobs)

    def register_job(
        self, job_id: str, session_id: str, request_id: Any | None = None
    ) -> None:
        self.jobs[job_id] = ActiveJob(
            session_id=session_id, job_id=job_id, request_id=request_id
        )

    def touch_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.last_progress_at = time.monotonic()

    def finish_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)

    def degrade(self, reason: str) -> None:
        self.degraded = True
        self.degrade_reason = reason

    def recover(self) -> None:
        """Clear a recoverable appserver-wide degradation latch.

        A stalled job is isolated and its worker is discarded by the server.
        Keeping this state latched forever makes every later prompt fail even
        after a fresh worker can be created. Transport objects still expose
        their own terminal ``degraded`` state; this method only resets the
        watchdog's aggregate admission gate after the server has repaired the
        failed job.
        """
        self.degraded = False
        self.degrade_reason = ""

    def stalled_jobs(self) -> list[ActiveJob]:
        """Jobs whose worker stopped heartbeating.

        Model-stream silence is not a stall: a live worker keeps
        ``last_progress_at`` fresh via ``event/heartbeat``. This fires when
        the worker process, event loop, or emit path is dead.
        """
        limit = stall_timeout_seconds()
        now = time.monotonic()
        return [j for j in self.jobs.values() if now - j.last_progress_at > limit]
