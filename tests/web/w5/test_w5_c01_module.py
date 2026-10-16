"""WEB-W5-C01. A missing runtime blocks the tool and does not run it on the host."""

from __future__ import annotations

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


def test_w5_c01_integration(tmp_path: Path) -> None:
    """Creating a run against a runtime the daemon does not have blocks the tool."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.provider import IsolationUnavailable
    from rxycode_server.sandbox.control import SandboxControl, ToolBlocked

    docker = docker_executable()
    workspace_id = "ws-down-" + uuid.uuid4().hex[:8]
    marker = tmp_path / "host-fallback.txt"
    probe = GVisorSandbox(image="python:3.12-slim")
    try:
        installed = probe.installed_runtimes()
    except IsolationUnavailable:
        installed = []
    missing = "runsc" if "runsc" not in installed else "runtime-class-not-present"
    listed = subprocess.run(
        [docker, "ps", "-aq", "--filter", f"label=rxy.workspace={workspace_id}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert listed.stdout.strip() == ""
    control = SandboxControl(GVisorSandbox(runtime=missing, image="python:3.12-slim"))
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran-on-host')"
    with pytest.raises(ToolBlocked) as blocked:
        control.sandboxd_exec(
            tenant_id="tenant-a",
            workspace_id=workspace_id,
            argv=["python", "-c", script],
        )
    assert "unavailable" in str(blocked.value).lower()
    assert blocked.value.target == f"cloud:tenant-a:{workspace_id}"
    assert marker.is_file() is False
    again = subprocess.run(
        [docker, "ps", "-aq", "--filter", f"label=rxy.workspace={workspace_id}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert again.stdout.strip() == ""
    kinds = [row["kind"] for row in control.ledger()]
    assert "start" not in kinds
    assert "blocked" in kinds
