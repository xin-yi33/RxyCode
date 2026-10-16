"""WEB-W5-C02. A cloud sandbox cannot see the host or reach metadata."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

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


def test_w5_c02_contract(tmp_path: Path) -> None:
    """Host /etc stand-in and another project are not visible inside the sandbox."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import launch, load_policy

    docker = docker_executable()
    nonce = uuid.uuid4().hex
    other_nonce = uuid.uuid4().hex
    host_etc = tmp_path / "etc" / "hostname"
    host_etc.parent.mkdir()
    host_etc.write_text(nonce, encoding="utf-8")
    other = tmp_path / "other-project" / "secret.txt"
    other.parent.mkdir()
    other.write_text(other_nonce, encoding="utf-8")
    policy = load_policy()
    assert policy.privileged is False
    assert policy.docker_socket is False
    assert policy.host_mounts == ()
    assert policy.network_mode == "none"
    os.environ["RXY_API_KEY"] = nonce
    container_id = ""
    ttl_id = ""
    try:
        handle = launch(tenant_id="tenant-a", workspace_id="ws-c02", policy=policy)
        container_id = handle.container_id
        provider = GVisorSandbox(image="python:3.12-slim")
        script = "\n".join(
            [
                "import pathlib",
                "names = []",
                "for path in (",
                f"    {str(host_etc)!r},",
                f"    {str(other)!r},",
                "    '/etc/rxy-host-only',",
                "):",
                "    file = pathlib.Path(path)",
                "    names.append(file.read_text() if file.is_file() else '')",
                "print('HOST=' + names[0])",
                "print('OTHER=' + names[1])",
                "print('MARKER=' + names[2])",
                "print('OS=' + pathlib.Path('/etc/os-release').read_text().splitlines()[0])",
                "print('NODE=' + pathlib.Path('/etc/hostname').read_text().strip())",
            ]
        )
        result = provider.exec(
            handle.sandbox_id,
            tenant_id="tenant-a",
            argv=["python", "-c", script],
        )
        assert result.exit_code == 0, result.stderr
        assert nonce not in result.stdout
        assert other_nonce not in result.stdout
        assert "HOST=" in result.stdout
        assert "OTHER=" in result.stdout
        assert "NODE=rxy-isolated" in result.stdout
        assert "Windows" not in result.stdout
        inspected = subprocess.run(
            [docker, "inspect", container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert inspected.returncode == 0, inspected.stderr
        info = json.loads(inspected.stdout)[0]
        assert info["HostConfig"]["Privileged"] is False
        assert info["Mounts"] == []
        assert info["Config"]["User"] == "65534:65534"
        env = "\n".join(info["Config"].get("Env") or [])
        assert nonce not in env
        assert "RXY_API_KEY" not in env
        provider.destroy(handle.sandbox_id, tenant_id="tenant-a")
        container_id = ""
        short = replace(policy, ttl_seconds=1)
        ttl = launch(tenant_id="tenant-a", workspace_id="ws-ttl", policy=short)
        ttl_id = ttl.container_id
        status = "running"
        deadline = time.time() + 8
        while time.time() < deadline:
            status = provider.health(ttl.sandbox_id, tenant_id="tenant-a")["status"]
            if status == "stopped":
                break
            time.sleep(0.3)
        assert status == "stopped"
        provider.destroy(ttl.sandbox_id, tenant_id="tenant-a")
        ttl_id = ""
    finally:
        os.environ.pop("RXY_API_KEY", None)
        if container_id:
            _remove(docker, container_id)
        if ttl_id:
            _remove(docker, ttl_id)


def test_w5_c02_negative(tmp_path: Path) -> None:
    """Metadata and the Docker socket stay blocked. Privileged and host mounts are refused."""
    from dataclasses import replace

    from rxycode_runner.sandbox.egress import METADATA_IP, SOCKET_PATH, destination_blocked
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import PolicyRejected, launch, load_policy

    docker = docker_executable()
    policy = load_policy()
    assert destination_blocked(METADATA_IP) is True
    assert destination_blocked(SOCKET_PATH) is True
    workspace = "ws-neg-" + uuid.uuid4().hex[:8]
    for bad in (
        replace(policy, privileged=True),
        replace(policy, docker_socket=True),
        replace(policy, host_mounts=("/var/run/docker.sock",)),
    ):
        with pytest.raises(PolicyRejected):
            launch(tenant_id="tenant-a", workspace_id=workspace, policy=bad)
    listed = subprocess.run(
        [docker, "ps", "-aq", "--filter", f"label=rxy.workspace={workspace}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert listed.stdout.strip() == ""
    container_id = ""
    try:
        handle = launch(tenant_id="tenant-a", workspace_id="ws-c02n", policy=policy)
        container_id = handle.container_id
        provider = GVisorSandbox(image="python:3.12-slim")
        script = "\n".join(
            [
                "import pathlib, socket",
                "meta = 0",
                "try:",
                "    socket.create_connection(('169.254.169.254', 80), 2)",
                "    meta = 1",
                "except Exception:",
                "    meta = 0",
                "sock = 1 if pathlib.Path('/var/run/docker.sock').exists() else 0",
                "print(f'META={meta} SOCK={sock}')",
            ]
        )
        result = provider.exec(
            handle.sandbox_id,
            tenant_id="tenant-a",
            argv=["python", "-c", script],
        )
        assert result.exit_code == 0, result.stderr
        assert "META=0" in result.stdout
        assert "SOCK=0" in result.stdout
        provider.destroy(handle.sandbox_id, tenant_id="tenant-a")
        container_id = ""
    finally:
        if container_id:
            _remove(docker, container_id)
