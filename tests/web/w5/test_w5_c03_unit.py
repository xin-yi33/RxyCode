"""WEB-W5-C03. Checkout runs inside the sandbox. Logs and snapshots omit tokens."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_URL = "https://github.com/octocat/Hello-World"
_SHA = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _remove(docker: str, container_id: str) -> None:
    if not container_id:
        return
    subprocess.run(
        [docker, "rm", "-f", container_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _read(docker: str, container_id: str, path: str) -> str:
    done = subprocess.run(
        [docker, "exec", container_id, "python", "-c", f"print(open({path!r}).read(), end='')"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_w5_c03_contract() -> None:
    """Importing the public sample checks out that revision and can run inside the sandbox."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import WorkspaceProvision

    docker = docker_executable()
    provision = WorkspaceProvision()
    imported = None
    short = None
    try:
        imported = provision.import_repo(
            tenant_id="tenant-a",
            project_id="proj-c03",
            url=_URL,
            revision=_SHA,
            authorize_snapshot=True,
        )
        assert imported.revision == _SHA
        assert "Hello World!" in imported.test_stdout
        assert "sample-ok" in imported.test_stdout
        assert _read(docker, imported.container_id, "/tmp/ws/.revision").strip() == _SHA
        assert "Hello World!" in _read(docker, imported.container_id, "/tmp/ws/README")
        assert _read(docker, imported.container_id, "/tmp/ws/.porcelain") == ""
        assert _read(docker, imported.container_id, "/tmp/ws/.branch").strip() == "HEAD"
        inspected = subprocess.run(
            [docker, "inspect", imported.container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert inspected.returncode == 0, inspected.stderr
        info = json.loads(inspected.stdout)[0]
        assert info["HostConfig"]["NetworkMode"] == "none"
        blob = provision.read_snapshot(tenant_id="tenant-a", snapshot_id=imported.snapshot_id)
        digest = __import__("hashlib").sha256(blob).hexdigest()
        assert imported.snapshot_sha256 == digest
        provision.cleanup(tenant_id="tenant-a", workspace_id=imported.workspace_id)
        gone = subprocess.run(
            [docker, "inspect", imported.container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert gone.returncode != 0
        imported = None
        short = provision.import_repo(
            tenant_id="tenant-a",
            project_id="proj-ttl",
            url=_URL,
            revision=_SHA,
            ttl_seconds=8,
        )
        removed = False
        deadline = time.time() + 20
        while time.time() < deadline:
            inspected = subprocess.run(
                [docker, "inspect", short.container_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if inspected.returncode != 0:
                removed = True
                break
            time.sleep(0.3)
        assert removed
        short = None
    finally:
        if imported is not None:
            _remove(docker, imported.container_id)
        if short is not None:
            _remove(docker, short.container_id)


def test_w5_c03_negative() -> None:
    """A private-repo token stays out of the log and the snapshot. Other tenants cannot read it."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import RepoRefused, SnapshotRefused, WorkspaceProvision

    docker = docker_executable()
    secret = "w5c03-token-" + uuid.uuid4().hex
    poisoned = f"https://x-access-token:{secret}@github.com/octocat/Hello-World.git"
    provision = WorkspaceProvision()
    before = subprocess.run(
        [docker, "ps", "-aq", "--filter", "label=rxy.card=w5c01"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    before_ids = {line.strip() for line in before.stdout.splitlines() if line.strip()}
    for url in (
        "file:///etc/passwd",
        "https://169.254.169.254/latest/meta-data",
        "https://github.com/../../etc",
        "http://evil.example/repo.git",
        f"https://x-access-token:{secret}@evil.example/repo.git",
    ):
        with pytest.raises(RepoRefused) as refused:
            provision.import_repo(
                tenant_id="tenant-a",
                project_id="proj-bad",
                url=url,
                revision=_SHA,
                token=secret,
            )
        assert secret not in str(refused.value)
    after = subprocess.run(
        [docker, "ps", "-aq", "--filter", "label=rxy.card=w5c01"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    after_ids = {line.strip() for line in after.stdout.splitlines() if line.strip()}
    assert after_ids == before_ids
    imported = None
    try:
        imported = provision.import_repo(
            tenant_id="tenant-a",
            project_id="proj-private",
            url=poisoned,
            revision=_SHA,
            token=secret,
            authorize_snapshot=True,
        )
        assert secret not in imported.log
        assert secret not in imported.revision
        blob = provision.read_snapshot(tenant_id="tenant-a", snapshot_id=imported.snapshot_id)
        assert secret.encode() not in blob
        inspected = subprocess.run(
            [docker, "inspect", imported.container_id],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert inspected.returncode == 0, inspected.stderr
        assert secret not in inspected.stdout
        with pytest.raises(SnapshotRefused):
            provision.read_snapshot(tenant_id="tenant-b", snapshot_id=imported.snapshot_id)
        with pytest.raises(SnapshotRefused):
            provision.cleanup(tenant_id="tenant-b", workspace_id=imported.workspace_id)
        assert "Hello World!" in _read(docker, imported.container_id, "/tmp/ws/README")
        provision.cleanup(tenant_id="tenant-a", workspace_id=imported.workspace_id)
        imported = None
    finally:
        if imported is not None:
            _remove(docker, imported.container_id)
