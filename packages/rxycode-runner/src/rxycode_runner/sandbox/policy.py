"""Tenant sandbox limits. Unsafe policies are refused before a container exists."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

_MEMORY = re.compile(r"^(\d+)([kmg])?$")
_USER = re.compile(r"^\d+:\d+$")
_SCALES = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_SECRET_PARTS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "AWS_ACCESS", "AWS_SECRET", "PRIVATE_KEY")


class PolicyRejected(PermissionError):
    """The sandbox policy would weaken the OS boundary."""


@dataclass(frozen=True)
class SandboxPolicy:
    privileged: bool
    docker_socket: bool
    host_mounts: tuple[str, ...]
    network_mode: str
    block_metadata: bool
    block_private: bool
    cpu: str
    memory: str
    pids: int
    ttl_seconds: int
    user: str
    cap_drop: tuple[str, ...]
    security_opt: tuple[str, ...]


def load_policy(path: Path | None = None) -> SandboxPolicy:
    file = path or _default_path()
    text = file.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    lists: dict[str, tuple[str, ...]] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            parts = [part.strip() for part in value[1:-1].split(",") if part.strip()]
            lists[key] = tuple(parts)
            continue
        values[key] = value.strip('"').strip("'")
    policy = SandboxPolicy(
        privileged=_flag(values, "privileged"),
        docker_socket=_flag(values, "docker_socket"),
        host_mounts=lists.get("host_mounts", ()),
        network_mode=values.get("network_mode", ""),
        block_metadata=_flag(values, "block_metadata"),
        block_private=_flag(values, "block_private"),
        cpu=values.get("cpu", ""),
        memory=values.get("memory", ""),
        pids=int(values.get("pids", "0")),
        ttl_seconds=int(values.get("ttl_seconds", "0")),
        user=values.get("user", ""),
        cap_drop=lists.get("cap_drop", ()),
        security_opt=lists.get("security_opt", ()),
    )
    reject_if_unsafe(policy)
    return policy


def reject_if_unsafe(policy: SandboxPolicy) -> None:
    if policy.privileged:
        raise PolicyRejected("privileged sandboxes are refused")
    if policy.docker_socket:
        raise PolicyRejected("docker socket is refused")
    if policy.host_mounts:
        raise PolicyRejected("host mounts are refused")
    if policy.network_mode != "none":
        raise PolicyRejected("network must stay none")
    if not policy.block_metadata or not policy.block_private:
        raise PolicyRejected("metadata and private networks stay blocked")
    if policy.pids < 1 or policy.ttl_seconds < 1:
        raise PolicyRejected("pids and ttl must be finite")
    if not _USER.fullmatch(policy.user) or policy.user.startswith("0:"):
        raise PolicyRejected("sandbox user must be a non-root uid:gid")
    if "ALL" not in policy.cap_drop:
        raise PolicyRejected("capabilities must be dropped")
    memory_bytes(policy.memory)


def with_memory(policy: SandboxPolicy, memory: str) -> SandboxPolicy:
    if memory_bytes(memory) > memory_bytes(policy.memory):
        raise PolicyRejected(f"memory {memory} exceeds ceiling {policy.memory}")
    tightened = replace(policy, memory=memory)
    reject_if_unsafe(tightened)
    return tightened


def memory_bytes(text: str) -> int:
    match = _MEMORY.fullmatch(text.strip().lower())
    if match is None:
        raise PolicyRejected(f"memory {text} is refused")
    return int(match.group(1)) * _SCALES[match.group(2) or ""]


def secret_findings(env: list[str]) -> list[str]:
    found: list[str] = []
    for item in env:
        key = item.split("=", 1)[0].upper()
        if any(part in key for part in _SECRET_PARTS):
            found.append(key)
    return found


def launch(
    *,
    tenant_id: str,
    workspace_id: str,
    policy: SandboxPolicy | None = None,
    hostname: str = "rxy-isolated",
):
    """Create a sandbox with this policy. Host mounts and host env are not passed in."""
    from rxycode_runner.sandbox.egress import guard
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable

    chosen = policy or load_policy()
    reject_if_unsafe(chosen)
    guard(chosen)
    sandbox = GVisorSandbox(image="python:3.12-slim", hostname=hostname)
    handle = sandbox.create(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        retain=True,
        policy=chosen,
    )
    inspected = subprocess.run(
        [docker_executable(), "inspect", handle.sandbox_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if inspected.returncode != 0:
        sandbox.destroy(handle.sandbox_id, tenant_id=tenant_id)
        raise PolicyRejected(inspected.stderr.strip() or "sandbox inspect failed")
    info = json.loads(inspected.stdout)[0]
    if secret_findings(list(info.get("Config", {}).get("Env") or [])):
        sandbox.destroy(handle.sandbox_id, tenant_id=tenant_id)
        raise PolicyRejected("secret in sandbox environment")
    return handle


def _default_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "compose" / "sandbox-policy.yaml"
        if candidate.is_file():
            return candidate
    raise PolicyRejected("sandbox-policy.yaml is missing")


def _flag(values: dict[str, str], key: str) -> bool:
    text = values.get(key, "")
    if text == "true":
        return True
    if text == "false":
        return False
    raise PolicyRejected(f"{key} must be true or false")
