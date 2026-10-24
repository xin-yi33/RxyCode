"""WEB-W6-C03. Authorized handoff continues one agent session, not user Chrome."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
from tests.support.pgurl import bun_path

BUN = bun_path()
for _entry in (REPO, _RUNNER, REPO / "tests" / "web" / "w6"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def test_w6_c03_integration() -> None:
    """A handoff click authorizes the same agent session and leaves Chrome alone."""
    from test_w6_c03_unit import start_page
    from rxycode_runner.browser.session_manager import (
        close_session,
        continue_session,
        navigate_click,
        open_agent_context,
        read_storage,
        request_user_cookies,
        snapshot,
    )

    token = "rxy-hand-" + uuid.uuid4().hex
    server, url = start_page(token)
    root = Path(tempfile.mkdtemp(prefix="rxy-w6c03-mod-"))
    user_chrome = root / "Google" / "Chrome" / "User Data"
    secret_path = user_chrome / "Default" / "Cookies"
    secret_path.parent.mkdir(parents=True)
    secret = b"CHROME-SECRET-" + uuid.uuid4().hex.encode("ascii")
    secret_path.write_bytes(secret)
    before = sorted(str(path.relative_to(user_chrome)) for path in user_chrome.rglob("*") if path.is_file())
    agent_dir = root / "agent-profile"
    preview_dir = root / "preview-profile"
    opened: list[str] = []
    try:
        agent = open_agent_context(profile_dir=agent_dir, kind="agent")
        assert agent["status"] == "open"
        reused = open_agent_context(profile_dir=agent_dir, kind="preview")
        assert reused["status"] == "refused"
        alias = root / "preview-alias"
        if os.name == "nt":
            linked = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alias), str(agent_dir)],
                capture_output=True,
                check=False,
            )
            detail = (linked.stderr or linked.stdout).decode("utf-8", "replace")
            assert linked.returncode == 0, detail
        else:
            alias.symlink_to(agent_dir, target_is_directory=True)
        aliased = open_agent_context(profile_dir=alias, kind="preview")
        assert aliased["status"] == "refused"
        if os.name == "nt":
            os.rmdir(alias)
        else:
            alias.unlink()
        preview = open_agent_context(profile_dir=preview_dir, kind="preview")
        assert preview["status"] == "open"
        assert agent["profile_kind"] == "agent"
        assert preview["profile_kind"] == "preview"
        assert Path(agent["profile_dir"]) != Path(preview["profile_dir"])
        opened.extend([str(agent["session_id"]), str(preview["session_id"])])
        blocked = continue_session(session_id=str(agent["session_id"]))
        assert blocked["status"] == "refused"
        assert token not in blocked.get("dom", "")
        app_text = (REPO / "apps" / "web" / "src" / "app" / "App.tsx").read_text(encoding="utf-8")
        assert "BrowserHandoff" in app_text
        assert "handoffPageUrl" in app_text
        assert 'path: "/browser/:sessionId"' in app_text
        pending = _render(session_id=str(agent["session_id"]), authorized=False)
        assert 'aria-label="browser-handoff"' in pending
        assert 'data-authorized="false"' in pending
        assert f'data-session="{agent["session_id"]}"' in pending
        assert "授权接管" in pending
        assert "<iframe" not in pending.lower()
        assert secret.decode("ascii") not in pending
        clicked = navigate_click(session_id=str(agent["session_id"]), url=url, selector="#go")
        assert clicked["status"] == "ok"
        assert token in clicked["dom"]
        preview_hit = navigate_click(
            session_id=str(preview["session_id"]),
            url=url,
            selector="#missing",
        )
        assert preview_hit["status"] != "ok"
        assert read_storage(session_id=str(preview["session_id"]), key="rxy-marker")["value"] in ("", None)
        from rxycode_runner.browser.session_manager import HANDOFF_PORT

        framed = urllib.request.urlopen(
            f"http://127.0.0.1:{HANDOFF_PORT}/browser/{agent['session_id']}",
            timeout=5,
        )
        assert framed.headers["X-Frame-Options"] == "DENY"
        assert framed.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
        framed.close()
        evil = urllib.request.Request(
            f"http://127.0.0.1:{HANDOFF_PORT}/sessions/{agent['session_id']}/authorize",
            data=b"",
            method="POST",
            headers={"Origin": "http://evil.example", "X-Handoff-Token": "stolen"},
        )
        with pytest.raises(urllib.error.HTTPError) as blocked_post:
            urllib.request.urlopen(evil, timeout=5)
        assert blocked_post.value.code == 403
        still_blocked = continue_session(session_id=str(agent["session_id"]))
        assert still_blocked["status"] == "refused"
        granted = _click_same_origin_handoff(str(agent["session_id"]))
        assert granted["status"] == "authorized", granted.get("reason")
        assert granted["shared"] is False
        assert 'data-authorized="true"' in granted["dom"]
        assert "agent session continued" in granted["dom"]
        assert "user Chrome data is not shared" in granted["dom"]
        assert "<iframe" not in granted["dom"].lower()
        continued = continue_session(session_id=str(agent["session_id"]))
        assert continued["status"] == "ok"
        assert continued["session_id"] == agent["session_id"]
        assert continued["profile_kind"] == "agent"
        assert token in continued["dom"]
        assert read_storage(session_id=str(agent["session_id"]), key="rxy-marker")["value"] == token
        cookies = request_user_cookies(authorized=True, user_chrome_dir=user_chrome)
        assert cookies["shared"] is False
        assert secret.decode("ascii") not in str(cookies)
        blob = ""
        public = {"status": "not attempted"}
        for _ in range(3):
            # External navigation flake — ERR_NETWORK_*, slow first paint,
            # or chromium landing on its own chrome-error page despite an
            # "ok" status under load. A genuine product refusal reproduces
            # on every retry, which keeps the assertion strict.
            public = navigate_click(
                session_id=str(agent["session_id"]),
                url="https://example.com/",
                selector="a",
            )
            if public["status"] != "ok":
                continue
            shot = snapshot(session_id=str(agent["session_id"]))
            if shot["status"] != "ok":
                continue
            blob = (shot["dom"] + shot.get("title", "") + shot["url"]).lower()
            if "chrome-error://" not in blob:
                break
        assert public["status"] == "ok", public
        assert "iana.org" in blob or "example domain" in blob
        assert secret.decode("ascii") not in blob
        assert secret_path.read_bytes() == secret
        after = sorted(
            str(path.relative_to(user_chrome))
            for path in user_chrome.rglob("*")
            if path.is_file()
        )
        assert after == before
        for session_id in opened:
            close_session(session_id=session_id)
        opened.clear()
        for cookies_file in agent_dir.rglob("Cookies"):
            assert secret not in cookies_file.read_bytes()
        _assert_wheel_contains_session_manager()
    finally:
        for session_id in opened:
            close_session(session_id=session_id)
        server.shutdown()
        alias = root / "preview-alias"
        is_junction = getattr(os.path, "isjunction", None)
        if is_junction is not None and is_junction(alias):
            os.rmdir(alias)
        shutil.rmtree(root, ignore_errors=True)


def _assert_wheel_contains_session_manager() -> None:
    """The installed wheel contains the browser session manager."""
    out = Path(tempfile.mkdtemp(prefix="rxy-w6c03-wheel-"))
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(out),
            str(REPO),
        ],
        cwd=REPO,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    wheels = list(out.glob("*.whl"))
    assert wheels
    names: set[str] = set()
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as bundle:
            names.update(bundle.namelist())
    assert "rxycode_runner/browser/session_manager.py" in names
    assert "rxycode_runner/browser/__init__.py" in names


_ENTRY = """
import { createRoot } from "react-dom/client"
import { BrowserHandoff, requestHandoff } from "./BrowserHandoff.tsx"

const root = document.getElementById("root")
const sessionId = (window as Window & { sessionId: string }).sessionId
if (root) {
  createRoot(root).render(
    <BrowserHandoff
      sessionId={sessionId}
      authorized={false}
      onAuthorize={() => requestHandoff(sessionId)}
    />
  )
}
"""

_DENY_ENTRY = """
import { createRoot } from "react-dom/client"
import { BrowserHandoff } from "./BrowserHandoff.tsx"

const root = document.getElementById("root")
const sessionId = (window as Window & { sessionId: string }).sessionId
if (root) {
  createRoot(root).render(
    <BrowserHandoff
      sessionId={sessionId}
      authorized={false}
      onAuthorize={() => Promise.resolve(false)}
    />
  )
}
"""


def _click_denied(page: object) -> None:
    page.click("button", timeout=8000)  # type: ignore[attr-defined]
    page.wait_for_timeout(500)  # type: ignore[attr-defined]


def _click_granted(page: object) -> None:
    page.click("button", timeout=8000)  # type: ignore[attr-defined]
    page.wait_for_selector('[data-authorized="true"]', timeout=10000)  # type: ignore[attr-defined]


class _Bundle(BaseHTTPRequestHandler):
    html = b""
    script = b""

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/bundle.js"):
            body, kind = self.script, "text/javascript"
        else:
            body, kind = self.html, "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _user_clicks_handoff(session_id: str, source: str, action: object) -> dict[str, object]:
    """The test performs the button click. The product only mounts the page."""
    from rxycode_runner.browser.session_manager import (
        close_handoff_page,
        present_handoff,
        run_on_handoff_page,
    )

    entry = REPO / "apps" / "web" / "src" / "features" / "browser" / "_c03_handoff_entry.tsx"
    bundle_dir = Path(tempfile.mkdtemp(prefix="rxy-w6c03-bundle-"))
    bundle = bundle_dir / "bundle.js"
    entry.write_text(source, encoding="utf-8")
    server: ThreadingHTTPServer | None = None
    try:
        built = subprocess.run(
            [BUN, "build", str(entry), "--outfile", str(bundle), "--target", "browser"],
            cwd=REPO / "apps" / "web",
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert built.returncode == 0, built.stderr
        html = (
            '<!doctype html><html><body><div id="root"></div>'
            f"<script>window.sessionId = {json.dumps(session_id)}</script>"
            '<script src="/bundle.js"></script></body></html>'
        )
        _Bundle.html = html.encode("utf-8")
        _Bundle.script = bundle.read_bytes()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Bundle)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = f"http://127.0.0.1:{server.server_address[1]}/"
        presented = present_handoff(agent_session_id=session_id, url=page)
        assert presented["status"] == "open", presented
        return run_on_handoff_page(agent_session_id=session_id, action=action)
    finally:
        close_handoff_page(agent_session_id=session_id)
        entry.unlink(missing_ok=True)
        if server is not None:
            server.shutdown()
        shutil.rmtree(bundle_dir, ignore_errors=True)


def _click_same_origin_handoff(session_id: str) -> dict[str, object]:
    """Click the page the app route links to. That page posts its own token."""
    from rxycode_runner.browser.session_manager import (
        HANDOFF_PORT,
        close_handoff_page,
        present_handoff,
        run_on_handoff_page,
    )

    try:
        presented = present_handoff(
            agent_session_id=session_id,
            url=f"http://127.0.0.1:{HANDOFF_PORT}/browser/{session_id}",
        )
        assert presented["status"] == "open", presented
        return run_on_handoff_page(agent_session_id=session_id, action=_click_granted)
    finally:
        close_handoff_page(agent_session_id=session_id)


def _render(*, session_id: str, authorized: bool) -> str:
    if BUN is None:
        pytest.skip("bun is not installed")
    env = os.environ.copy()
    env["RXY_SESSION"] = session_id
    env["RXY_AUTHORIZED"] = "true" if authorized else "false"
    component = REPO / "apps" / "web" / "src" / "features" / "browser" / "BrowserHandoff.tsx"
    env["RXY_COMPONENT"] = str(component)
    script = r"""
import { createRequire } from "module"
import { pathToFileURL } from "url"
const require = createRequire(pathToFileURL(process.env.RXY_COMPONENT).href)
const React = require(require.resolve("react", { paths: [process.cwd() + "/apps/web"] }))
const { renderToStaticMarkup } = require(require.resolve("react-dom/server", { paths: [process.cwd() + "/apps/web"] }))
const { BrowserHandoff } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const html = renderToStaticMarkup(React.createElement(BrowserHandoff, {
  sessionId: process.env.RXY_SESSION,
  authorized: process.env.RXY_AUTHORIZED === "true",
}))
process.stdout.write(html)
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c03-ui-")) / "render.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [BUN, str(program)],
            cwd=REPO,
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
    assert rendered.returncode == 0, rendered.stderr
    json.dumps({"session_id": session_id, "authorized": authorized})
    return rendered.stdout
