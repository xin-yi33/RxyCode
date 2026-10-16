"""Concurrency, cold-start samples, and sandbox GC.

A failed or expired sandbox is removed with docker rm. Cold-start percentiles
come from the measured create durations kept on this scheduler.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from rxycode_runner.sandbox.gvisor import GVisorSandbox
from rxycode_runner.sandbox.policy import load_policy, reject_if_unsafe
from rxycode_runner.sandbox.provider import ExecResult, SandboxHandle

_NONCE = re.compile(r"^[0-9a-f]{16}$")


class TopologyRefused(ValueError):
    """The compose file asks for privileged mode or omits a healthcheck."""


class CapacityFull(RuntimeError):
    """This user already holds every worker slot."""


@dataclass(frozen=True)
class ServiceSpec:
    image: str
    healthcheck: bool
    privileged: bool


@dataclass
class _Record:
    sandbox_id: str
    tenant_id: str
    deadline: float
    failed: bool
    backend: GVisorSandbox
    timer: threading.Timer | None = None


def load_compose(path: Path) -> dict[str, ServiceSpec]:
    """Read the self-hosted topology. Privileged services are refused."""
    text = Path(path).read_text(encoding="utf-8")
    services = _parse_services(text)
    if not services:
        raise TopologyRefused("compose has no services")
    for name, spec in services.items():
        if spec.privileged:
            raise TopologyRefused(f"{name} is privileged")
        if not spec.healthcheck:
            raise TopologyRefused(f"{name} has no healthcheck")
        if not spec.image:
            raise TopologyRefused(f"{name} has no image")
    return services


def _parse_services(text: str) -> dict[str, ServiceSpec]:
    in_services = False
    current: str | None = None
    found: dict[str, dict[str, object]] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0 and stripped == "services:":
            in_services = True
            current = None
            continue
        if not in_services:
            continue
        if indent == 0:
            in_services = False
            current = None
            continue
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1].strip()
            found[current] = {"image": "", "healthcheck": False, "privileged": False}
            continue
        if current is None or indent != 4 or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        slot = found[current]
        if key.strip() == "image":
            slot["image"] = value.strip().strip('"').strip("'")
        elif key.strip() == "privileged":
            slot["privileged"] = value.strip().lower() == "true"
        elif key.strip() == "healthcheck":
            slot["healthcheck"] = True
    return {
        name: ServiceSpec(
            image=str(slot["image"]),
            healthcheck=bool(slot["healthcheck"]),
            privileged=bool(slot["privileged"]),
        )
        for name, slot in found.items()
    }


class Capacity:
    """Worker occupancy plus the sandboxes this scheduler created."""

    def __init__(self) -> None:
        self.workers: list[tuple[str, str, str]] = []
        self._records: dict[str, _Record] = {}
        self._samples: list[float] = []
        self._lock = threading.Lock()

    @property
    def live_ids(self) -> list[str]:
        with self._lock:
            return list(self._records)

    def acquire(self, tenant_id: str, user_id: str, *, limit: int) -> str:
        """Occupy one worker, or refuse when this user is already at the ceiling."""
        with self._lock:
            held = sum(
                1 for owner, user, _worker in self.workers if owner == tenant_id and user == user_id
            )
            if limit < 1 or held >= limit:
                raise CapacityFull(f"{tenant_id}/{user_id} is at concurrency {limit}")
            worker_id = "worker-" + uuid.uuid4().hex[:8]
            self.workers.append((tenant_id, user_id, worker_id))
            return worker_id

    def release(self, tenant_id: str, user_id: str) -> None:
        with self._lock:
            for index in range(len(self.workers) - 1, -1, -1):
                owner, user, _worker = self.workers[index]
                if owner == tenant_id and user == user_id:
                    del self.workers[index]
                    return

    def provision(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        ttl_seconds: int | None = None,
    ) -> SandboxHandle:
        """Create one isolated sandbox and record the measured cold start."""
        started = time.perf_counter()
        policy = load_policy()
        if ttl_seconds is not None:
            policy = replace(policy, ttl_seconds=ttl_seconds)
            reject_if_unsafe(policy)
        backend = GVisorSandbox()
        handle = backend.create(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            retain=True,
            policy=policy,
        )
        elapsed = time.perf_counter() - started
        record = _Record(
            sandbox_id=handle.sandbox_id,
            tenant_id=handle.tenant_id,
            deadline=time.monotonic() + int(policy.ttl_seconds),
            failed=False,
            backend=backend,
        )
        delay = float(policy.ttl_seconds)
        record.deadline = time.monotonic() + delay
        timer = threading.Timer(delay, self._expire, args=(handle.sandbox_id,))
        timer.daemon = True
        record.timer = timer
        with self._lock:
            self._samples.append(elapsed)
            self._records[handle.sandbox_id] = record
        timer.start()
        return handle

    @contextmanager
    def sandbox(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        ttl_seconds: int | None = None,
    ) -> Iterator[SandboxHandle]:
        """Mark the sandbox failed when the caller raises after create."""
        handle = self.provision(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            ttl_seconds=ttl_seconds,
        )
        try:
            yield handle
        except Exception:
            with self._lock:
                record = self._records.get(handle.sandbox_id)
                if record is not None:
                    record.failed = True
            self.gc()
            raise

    def _expire(self, sandbox_id: str) -> None:
        """TTL callback. gc() is the reaper; the test does not have to call it."""
        with self._lock:
            record = self._records.get(sandbox_id)
            if record is not None:
                record.deadline = min(record.deadline, time.monotonic())
        self.gc()

    def gc(self) -> list[str]:
        """Remove failed sandboxes and sandboxes whose TTL has elapsed."""
        now = time.monotonic()
        with self._lock:
            chosen = [
                record
                for record in self._records.values()
                if record.failed or now >= record.deadline
            ]
        removed: list[str] = []
        for record in chosen:
            self._remove(record)
            removed.append(record.sandbox_id)
        return removed

    def destroy_all(self) -> None:
        with self._lock:
            records = list(self._records.values())
        for record in records:
            self._remove(record)

    def cold_start_samples(self) -> list[float]:
        with self._lock:
            return list(self._samples)

    def cold_start_p50(self) -> float:
        return self._percentile(50)

    def cold_start_p95(self) -> float:
        return self._percentile(95)

    def write_marker(self, handle: SandboxHandle, nonce: str) -> None:
        if not _NONCE.fullmatch(nonce):
            raise ValueError("marker nonce is refused")
        code = (
            "import pathlib; "
            f"pathlib.Path('/tmp/tenant-marker').write_text('{nonce}')"
        )
        self._exec(handle, handle.tenant_id, code)

    def read_marker(self, handle: SandboxHandle, tenant_id: str | None = None) -> str:
        owner = tenant_id or handle.tenant_id
        result = self._exec(handle, owner, "print(open('/tmp/tenant-marker').read())")
        return result.stdout.strip()

    def publish_event(self, handle: SandboxHandle, event: dict[str, object]) -> None:
        blob = base64.b64encode(json.dumps(event).encode()).decode()
        code = (
            "import base64, pathlib; "
            f"pathlib.Path('/tmp/events.json').write_bytes(base64.b64decode('{blob}'))"
        )
        self._exec(handle, handle.tenant_id, code)

    def read_events(
        self,
        handle: SandboxHandle,
        tenant_id: str | None = None,
    ) -> dict[str, object]:
        owner = tenant_id or handle.tenant_id
        result = self._exec(handle, owner, "print(open('/tmp/events.json').read())")
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise RuntimeError("sandbox event payload is not an object")
        return payload

    def _percentile(self, percentile: int) -> float:
        with self._lock:
            ordered = sorted(self._samples)
        if not ordered:
            raise RuntimeError("no cold start samples")
        index = max(0, -(-len(ordered) * percentile // 100) - 1)
        return ordered[min(index, len(ordered) - 1)]

    def _exec(self, handle: SandboxHandle, tenant_id: str, code: str) -> ExecResult:
        with self._lock:
            record = self._records[handle.sandbox_id]
            backend = record.backend
        result = backend.exec(
            handle.sandbox_id,
            tenant_id=tenant_id,
            argv=["python", "-c", code],
            timeout=30,
        )
        if result.exit_code != 0:
            detail = result.stderr or result.stdout or "sandbox exec failed"
            raise RuntimeError(detail)
        return result

    def _remove(self, record: _Record) -> None:
        with self._lock:
            current = self._records.pop(record.sandbox_id, None)
            timer = record.timer
        if timer is not None:
            timer.cancel()
        if current is None:
            return
        try:
            record.backend.destroy(record.sandbox_id, tenant_id=record.tenant_id)
        except Exception:
            record.backend._docker(["rm", "-f", record.sandbox_id], timeout=30)
