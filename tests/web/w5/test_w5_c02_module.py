"""WEB-W5-C02. A sandbox over its memory quota dies. Another tenant still runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _remove(docker: str, container_id: str) -> None:
    subprocess.run(
        [docker, "rm", "-f", container_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_w5_c02_integration() -> None:
    """Allocating past the tenant quota is killed. Tenant B and this process stay up."""
    from dataclasses import replace

    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import launch, load_policy, with_memory

    docker = docker_executable()
    policy = load_policy()
    tight = with_memory(policy, "128m")
    assert tight.memory == "128m"
    with_memory_refused = False
    try:
        with_memory(policy, "999g")
    except Exception:
        with_memory_refused = True
    assert with_memory_refused is True
    provider = GVisorSandbox(image="python:3.12-slim")
    first = ""
    second = ""
    try:
        limited = launch(tenant_id="tenant-a", workspace_id="ws-oom", policy=tight)
        first = limited.container_id
        bomb = provider.exec(
            limited.sandbox_id,
            tenant_id="tenant-a",
            argv=["python", "-c", "print(len(bytearray(256 * 1024 * 1024)))"],
            timeout=30,
        )
        assert bomb.exit_code != 0
        assert "268435456" not in bomb.stdout
        other = launch(
            tenant_id="tenant-b",
            workspace_id="ws-other",
            policy=replace(policy, ttl_seconds=policy.ttl_seconds),
        )
        second = other.container_id
        alive = provider.exec(
            other.sandbox_id,
            tenant_id="tenant-b",
            argv=["python", "-c", "print('tenant-b-alive')"],
        )
        assert alive.exit_code == 0, alive.stderr
        assert "tenant-b-alive" in alive.stdout
        assert provider.health(other.sandbox_id, tenant_id="tenant-b")["status"] == "running"
        provider.destroy(limited.sandbox_id, tenant_id="tenant-a")
        provider.destroy(other.sandbox_id, tenant_id="tenant-b")
        first = ""
        second = ""
    finally:
        if first:
            _remove(docker, first)
        if second:
            _remove(docker, second)
