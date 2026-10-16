"""WEB-W5-C03. The same task imported twice reproduces the fixed commit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def _readme(docker: str, container_id: str) -> str:
    done = subprocess.run(
        [
            docker,
            "exec",
            container_id,
            "python",
            "-c",
            "print(open('/tmp/ws/README').read(), end='')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_w5_c03_integration() -> None:
    """Two runs of one task check out the same commit and the same base file."""
    from rxycode_runner.sandbox.gvisor import docker_executable
    from rxycode_server.workspaces.provision import WorkspaceProvision

    docker = docker_executable()
    provision = WorkspaceProvision()
    first = None
    second = None
    try:
        kwargs = {
            "tenant_id": "tenant-a",
            "project_id": "proj-repeat",
            "url": _URL,
            "revision": _SHA,
            "authorize_snapshot": True,
        }
        first = provision.import_repo(**kwargs)
        second = provision.import_repo(**kwargs)
        assert first.revision == _SHA
        assert second.revision == _SHA
        assert first.snapshot_sha256 == second.snapshot_sha256
        assert first.container_id != second.container_id
        assert _readme(docker, first.container_id) == _readme(docker, second.container_id)
        assert "Hello World!" in _readme(docker, first.container_id)
        provision.cleanup(tenant_id="tenant-a", workspace_id=first.workspace_id)
        first = None
        assert "Hello World!" in _readme(docker, second.container_id)
        provision.cleanup(tenant_id="tenant-a", workspace_id=second.workspace_id)
        second = None
    finally:
        if first is not None:
            _remove(docker, first.container_id)
        if second is not None:
            _remove(docker, second.container_id)
