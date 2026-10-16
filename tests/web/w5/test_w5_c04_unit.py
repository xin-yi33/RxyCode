"""WEB-W5-C04. The owner sees the sandbox page. Metadata and other tenants are refused."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
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


def _exec(docker: str, sandbox_id: str, argv: list[str], detach: bool = False) -> subprocess.CompletedProcess[str]:
    args = [docker, "exec"]
    if detach:
        args.append("-d")
    args.extend([sandbox_id, *argv])
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)


def _start_page(docker: str, sandbox_id: str, port: int, html: str) -> None:
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
    started = _exec(docker, sandbox_id, ["python", "-c", script], detach=True)
    assert started.returncode == 0, started.stderr
    deadline = time.time() + 10
    while time.time() < deadline:
        probe = _exec(
            docker,
            sandbox_id,
            ["python", "-c", f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=1).read().decode())"],
        )
        if probe.returncode == 0 and html in probe.stdout:
            return
        time.sleep(0.2)
    raise AssertionError("dev server did not start")


def _render(proxy_path: str, html: str, unavailable: bool) -> str:
    script = (
        "import { createElement } from 'react';\n"
        "import { renderToStaticMarkup } from 'react-dom/server';\n"
        "import { BrowserPreview } from './src/features/preview/BrowserPreview.tsx';\n"
        "const html = renderToStaticMarkup(createElement(BrowserPreview, {\n"
        "  proxyPath: process.env.PREVIEW_PATH,\n"
        "  html: process.env.PREVIEW_HTML,\n"
        "  unavailable: process.env.PREVIEW_DOWN === '1',\n"
        "}));\n"
        "process.stdout.write(html);\n"
    )
    done = subprocess.run(
        [str(BUN), "-e", script],
        cwd=REPO / "apps" / "web",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            **os.environ,
            "PREVIEW_PATH": proxy_path,
            "PREVIEW_HTML": html,
            "PREVIEW_DOWN": "1" if unavailable else "0",
        },
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_w5_c04_contract() -> None:
    """The owner's preview is the real sandbox page, and the browser profile has no OAuth token."""
    from rxycode_runner.sandbox.browser import close_profile, open_profile
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import launch
    from rxycode_server.previews.proxy import PreviewProxy

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    html = f"<html><body>{nonce}</body></html>"
    secret = "oauth-" + uuid.uuid4().hex
    handle = launch(tenant_id="tenant-a", workspace_id="proj-c04")
    proxy = PreviewProxy()
    try:
        _start_page(docker, handle.sandbox_id, 8765, html)
        granted = proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8765,
            ttl_seconds=60,
        )
        page = proxy.fetch(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8765,
        )
        assert nonce in page.body
        assert page.proxy_path == granted.proxy_path
        assert page.proxy_path.startswith("/api/v1/previews/")
        assert "default-src" in page.csp
        viewed = _render(page.proxy_path, page.body, False)
        assert nonce in viewed
        assert 'sandbox=""' in viewed or "sandbox=\"\"" in viewed
        hidden = _render(page.proxy_path, page.body, True)
        assert "target unavailable" in hidden
        assert nonce not in hidden
        os.environ["OAUTH_TOKEN"] = secret
        try:
            profile = open_profile(sandbox_id=handle.sandbox_id, tenant_id="tenant-a")
        finally:
            os.environ.pop("OAUTH_TOKEN", None)
        listed = _exec(
            docker,
            handle.sandbox_id,
            ["python", "-c", f"import os; root={profile.path!r}\nprint(''.join(os.listdir(root)))\n"],
        )
        assert listed.returncode == 0, listed.stderr
        assert secret not in listed.stdout
        dumped = _exec(
            docker,
            handle.sandbox_id,
            [
                "python",
                "-c",
                (
                    "import os\n"
                    f"root={profile.path!r}\n"
                    "buf=[]\n"
                    "for name in os.listdir(root):\n"
                    "    buf.append(open(os.path.join(root, name), encoding='utf-8', errors='replace').read())\n"
                    "print(''.join(buf))\n"
                ),
            ],
        )
        assert secret not in dumped.stdout
        close_profile(profile_id=profile.profile_id, sandbox_id=handle.sandbox_id, tenant_id="tenant-a")
        gone = _exec(
            docker,
            handle.sandbox_id,
            ["python", "-c", f"import os; raise SystemExit(0 if not os.path.exists({profile.path!r}) else 1)"],
        )
        assert gone.returncode == 0
        info = json.loads(
            subprocess.run(
                [docker, "inspect", handle.container_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            ).stdout
        )[0]
        assert info["HostConfig"]["NetworkMode"] == "none"
    finally:
        GVisorSandbox().destroy(handle.sandbox_id, tenant_id="tenant-a")


def test_w5_c04_negative() -> None:
    """Metadata URLs and another tenant are refused. An unregistered port is not proxied."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_runner.sandbox.policy import launch
    from rxycode_server.previews.proxy import PreviewProxy, PreviewRefused

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    html = f"<html><body>{nonce}</body></html>"
    handle = launch(tenant_id="tenant-a", workspace_id="proj-c04n")
    proxy = PreviewProxy()
    try:
        _start_page(docker, handle.sandbox_id, 8766, html)
        proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8766,
            ttl_seconds=60,
        )
        with pytest.raises(PreviewRefused):
            proxy.fetch(
                tenant_id="tenant-b",
                owner_id="user-b",
                sandbox_id=handle.sandbox_id,
                port=8766,
            )
        with pytest.raises(PreviewRefused):
            proxy.fetch(
                tenant_id="tenant-a",
                owner_id="user-a",
                sandbox_id=handle.sandbox_id,
                port=8766,
                requested_url="http://169.254.169.254/latest/meta-data",
            )
        with pytest.raises(PreviewRefused):
            proxy.expose_port(
                tenant_id="tenant-b",
                owner_id="user-b",
                sandbox_id=handle.sandbox_id,
                port=8766,
                ttl_seconds=60,
            )
        with pytest.raises(PreviewRefused):
            proxy.fetch(
                tenant_id="tenant-a",
                owner_id="user-a",
                sandbox_id=handle.sandbox_id,
                port=9,
            )
        still = proxy.fetch(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8766,
        )
        assert nonce in still.body
        assert "169.254.169.254" not in still.body
        short = proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8766,
            ttl_seconds=1,
        )
        time.sleep(1.3)
        with pytest.raises(PreviewRefused):
            proxy.fetch(
                tenant_id="tenant-a",
                owner_id="user-a",
                sandbox_id=handle.sandbox_id,
                port=8766,
                grant_id=short.grant_id,
            )
    finally:
        GVisorSandbox().destroy(handle.sandbox_id, tenant_id="tenant-a")
