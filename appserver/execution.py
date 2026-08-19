"""Tool / command / background-task records for PhaseG-B6."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_OUTPUT = 32_000
_SECRET_ENV = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "AUTHORIZATION",
    "ACCESS_KEY",
)

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timeout"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_text(value: str) -> str:
    safe = re.sub(
        r"(?i)(authorization|api[_-]?key|password|secret|access[_-]?token)"
        r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        value,
    )
    safe = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [REDACTED]", safe)
    return safe


def env_summary(env: dict[str, str] | None = None) -> dict[str, str]:
    source = env if env is not None else {}
    summary: dict[str, str] = {}
    for key in sorted(source):
        upper = key.upper()
        if any(token in upper for token in _SECRET_ENV):
            summary[key] = "[REDACTED]"
        else:
            summary[key] = "<set>"
    return summary


def risk_for(name: str, *, kind: str = "tool") -> str:
    lowered = name.lower()
    if kind in {"command", "background"} or any(
        token in lowered for token in ("bash", "shell", "write", "edit", "rm", "del")
    ):
        return "high"
    if any(token in lowered for token in ("read", "grep", "glob", "ls")):
        return "low"
    return "medium"


def summarize_args(arguments: Any) -> str:
    text = redact_text(str(arguments))
    if len(text) > 240:
        return text[:240] + "…"
    return text


@dataclass
class ExecutionRecord:
    task_id: str
    session_id: str
    parent_session_id: str | None = None
    kind: str = "tool"
    origin: str = "agent"
    name: str = ""
    args_summary: str = ""
    risk: str = "medium"
    cwd: str | None = None
    env_summary: dict[str, str] = field(default_factory=dict)
    status: str = "running"
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    unread: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, *, include_output: bool = True) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "kind": self.kind,
            "origin": self.origin,
            "name": self.name,
            "args_summary": self.args_summary,
            "risk": self.risk,
            "cwd": self.cwd,
            "env_summary": dict(self.env_summary),
            "status": self.status,
            "exit_code": self.exit_code,
            "truncated": self.truncated,
            "unread": self.unread,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_output:
            payload["stdout"] = self.stdout
            payload["stderr"] = self.stderr
        return payload


class ExecutionStore:
    def __init__(self, on_change: Any | None = None) -> None:
        self._items: dict[str, ExecutionRecord] = {}
        self._cancel: dict[str, asyncio.Event] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._on_change = on_change

    def _notify(self, record: ExecutionRecord) -> None:
        if self._on_change is not None:
            self._on_change(record)

    def start(
        self,
        *,
        session_id: str,
        name: str,
        kind: str = "tool",
        origin: str = "agent",
        arguments: Any = None,
        risk: str = "medium",
        cwd: str | None = None,
        parent_session_id: str | None = None,
        task_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            task_id=task_id or uuid.uuid4().hex[:12],
            session_id=session_id,
            parent_session_id=parent_session_id,
            kind=kind,
            origin=origin,
            name=name,
            args_summary=summarize_args(arguments),
            risk=risk or risk_for(name, kind=kind),
            cwd=str(Path(cwd)) if cwd else None,
            env_summary=env_summary(env),
            created_at=_now(),
            updated_at=_now(),
        )
        self._items[record.task_id] = record
        self._cancel[record.task_id] = asyncio.Event()
        self._notify(record)
        return record

    def get(self, task_id: str) -> ExecutionRecord | None:
        return self._items.get(task_id)

    def list(
        self, session_id: str, *, include_completed: bool = False
    ) -> list[ExecutionRecord]:
        values = [
            item for item in self._items.values() if item.session_id == session_id
        ]
        if not include_completed:
            values = [item for item in values if item.status not in TERMINAL]
        return sorted(values, key=lambda item: item.updated_at, reverse=True)

    def append_output(self, task_id: str, *, stdout: str = "", stderr: str = "") -> ExecutionRecord:
        record = self._require(task_id)
        if stdout:
            record.stdout, cut = _clip(record.stdout + redact_text(stdout))
            record.truncated = record.truncated or cut
            record.unread = True
        if stderr:
            record.stderr, cut = _clip(record.stderr + redact_text(stderr))
            record.truncated = record.truncated or cut
            record.unread = True
        record.updated_at = _now()
        self._notify(record)
        return record

    def set_waiting(self, task_id: str) -> ExecutionRecord:
        record = self._require(task_id)
        record.status = "waiting_approval"
        record.updated_at = _now()
        self._notify(record)
        return record

    def finish(
        self,
        task_id: str,
        status: str,
        *,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> ExecutionRecord:
        record = self._require(task_id)
        if stdout:
            self.append_output(task_id, stdout=stdout)
        if stderr:
            self.append_output(task_id, stderr=stderr)
        record.status = status
        record.exit_code = exit_code
        record.unread = status in TERMINAL
        record.updated_at = _now()
        self._procs.pop(task_id, None)
        self._notify(record)
        return record

    def mark_read(self, task_id: str) -> ExecutionRecord:
        record = self._require(task_id)
        record.unread = False
        record.updated_at = _now()
        self._notify(record)
        return record

    def request_stop(self, task_id: str) -> ExecutionRecord:
        record = self._require(task_id)
        if record.status != "running":
            raise ValueError("task is not running")
        event = self._cancel.setdefault(task_id, asyncio.Event())
        event.set()
        proc = self._procs.get(task_id)
        if proc is not None and proc.returncode is None:
            proc.kill()
        record.status = "cancelled"
        record.updated_at = _now()
        self._notify(record)
        return record

    def cancelled(self, task_id: str) -> bool:
        event = self._cancel.get(task_id)
        return bool(event and event.is_set())

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        cwd: str | None = None,
        origin: str = "user",
        background: bool = False,
        timeout: float = 30.0,
        parent_session_id: str | None = None,
    ) -> ExecutionRecord:
        env = {
            key: value
            for key, value in os.environ.items()
            if any(token in key.upper() for token in _SECRET_ENV) or key == "PATH"
        }
        record = self.start(
            session_id=session_id,
            name=command,
            kind="background" if background else "command",
            origin=origin,
            arguments={"command": command},
            risk="high" if origin == "user" else "medium",
            cwd=cwd or str(Path.cwd()),
            parent_session_id=parent_session_id,
            env=env,
        )
        if background:
            asyncio.create_task(self._run_process(record.task_id, command, cwd, timeout))
            return record
        await self._run_process(record.task_id, command, cwd, timeout)
        return self._require(record.task_id)

    async def _run_process(
        self, task_id: str, command: str, cwd: str | None, timeout: float
    ) -> None:
        try:
            if self.cancelled(task_id):
                self.finish(task_id, "cancelled")
                return
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._procs[task_id] = proc

            async def _pump(stream: asyncio.StreamReader, kind: str) -> None:
                while True:
                    chunk = await stream.read(1024)
                    if not chunk:
                        return
                    text = chunk.decode("utf-8", errors="replace")
                    if kind == "stdout":
                        self.append_output(task_id, stdout=text)
                    else:
                        self.append_output(task_id, stderr=text)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _pump(proc.stdout, "stdout"),
                        _pump(proc.stderr, "stderr"),
                        proc.wait(),
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                with contextlib.suppress(Exception):
                    leftover_out, leftover_err = await proc.communicate()
                    if leftover_out:
                        self.append_output(task_id, stdout=leftover_out.decode("utf-8", errors="replace"))
                    if leftover_err:
                        self.append_output(task_id, stderr=leftover_err.decode("utf-8", errors="replace"))
                self.finish(task_id, "timeout", exit_code=proc.returncode)
                return
            if self.cancelled(task_id) or self._require(task_id).status == "cancelled":
                self.finish(task_id, "cancelled", exit_code=proc.returncode)
                return
            status = "succeeded" if proc.returncode == 0 else "failed"
            self.finish(task_id, status, exit_code=proc.returncode)
        except Exception as exc:
            if self.cancelled(task_id) or self.get(task_id) and self.get(task_id).status == "cancelled":
                return
            self.finish(task_id, "failed", stderr=str(exc))

    def _require(self, task_id: str) -> ExecutionRecord:
        record = self._items.get(task_id)
        if record is None:
            raise KeyError(task_id)
        return record


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_OUTPUT:
        return text, False
    return text[:_MAX_OUTPUT] + "\n[truncated]", True
