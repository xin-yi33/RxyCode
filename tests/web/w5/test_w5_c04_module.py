"""WEB-W5-C04. A closed dev server comes back as target unavailable."""

from __future__ import annotations

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


def _exec(docker: str, sandbox_id: str, argv: list[str], detach: bool = False) -> subprocess.CompletedProcess[str]:
    args = [docker, "exec"]
    if detach:
        args.append("-d")
    args.extend([sandbox_id, *argv])
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)


def test_w5_c04_integration() -> None:
    """After the sandbox port closes, the proxy says the target is unavailable."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import launch
    from rxycode_server.previews.proxy import PreviewProxy, TargetUnavailable

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    html = f"<html><body>{nonce}</body></html>"
    port = 8767
    script = (
        "import os\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        f"HTML = {html!r}.encode()\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'text/html; charset=utf-8')\n"
        "        self.end_headers()\n"
        "        self.wfile.write(HTML)\n"
        "    def log_message(self, *args):\n"
        "        return\n"
        "open('/tmp/preview.pid', 'w').write(str(os.getpid()))\n"
        f"HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n"
    )
    handle = launch(tenant_id="tenant-a", workspace_id="proj-c04i")
    proxy = PreviewProxy()
    try:
        started = _exec(docker, handle.sandbox_id, ["python", "-c", script], detach=True)
        assert started.returncode == 0, started.stderr
        deadline = time.time() + 10
        while time.time() < deadline:
            probe = _exec(
                docker,
                handle.sandbox_id,
                [
                    "python",
                    "-c",
                    f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=1).read().decode())",
                ],
            )
            if probe.returncode == 0 and nonce in probe.stdout:
                break
            time.sleep(0.2)
        else:
            raise AssertionError("dev server did not start")
        proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=port,
            ttl_seconds=60,
        )
        opened = proxy.fetch(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=port,
        )
        assert nonce in opened.body
        killed = _exec(
            docker,
            handle.sandbox_id,
            [
                "python",
                "-c",
                "import os, signal; os.kill(int(open('/tmp/preview.pid').read()), signal.SIGTERM)",
            ],
        )
        assert killed.returncode == 0, killed.stderr
        with pytest.raises(TargetUnavailable) as closed:
            proxy.fetch(
                tenant_id="tenant-a",
                owner_id="user-a",
                sandbox_id=handle.sandbox_id,
                port=port,
            )
        assert "unavailable" in str(closed.value).lower()
        assert handle.sandbox_id in closed.value.target
    finally:
        GVisorSandbox().destroy(handle.sandbox_id, tenant_id="tenant-a")
