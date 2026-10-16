"""WEB-W6-C03. Isolated agent browser DOM, and no user Chrome sharing."""

from __future__ import annotations

import sys
import tempfile
import threading
import uuid
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _entry in (REPO, _RUNNER):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


class _Page(BaseHTTPRequestHandler):
    token = ""

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/done"):
            body = (
                "<!doctype html><html><body>"
                f"<p id=\"out\">{self.token}</p>"
                "<script>localStorage.setItem('rxy-marker', "
                "document.getElementById('out').textContent)</script>"
                "</body></html>"
            ).encode("utf-8")
            kind = "text/html"
        else:
            body = (
                "<!doctype html><html><body>"
                "<p id=\"out\">before</p><button id=\"go\">Go</button>"
                "<script>document.getElementById('go').addEventListener('click', function () {"
                " window.location = '/done';"
                "});</script></body></html>"
            ).encode("utf-8")
            kind = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def start_page(token: str) -> tuple[ThreadingHTTPServer, str]:
    _Page.token = token
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/"


def _listing(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )


def test_w6_c03_contract() -> None:
    """Navigate and click in an isolated agent profile and read the clicked DOM."""
    from rxycode_runner.browser.session_manager import (
        close_session,
        navigate_click,
        open_agent_context,
        read_storage,
    )

    cu = (REPO / "core" / "cu" / "browser.py").read_text(encoding="utf-8")
    assert "def browser_open(" in cu
    assert "def browser_snapshot(" in cu
    assert "def browser_act(" in cu
    tools = (REPO / "tools" / "virtual_browser.py").read_text(encoding="utf-8")
    assert 'name="browser_navigate"' in tools
    assert 'name="browser_snapshot"' in tools
    assert 'name="browser_click"' in tools

    token = "rxy-dom-" + uuid.uuid4().hex
    server, url = start_page(token)
    profile = Path(tempfile.mkdtemp(prefix="rxy-w6c03-agent-"))
    session_id = ""
    try:
        static = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
        assert token not in static
        opened = open_agent_context(profile_dir=profile, kind="agent")
        assert opened["status"] == "open"
        assert opened["profile_kind"] == "agent"
        assert Path(opened["profile_dir"]) == profile
        assert opened["shared"] is False
        session_id = str(opened["session_id"])
        result = navigate_click(session_id=session_id, url=url, selector="#go")
        assert result["status"] == "ok"
        assert result["profile_kind"] == "agent"
        assert token in result["dom"]
        assert result["url"].startswith(url)
        stored = read_storage(session_id=session_id, key="rxy-marker")
        assert stored["value"] == token
        cookie_jar = profile / "Default" / "Network" / "Cookies"
        assert cookie_jar.is_file()
    finally:
        if session_id:
            close_session(session_id=session_id)
        server.shutdown()
        _remove(profile)


def test_w6_c03_negative() -> None:
    """Unauthorized cookie handoff must not read or copy the user's Chrome data."""
    from rxycode_runner.browser.session_manager import (
        close_session,
        navigate_click,
        open_agent_context,
        request_user_cookies,
    )

    root = Path(tempfile.mkdtemp(prefix="rxy-w6c03-neg-"))
    user_chrome = root / "Google" / "Chrome" / "User Data"
    secret_path = user_chrome / "Default" / "Cookies"
    secret_path.parent.mkdir(parents=True)
    secret = b"CHROME-SECRET-" + uuid.uuid4().hex.encode("ascii")
    secret_path.write_bytes(secret)
    before = _listing(user_chrome)
    agent = root / "agent-profile"
    session_id = ""
    try:
        refused = request_user_cookies(authorized=False, user_chrome_dir=user_chrome)
        assert refused["status"] == "refused"
        assert refused["shared"] is False
        assert secret.decode("ascii") not in str(refused)
        attached = open_agent_context(profile_dir=user_chrome, kind="agent")
        assert attached["status"] == "refused"
        assert attached["shared"] is False
        assert _listing(user_chrome) == before
        assert secret_path.read_bytes() == secret
        for path in root.rglob("*"):
            if path.is_file() and path != secret_path:
                assert secret not in path.read_bytes()
        opened = open_agent_context(profile_dir=agent, kind="agent")
        assert opened["status"] == "open"
        session_id = str(opened["session_id"])
        bad = navigate_click(
            session_id=session_id,
            url="file:///C:/Users/Administrator/AppData/Local/Google/Chrome/User Data/Local State",
            selector="#go",
        )
        assert bad["status"] == "refused"
        assert "Local State" not in bad.get("dom", "")
        assert secret.decode("ascii") not in str(bad)
        assert _listing(user_chrome) == before
    finally:
        if session_id:
            close_session(session_id=session_id)
        _remove(root)


def _remove(root: Path) -> None:
    import shutil

    shutil.rmtree(root, ignore_errors=True)
