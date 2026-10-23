"""Sandbox browser profile. Host OAuth credentials are not copied in."""

from __future__ import annotations

import subprocess
import uuid

from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
from rxycode_runner.sandbox.provider import AttachRefused


class ProfileRefused(PermissionError):
    """This tenant does not own the browser profile."""


class BrowserProfile:
    def __init__(self, profile_id: str, sandbox_id: str, path: str) -> None:
        self.profile_id = profile_id
        self.sandbox_id = sandbox_id
        self.path = path


_PROFILES: dict[str, dict[str, str]] = {}


def open_profile(*, sandbox_id: str, tenant_id: str) -> BrowserProfile:
    _owned(sandbox_id, tenant_id)
    profile_id = "prf-" + uuid.uuid4().hex[:12]
    path = f"/tmp/{profile_id}"
    script = f"mkdir -p {path} && printf '%s' sandbox-only > {path}/lifetime"
    done = _shell(sandbox_id, script)
    if done.returncode != 0:
        raise ProfileRefused("profile create failed")
    _PROFILES[profile_id] = {
        "sandbox_id": sandbox_id,
        "tenant_id": tenant_id,
        "path": path,
    }
    return BrowserProfile(profile_id, sandbox_id, path)


def close_profile(*, profile_id: str, sandbox_id: str, tenant_id: str) -> None:
    row = _PROFILES.get(profile_id)
    if row is None or row["sandbox_id"] != sandbox_id or row["tenant_id"] != tenant_id:
        raise ProfileRefused("profile refused")
    _owned(sandbox_id, tenant_id)
    script = f"rm -rf {row['path']}"
    done = _shell(sandbox_id, script)
    if done.returncode != 0:
        raise ProfileRefused("profile close failed")
    del _PROFILES[profile_id]


def _owned(sandbox_id: str, tenant_id: str) -> None:
    try:
        GVisorSandbox().attach(sandbox_id, tenant_id=tenant_id)
    except AttachRefused as exc:
        raise ProfileRefused("profile refused") from exc


def _shell(sandbox_id: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker_executable(), "exec", sandbox_id, "sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
