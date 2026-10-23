"""WEB-W5-C04. Closing the React preview server returns target unavailable."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from tests.web.w5.test_w5_c04_unit import _exec, _sandbox, _session_app, _start_react


def test_w5_c04_integration(tmp_path: Path) -> None:
    """After the React server exits, the preview route says the target is unavailable."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_server.previews.proxy import PreviewProxy

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    handle = _sandbox("tenant-a", "proj-c04i")
    proxy = PreviewProxy()
    try:
        _start_react(docker, handle.sandbox_id, 8767, nonce)
        granted = proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8767,
            ttl_seconds=60,
        )
        client, token = _session_app(proxy, "user-a", "tenant-a", tmp_path / "c04i.db")
        opened = client.get(granted.proxy_path, cookies={"rxy_session": token})
        assert opened.status_code == 200
        assert nonce in opened.text
        killed = _exec(
            docker,
            handle.sandbox_id,
            [
                "node",
                "-e",
                "process.kill(Number(require('fs').readFileSync('/tmp/preview.pid','utf8')), 'SIGTERM')",
            ],
        )
        assert killed.returncode == 0, killed.stderr
        closed = client.get(granted.proxy_path, cookies={"rxy_session": token})
        assert closed.status_code == 503
        assert "unavailable" in closed.text
        assert handle.sandbox_id in closed.text
    finally:
        GVisorSandbox().destroy(handle.sandbox_id, tenant_id="tenant-a")
