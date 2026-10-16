"""WEB-W5-C04. A session sees the React preview. Forged headers and metadata are refused."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
SECRET = "local-web-secret-value-32bytes!!"
MODULES = REPO / "apps" / "web" / "node_modules"
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _exec(docker: str, sandbox_id: str, argv: list[str], detach: bool = False, cwd: str = "") -> subprocess.CompletedProcess[str]:
    args = [docker, "exec"]
    if detach:
        args.append("-d")
    if cwd:
        args.extend(["-w", cwd])
    args.extend([sandbox_id, *argv])
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def _sandbox(tenant_id: str, workspace_id: str):
    from rxycode_runner.sandbox.gvisor import GVisorSandbox
    from rxycode_runner.sandbox.policy import load_policy

    box = GVisorSandbox(image="node:22-slim")
    return box.create(tenant_id=tenant_id, workspace_id=workspace_id, retain=True, policy=load_policy())


def _start_react(docker: str, sandbox_id: str, port: int, nonce: str) -> None:
    made = _exec(docker, sandbox_id, ["mkdir", "-p", "/tmp/app/node_modules"])
    assert made.returncode == 0, made.stderr
    reader = subprocess.Popen(
        ["tar", "-C", str(MODULES), "-cf", "-", "react", "react-dom", "scheduler"],
        stdout=subprocess.PIPE,
    )
    writer = subprocess.run(
        [docker, "exec", "-i", sandbox_id, "tar", "-C", "/tmp/app/node_modules", "-xf", "-"],
        stdin=reader.stdout,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if reader.stdout is not None:
        reader.stdout.close()
    assert reader.wait(timeout=60) == 0
    assert writer.returncode == 0, writer.stderr
    server = (
        "import http from 'node:http';\n"
        "import { writeFileSync } from 'node:fs';\n"
        "import { createElement } from 'react';\n"
        "import { renderToStaticMarkup } from 'react-dom/server';\n"
        f"const nonce = {nonce!r};\n"
        "const html = '<!doctype html>' + renderToStaticMarkup(createElement('p', { id: 'root' }, nonce));\n"
        "writeFileSync('/tmp/preview.pid', String(process.pid));\n"
        "http.createServer((req, res) => {\n"
        "  if (req.url === '/app.js') {\n"
        "    res.setHeader('content-type', 'text/javascript');\n"
        "    res.end('globalThis.__previewLive = true;');\n"
        "    return;\n"
        "  }\n"
        "  if (req.url === '/app.css') {\n"
        "    res.setHeader('content-type', 'text/css');\n"
        "    res.end('p{color:black}');\n"
        "    return;\n"
        "  }\n"
        "  res.setHeader('content-type', 'text/html; charset=utf-8');\n"
        "  res.end(html + '<link rel=\"stylesheet\" href=\"app.css\"><script src=\"app.js\"></script>');\n"
        f"}}).listen({port}, '127.0.0.1');\n"
    )
    saved = subprocess.run(
        [docker, "exec", "-i", sandbox_id, "sh", "-c", "cat > /tmp/app/server.mjs"],
        input=server,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert saved.returncode == 0, saved.stderr
    started = _exec(docker, sandbox_id, ["node", "/tmp/app/server.mjs"], detach=True, cwd="/tmp/app")
    assert started.returncode == 0, started.stderr
    deadline = time.time() + 15
    while time.time() < deadline:
        probe = _exec(
            docker,
            sandbox_id,
            ["node", "-e", f"fetch('http://127.0.0.1:{port}/').then(r=>r.text()).then(t=>{{ if(!t.includes({nonce!r})) process.exit(1); console.log(t); }})"],
        )
        if probe.returncode == 0 and nonce in probe.stdout:
            return
        time.sleep(0.3)
    raise AssertionError(probe.stderr or "react preview did not start")


def _session_app(proxy, user_id: str, tenant_id: str, database: Path):
    from fastapi.testclient import TestClient

    from rxycode_server.api.auth import AuthRecord, _hash_token
    from rxycode_server.main import create_app

    app = create_app(
        "sqlite:///" + database.as_posix(),
        mode="local",
        secret=SECRET,
        allowed_origins=["http://127.0.0.1"],
    )
    app.state.preview_proxy = proxy
    token = secrets.token_urlsafe(32)
    app.state.sessions[_hash_token(app.state.secret, token)] = AuthRecord(
        user_id=user_id,
        tenant_id=tenant_id,
        created=time.monotonic(),
    )
    return TestClient(app), token


def _render(proxy_path: str, unavailable: bool) -> str:
    script = (
        "import { createElement } from 'react';\n"
        "import { renderToStaticMarkup } from 'react-dom/server';\n"
        "import { BrowserPreview } from './src/features/preview/BrowserPreview.tsx';\n"
        "process.stdout.write(renderToStaticMarkup(createElement(BrowserPreview, {\n"
        "  proxyPath: process.env.PREVIEW_PATH,\n"
        "  unavailable: process.env.PREVIEW_DOWN === '1',\n"
        "})));\n"
    )
    done = subprocess.run(
        [str(BUN), "-e", script],
        cwd=REPO / "apps" / "web",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "PREVIEW_PATH": proxy_path, "PREVIEW_DOWN": "1" if unavailable else "0"},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_w5_c04_contract(tmp_path: Path) -> None:
    """The session cookie sees the React page. The browser profile does not copy OAuth."""
    from rxycode_runner.sandbox.browser import close_profile, open_profile
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    secret = "oauth-" + uuid.uuid4().hex
    handle = _sandbox("tenant-a", "proj-c04")
    from rxycode_server.previews.proxy import PreviewProxy

    proxy = PreviewProxy()
    try:
        _start_react(docker, handle.sandbox_id, 8765, nonce)
        granted = proxy.expose_port(
            tenant_id="tenant-a",
            owner_id="user-a",
            sandbox_id=handle.sandbox_id,
            port=8765,
            ttl_seconds=60,
        )
        client, token = _session_app(proxy, "user-a", "tenant-a", tmp_path / "c04.db")
        forged = client.get(
            granted.proxy_path,
            headers={"x-owner-id": "user-a", "x-tenant-id": "tenant-a"},
        )
        assert forged.status_code == 401
        shown = client.get(granted.proxy_path, cookies={"rxy_session": token})
        assert shown.status_code == 200, shown.text
        assert nonce in shown.text
        assert 'src="app.js"' in shown.text
        assert 'href="app.css"' in shown.text
        assert 'src="/app.js"' not in shown.text
        script = client.get(granted.proxy_path + "app.js", cookies={"rxy_session": token})
        assert script.status_code == 200
        assert script.headers["content-type"].startswith("text/javascript")
        assert "__previewLive" in script.text
        style = client.get(granted.proxy_path + "app.css", cookies={"rxy_session": token})
        assert style.status_code == 200
        assert style.headers["content-type"].startswith("text/css")
        assert "color" in style.text
        viewed = _render(granted.proxy_path, False)
        assert f'src="{granted.proxy_path}"' in viewed
        assert 'sandbox="allow-scripts"' in viewed
        assert "srcDoc" not in viewed
        hidden = _render(granted.proxy_path, True)
        assert "target unavailable" in hidden
        os.environ["OAUTH_TOKEN"] = secret
        try:
            profile = open_profile(sandbox_id=handle.sandbox_id, tenant_id="tenant-a")
        finally:
            os.environ.pop("OAUTH_TOKEN", None)
        listed = _exec(
            docker,
            handle.sandbox_id,
            [
                "node",
                "-e",
                (
                    "const fs=require('fs');"
                    f"const root={profile.path!r};"
                    "console.log(fs.readdirSync(root).map(n=>fs.readFileSync(root+'/'+n,'utf8')).join(''));"
                ),
            ],
        )
        assert listed.returncode == 0, listed.stderr
        assert secret not in listed.stdout
        close_profile(profile_id=profile.profile_id, sandbox_id=handle.sandbox_id, tenant_id="tenant-a")
        gone = _exec(
            docker,
            handle.sandbox_id,
            ["node", "-e", f"process.exit(require('fs').existsSync({profile.path!r}) ? 1 : 0)"],
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


def test_w5_c04_negative(tmp_path: Path) -> None:
    """Metadata URLs and another tenant are refused. An expired grant is refused."""
    from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
    from rxycode_server.previews.proxy import PreviewProxy, PreviewRefused

    docker = docker_executable()
    nonce = "preview-" + uuid.uuid4().hex
    handle = _sandbox("tenant-a", "proj-c04n")
    proxy = PreviewProxy()
    try:
        _start_react(docker, handle.sandbox_id, 8766, nonce)
        granted = proxy.expose_port(
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
        client, token = _session_app(proxy, "user-a", "tenant-a", tmp_path / "c04n.db")
        other, other_token = _session_app(proxy, "user-b", "tenant-b", tmp_path / "c04b.db")
        assert other.get(granted.proxy_path, cookies={"rxy_session": other_token}).status_code == 403
        with pytest.raises(PreviewRefused):
            proxy.fetch(
                tenant_id="tenant-a",
                owner_id="user-a",
                sandbox_id=handle.sandbox_id,
                port=8766,
                asset_path="../etc/passwd",
            )
        still = client.get(granted.proxy_path, cookies={"rxy_session": token})
        assert still.status_code == 200
        assert nonce in still.text
        assert "169.254.169.254" not in still.text
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
