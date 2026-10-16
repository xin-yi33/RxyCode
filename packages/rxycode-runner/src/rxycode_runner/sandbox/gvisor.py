"""Docker runtimeClass adapter.

The tool process is created inside the container. runsc is used when the
daemon lists it; otherwise runc is the isolation capability. A requested
runtime that is not installed fails closed. Nothing here starts the tool as
a server-host subprocess.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from rxycode_runner.sandbox.provider import (
    AttachRefused,
    ExecResult,
    IsolationUnavailable,
    SandboxHandle,
)

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_SANDBOX = re.compile(r"^rxy-sbx-[0-9a-f]{12}$")
_IMAGE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RUNTIME = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def docker_executable() -> str:
    """Return the docker CLI. A missing CLI is an unavailable target."""
    override = os.environ.get("RXYCODE_DOCKER", "").strip()
    if override:
        if Path(override).is_file():
            return override
        raise IsolationUnavailable("docker", "RXYCODE_DOCKER is not a docker executable")
    found = shutil.which("docker")
    if found:
        return found
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = (
        Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
        Path(r"E:\DockerDesktop\resources\bin\docker.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise IsolationUnavailable("docker", "docker executable is not installed")


class GVisorSandbox:
    """runc/runsc runtimeClass backend. Labels are the tenant source of truth."""

    def __init__(
        self,
        *,
        runtime: str | None = None,
        image: str = "python:3.12-slim",
        hostname: str = "rxy-isolated",
        docker_bin: str | None = None,
    ) -> None:
        if not _IMAGE.fullmatch(image):
            raise IsolationUnavailable(image, "image name is refused")
        if not _HOSTNAME.fullmatch(hostname):
            raise IsolationUnavailable(hostname, "hostname is refused")
        if runtime is not None and not _RUNTIME.fullmatch(runtime):
            raise IsolationUnavailable("runtime", "runtime class name is refused")
        self._runtime = runtime
        self._image = image
        self._hostname = hostname
        self._docker_bin = docker_bin or docker_executable()
        if not Path(self._docker_bin).is_file():
            raise IsolationUnavailable("docker", "docker executable is not installed")

    def installed_runtimes(self) -> list[str]:
        proc = self._docker(["info", "--format", "{{json .Runtimes}}"], timeout=30)
        if proc.returncode != 0 or not proc.stdout.strip():
            detail = (proc.stderr or proc.stdout or "docker info failed").strip()
            raise IsolationUnavailable("docker", detail)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise IsolationUnavailable("docker", "docker info returned no runtime map") from exc
        if not isinstance(payload, dict):
            raise IsolationUnavailable("docker", "docker info returned no runtime map")
        return sorted(str(name) for name in payload)

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        retain: bool = True,
    ) -> SandboxHandle:
        _require_id(tenant_id)
        _require_id(workspace_id)
        runtime = self._select_runtime()
        sandbox_id = "rxy-sbx-" + uuid.uuid4().hex[:12]
        created = self._docker(
            [
                "create",
                "--name",
                sandbox_id,
                "--hostname",
                self._hostname,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "256m",
                "--pids-limit",
                "64",
                "--runtime",
                runtime,
                "--label",
                "rxy.card=w5c01",
                "--label",
                f"rxy.tenant={tenant_id}",
                "--label",
                f"rxy.workspace={workspace_id}",
                "--label",
                f"rxy.sandbox={sandbox_id}",
                "--label",
                f"rxy.retain={'true' if retain else 'false'}",
                self._image,
                "sleep",
                "infinity",
            ],
            timeout=60,
        )
        if created.returncode != 0:
            detail = (created.stderr or created.stdout or "docker create failed").strip()
            raise IsolationUnavailable(runtime, detail)
        container_id = created.stdout.strip()
        started = self._docker(["start", sandbox_id], timeout=60)
        if started.returncode != 0:
            self._docker(["rm", "-f", sandbox_id], timeout=30)
            detail = (started.stderr or started.stdout or "docker start failed").strip()
            raise IsolationUnavailable(runtime, detail)
        return SandboxHandle(
            sandbox_id=sandbox_id,
            container_id=container_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            runtime=runtime,
            retain=retain,
            status="running",
        )

    def attach(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        return self._load(sandbox_id, tenant_id=tenant_id)

    def stop(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        self._load(sandbox_id, tenant_id=tenant_id)
        stopped = self._docker(["stop", "-t", "1", sandbox_id], timeout=30)
        if stopped.returncode != 0:
            detail = (stopped.stderr or stopped.stdout or "docker stop failed").strip()
            raise IsolationUnavailable(sandbox_id, detail)
        return self._load(sandbox_id, tenant_id=tenant_id)

    def destroy(self, sandbox_id: str, *, tenant_id: str) -> None:
        self._load(sandbox_id, tenant_id=tenant_id)
        removed = self._docker(["rm", "-f", sandbox_id], timeout=30)
        if removed.returncode != 0:
            detail = (removed.stderr or removed.stdout or "docker rm failed").strip()
            raise IsolationUnavailable(sandbox_id, detail)

    def health(self, sandbox_id: str, *, tenant_id: str) -> dict[str, str]:
        handle = self._load(sandbox_id, tenant_id=tenant_id)
        return {
            "status": handle.status,
            "sandbox_id": handle.sandbox_id,
            "runtime": handle.runtime,
            "workspace_id": handle.workspace_id,
        }

    def exec(
        self,
        sandbox_id: str,
        *,
        tenant_id: str,
        argv: list[str],
        timeout: float = 60,
    ) -> ExecResult:
        handle = self._load(sandbox_id, tenant_id=tenant_id)
        if handle.status != "running":
            raise IsolationUnavailable(sandbox_id, "sandbox is not running")
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise IsolationUnavailable(sandbox_id, "tool argv is empty")
        proc = self._docker(["exec", sandbox_id, *argv], timeout=timeout)
        return ExecResult(
            sandbox_id=handle.sandbox_id,
            container_id=handle.container_id,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def _select_runtime(self) -> str:
        names = set(self.installed_runtimes())
        if self._runtime:
            if self._runtime not in names:
                raise IsolationUnavailable(
                    self._runtime,
                    f"runtime class {self._runtime} is not installed",
                )
            return self._runtime
        if "runsc" in names:
            return "runsc"
        if "runc" in names:
            return "runc"
        raise IsolationUnavailable("runtime", "no isolation runtime is installed")

    def _load(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        _require_id(tenant_id)
        if not _SANDBOX.fullmatch(sandbox_id):
            raise AttachRefused(sandbox_id, tenant_id)
        proc = self._docker(["inspect", sandbox_id], timeout=30)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise AttachRefused(sandbox_id, tenant_id)
        try:
            info = json.loads(proc.stdout)[0]
        except (json.JSONDecodeError, IndexError, TypeError) as exc:
            raise AttachRefused(sandbox_id, tenant_id) from exc
        labels = (info.get("Config") or {}).get("Labels") or {}
        owner = str(labels.get("rxy.tenant", ""))
        if owner != tenant_id:
            raise AttachRefused(sandbox_id, tenant_id)
        state = str((info.get("State") or {}).get("Status", ""))
        if state == "running":
            status = "running"
        elif state in {"exited", "dead", "created"}:
            status = "stopped"
        else:
            status = "stopped"
        runtime = str((info.get("HostConfig") or {}).get("Runtime") or "")
        return SandboxHandle(
            sandbox_id=str(labels.get("rxy.sandbox") or sandbox_id),
            container_id=str(info.get("Id") or ""),
            tenant_id=owner,
            workspace_id=str(labels.get("rxy.workspace") or ""),
            runtime=runtime,
            retain=str(labels.get("rxy.retain") or "") == "true",
            status=status,
        )

    def _docker(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self._docker_bin, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IsolationUnavailable(args[0], "docker command timed out") from exc
        except OSError as exc:
            raise IsolationUnavailable("docker", str(exc)) from exc


def _require_id(value: str) -> None:
    if not _ID.fullmatch(value):
        raise IsolationUnavailable(value, "tenant or workspace id is refused")
