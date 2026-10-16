"""WEB-W5-C03. The same task imported twice reproduces the fixed commit."""

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


def test_w5_c03_integration(tmp_path: Path) -> None:
    """Two runs of one task check out the same commit and the same base file."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import WorkspaceProvision

    docker = docker_executable()
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
    bundle_path = tmp_path / "sample.bundle"
    _git(repo, "bundle", "create", str(bundle_path), "--all")
    bundle = bundle_path.read_bytes()
    provision = WorkspaceProvision()
    first = None
    second = None
    try:
        kwargs = {
            "tenant_id": "tenant-a",
            "project_id": "proj-repeat",
            "url": "https://github.com/rxycode/w5-sample",
            "revision": sha,
            "bundle": bundle,
            "authorize_snapshot": True,
        }
        first = provision.import_repo(**kwargs)
        second = provision.import_repo(**kwargs)
        assert first.revision == sha
        assert second.revision == sha
        assert first.snapshot_sha256 == second.snapshot_sha256
        assert first.container_id != second.container_id
        left = subprocess.run(
            [docker, "exec", first.container_id, "python", "-c", "print(open('/tmp/ws/base.txt').read(), end='')"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        right = subprocess.run(
            [docker, "exec", second.container_id, "python", "-c", "print(open('/tmp/ws/base.txt').read(), end='')"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert left.returncode == 0, left.stderr
        assert right.returncode == 0, right.stderr
        assert left.stdout == right.stdout == "fixed-base\n"
        provision.cleanup(tenant_id="tenant-a", workspace_id=first.workspace_id)
        first = None
        again = subprocess.run(
            [docker, "exec", second.container_id, "python", "/tmp/ws/test_sample.py"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert again.returncode == 0, again.stderr
        assert "sample-ok" in again.stdout
        provision.cleanup(tenant_id="tenant-a", workspace_id=second.workspace_id)
        second = None
    finally:
        if first is not None:
            _remove(docker, first.container_id)
        if second is not None:
            _remove(docker, second.container_id)
