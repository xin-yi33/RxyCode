"""WEB-W5-C01. Cloud exec stays inside the sandbox, and other tenants cannot attach."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _remove_container(docker: str, container_id: str) -> None:
    subprocess.run(
        [docker, "rm", "-f", container_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_w5_c01_contract(tmp_path: Path) -> None:
    """Tenant A execs in a container. Closing the run does not destroy a retained sandbox."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_server.sandbox.control import SandboxControl

    docker = docker_executable()
    nonce = uuid.uuid4().hex
    marker = tmp_path / "host-fallback.txt"
    host = socket.gethostname()
    provider = GVisorSandbox(image="python:3.12-slim", hostname="rxy-isolated")
    control = SandboxControl(provider)
    sandbox_id = ""
    container_id = ""
    try:
        sandbox = control.create_sandbox(
            tenant_id="tenant-a",
            workspace_id="ws-a",
            retain=True,
        )
        sandbox_id = sandbox.sandbox_id
        container_id = sandbox.container_id
        assert sandbox.tenant_id == "tenant-a"
        assert sandbox.workspace_id == "ws-a"
        assert control.workspaces("tenant-a")[sandbox_id] == "ws-a"
        assert sandbox_id not in control.workspaces("tenant-b")
        script = "\n".join(
            [
                "import pathlib, socket",
                "try:",
                f"    pathlib.Path({str(marker)!r}).write_text('ran-on-host')",
                "except OSError:",
                "    pass",
                f"pathlib.Path('/tmp/proof.txt').write_text({nonce!r})",
                "print('NODE=' + socket.gethostname())",
                f"print('NONCE={nonce}')",
            ]
        )
        result = control.sandboxd_exec(
            tenant_id="tenant-a",
            sandbox_id=sandbox_id,
            argv=["python", "-c", script],
        )
        assert result.exit_code == 0, result.stderr
        assert f"NONCE={nonce}" in result.stdout
        assert "NODE=rxy-isolated" in result.stdout
        assert f"NODE={host}" not in result.stdout
        assert marker.is_file() is False
        proof = subprocess.run(
            [
                docker,
                "exec",
                container_id,
                "python",
                "-c",
                "print(open('/tmp/proof.txt').read())",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proof.returncode == 0, proof.stderr
        assert proof.stdout.strip() == nonce
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
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert info["Mounts"] == []
        assert info["Config"]["Hostname"] == "rxy-isolated"
        assert info["HostConfig"]["Runtime"] in {
            sandbox.runtime,
            "runc",
            "io.containerd.runc.v2",
            "runsc",
        }
        assert info["Config"]["Labels"]["rxy.tenant"] == "tenant-a"
        assert info["Config"]["Labels"]["rxy.workspace"] == "ws-a"
        fresh = GVisorSandbox(image="python:3.12-slim")
        attached = fresh.attach(sandbox_id, tenant_id="tenant-a")
        assert attached.container_id == container_id
        run_id = control.open_run(tenant_id="tenant-a", sandbox_id=sandbox_id)
        control.close_run(tenant_id="tenant-a", run_id=run_id)
        assert control.health(tenant_id="tenant-a", sandbox_id=sandbox_id)["status"] == "running"
        control.stop(tenant_id="tenant-a", sandbox_id=sandbox_id)
        assert control.health(tenant_id="tenant-a", sandbox_id=sandbox_id)["status"] == "stopped"
        control.destroy(tenant_id="tenant-a", sandbox_id=sandbox_id)
        gone = subprocess.run(
            [docker, "inspect", container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert gone.returncode != 0
        dropped = control.create_sandbox(
            tenant_id="tenant-a",
            workspace_id="ws-drop",
            retain=False,
        )
        container_id = dropped.container_id
        drop_run = control.open_run(tenant_id="tenant-a", sandbox_id=dropped.sandbox_id)
        control.close_run(tenant_id="tenant-a", run_id=drop_run)
        dropped_gone = subprocess.run(
            [docker, "inspect", container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert dropped_gone.returncode != 0
        container_id = ""
        kinds = [row["kind"] for row in control.ledger()]
        assert "start" in kinds
        assert "bill" in kinds
        assert "destroy" in kinds
    finally:
        if container_id:
            _remove_container(docker, container_id)


def test_w5_c01_negative() -> None:
    """Tenant B knows A's sandbox id and is still refused."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.provider import AttachRefused
    from rxycode_server.sandbox.control import SandboxControl

    docker = docker_executable()
    provider = GVisorSandbox(image="python:3.12-slim", hostname="rxy-isolated")
    control = SandboxControl(provider)
    container_id = ""
    try:
        sandbox = control.create_sandbox(
            tenant_id="tenant-a",
            workspace_id="ws-a",
            retain=True,
        )
        container_id = sandbox.container_id
        fresh = GVisorSandbox(image="python:3.12-slim")
        with pytest.raises(AttachRefused) as refused:
            fresh.attach(sandbox.sandbox_id, tenant_id="tenant-b")
        assert sandbox.sandbox_id in str(refused.value)
        health = fresh.health(sandbox.sandbox_id, tenant_id="tenant-a")
        assert health["status"] == "running"
        with pytest.raises(AttachRefused):
            control.sandboxd_exec(
                tenant_id="tenant-b",
                sandbox_id=sandbox.sandbox_id,
                argv=["python", "-c", "print(1)"],
            )
        still = control.health(tenant_id="tenant-a", sandbox_id=sandbox.sandbox_id)
        assert still["status"] == "running"
        control.destroy(tenant_id="tenant-a", sandbox_id=sandbox.sandbox_id)
        container_id = ""
    finally:
        if container_id:
            _remove_container(docker, container_id)
