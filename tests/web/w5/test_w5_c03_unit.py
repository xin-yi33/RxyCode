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
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _sample_bundle(tmp_path: Path) -> tuple[str, bytes]:
    repo = tmp_path / "sample"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "test_sample.py").write_bytes(b"print('sample-ok')\n")
    (repo / "base.txt").write_bytes(b"fixed-base\n")
    _git(repo, "add", "test_sample.py", "base.txt")
    _git(
        repo,
        "-c",
        "user.email=c03@example.test",
        "-c",
        "user.name=c03",
        "commit",
        "-m",
        "sample",
    )
    sha = _git(repo, "rev-parse", "HEAD")
    bundle = tmp_path / "sample.bundle"
    _git(repo, "bundle", "create", str(bundle), "--all")
    return sha, bundle.read_bytes()


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


def test_w5_c03_contract(tmp_path: Path) -> None:
    """A public sample checkout inside the sandbox matches the commit and its test runs."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import WorkspaceProvision

    docker = docker_executable()
    sha, bundle = _sample_bundle(tmp_path)
    provision = WorkspaceProvision()
    imported = None
    short = None
    try:
        imported = provision.import_repo(
            tenant_id="tenant-a",
            project_id="proj-c03",
            url="https://github.com/rxycode/w5-sample",
            revision=sha,
            bundle=bundle,
            authorize_snapshot=True,
        )
        assert imported.revision == sha
        assert "sample-ok" in imported.test_stdout
        assert _read(docker, imported.container_id, "/tmp/ws/.revision").strip() == sha
        assert _read(docker, imported.container_id, "/tmp/ws/base.txt") == "fixed-base\n"
        assert _read(docker, imported.container_id, "/tmp/ws/.porcelain") == ""
        assert _read(docker, imported.container_id, "/tmp/ws/.branch").strip() == "HEAD"
        ran = subprocess.run(
            [docker, "exec", imported.container_id, "python", "/tmp/ws/test_sample.py"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert ran.returncode == 0, ran.stderr
        assert "sample-ok" in ran.stdout
        blob = provision.read_snapshot(tenant_id="tenant-a", snapshot_id=imported.snapshot_id)
        assert imported.snapshot_sha256 == __import__("hashlib").sha256(blob).hexdigest()
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
            url="https://github.com/rxycode/w5-sample",
            revision=sha,
            bundle=bundle,
            ttl_seconds=8,
        )
        status = "running"
        deadline = time.time() + 16
        while time.time() < deadline:
            inspected = subprocess.run(
                [docker, "inspect", short.container_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if inspected.returncode != 0:
                status = "gone"
                break
            info = json.loads(inspected.stdout)[0]
            state = info["State"]["Status"]
            if state in {"exited", "dead"}:
                status = "stopped"
                break
            time.sleep(0.3)
        assert status in {"stopped", "gone"}
        provision.cleanup(tenant_id="tenant-a", workspace_id=short.workspace_id)
        short = None
    finally:
        if imported is not None:
            _remove(docker, imported.container_id)
        if short is not None:
            _remove(docker, short.container_id)


def test_w5_c03_negative(tmp_path: Path) -> None:
    """A private-repo token stays out of the log and the snapshot. Other tenants cannot read it."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import RepoRefused, SnapshotRefused, WorkspaceProvision

    docker = docker_executable()
    sha, bundle = _sample_bundle(tmp_path)
    secret = "w5c03-token-" + uuid.uuid4().hex
    poisoned = f"https://x-access-token:{secret}@github.com/rxycode/private.git"
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
                revision=sha,
                token=secret,
                bundle=bundle,
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
            revision=sha,
            token=secret,
            bundle=bundle,
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
        assert _read(docker, imported.container_id, "/tmp/ws/base.txt") == "fixed-base\n"
        provision.cleanup(tenant_id="tenant-a", workspace_id=imported.workspace_id)
        imported = None
    finally:
        if imported is not None:
            _remove(docker, imported.container_id)
