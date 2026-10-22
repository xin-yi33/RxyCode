"""WEB-W3-C02. A logged-in import survives refresh, and a rejected key creates no project."""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import http.client
import uvicorn
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402

_UNIT = Path(__file__).with_name("test_w3_c01_unit.py")
_spec = importlib.util.spec_from_file_location("w3c01_unit_build", _UNIT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

from tests.support.pgurl import ensure_container, worker_url  # noqa: E402

_PG_BASE = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
ensure_container("rxy-w2c01-pg", 55432)
URL = worker_url(_PG_BASE)
SECRET = "local-web-secret-value-32bytes!!"


def _port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _reset_db() -> None:
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    upgrade_head(URL)


def _wait_api(port: int) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/v1/auth/csrf")
            if conn.getresponse().status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("api did not start")


class _Stack:
    def __init__(self) -> None:
        dist = _mod.build_web()
        _reset_db()
        self.proxy_port = _port()
        origin = f"http://127.0.0.1:{self.proxy_port}"
        # W9: github/start is 503 AUTH_PROVIDER_NOT_CONFIGURED unless all three
        # values are set — the OAuth-flow assertions below need them present.
        app = create_app(
            URL,
            mode="local",
            secret=SECRET,
            allowed_origins=[origin],
            github_client_id="w3-c02-client",
            github_client_secret="w3-c02-secret",
            github_redirect_uri=f"{origin}/oauth/callback",
        )
        self.api_port = _port()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.api_port, log_level="warning")
        self.api = uvicorn.Server(config)
        self.api_thread = threading.Thread(target=self.api.run, daemon=True)
        self.api_thread.start()
        _wait_api(self.api_port)
        hits: list[str] = []
        api_port = self.api_port

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                del fmt, args

            def _proxy(self) -> None:
                length = int(self.headers.get("content-length", "0") or "0")
                body = self.rfile.read(length) if length else None
                conn = http.client.HTTPConnection("127.0.0.1", api_port, timeout=15)
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() not in {"host", "content-length", "accept-encoding"}
                }
                conn.request(self.command, self.path, body=body, headers=headers)
                response = conn.getresponse()
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() in {"transfer-encoding", "content-length", "content-encoding"}:
                        continue
                    self.send_header(key, value)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _static(self) -> None:
                path = urlparse(self.path).path
                hits.append(path)
                rel = path.lstrip("/") or "index.html"
                target = dist / rel
                if not target.is_file():
                    target = dist / "index.html"
                payload = target.read_bytes()
                kind = "text/html"
                if target.suffix == ".js":
                    kind = "text/javascript"
                elif target.suffix == ".css":
                    kind = "text/css"
                self.send_response(200)
                self.send_header("content-type", kind)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _tunnel(self) -> None:
                upstream = socket.create_connection(("127.0.0.1", api_port))
                lines = [f"{self.command} {self.path} HTTP/1.1", f"Host: 127.0.0.1:{api_port}"]
                for key, value in self.headers.items():
                    if key.lower() != "host":
                        lines.append(f"{key}: {value}")
                upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
                client = self.connection

                def pump(src: socket.socket, dst: socket.socket) -> None:
                    try:
                        while True:
                            chunk = src.recv(65536)
                            if not chunk:
                                break
                            dst.sendall(chunk)
                    except OSError:
                        pass
                    finally:
                        try:
                            dst.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass

                left = threading.Thread(target=pump, args=(upstream, client), daemon=True)
                right = threading.Thread(target=pump, args=(client, upstream), daemon=True)
                left.start()
                right.start()
                left.join()
                right.join()
                upstream.close()

            def do_GET(self) -> None:  # noqa: N802
                if self.headers.get("upgrade", "").lower() == "websocket":
                    self._tunnel()
                    return
                if urlparse(self.path).path.startswith("/api/"):
                    self._proxy()
                else:
                    self._static()

            def do_POST(self) -> None:  # noqa: N802
                self._proxy()

        self.proxy = ThreadingHTTPServer(("127.0.0.1", self.proxy_port), Handler)
        self.proxy_thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.proxy_thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.proxy_port}"

    def close(self) -> None:
        self.proxy.shutdown()
        self.api.should_exit = True


def _login(page, origin: str) -> None:
    """Local-secret login via the W9 /login page's 本机口令 section."""
    page.goto(f"{origin}/login", wait_until="domcontentloaded")
    page.get_by_role("button", name="本机口令").click()
    page.get_by_label("本机口令").fill(SECRET)
    page.get_by_role("button", name="使用本机口令登录").click()
    # The console composer proves the session reached /app.
    expect(page.get_by_label("消息")).to_be_visible(timeout=10000)


def test_w3_c02_contract() -> None:
    """A submitted task lands on the session page and survives a reload."""
    stack = _Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            _login(page, stack.origin)
            # W9-F3: project 导入 UI was removed — POST /tasks provisions the
            # server session + run and the session list is the persistence
            # surface this test now asserts.
            page.get_by_label("消息").fill("c02 持久化任务")
            page.get_by_role("button", name="发送").click()
            page.wait_for_url(re.compile(r"/app/s/[0-9a-f]+$"), timeout=10000)
            session_url = page.url
            expect(page.get_by_text("排队中").first).to_be_visible(timeout=10000)
            sidebar_item = page.locator("aside").get_by_text("c02 持久化任务")
            expect(sidebar_item).to_be_visible(timeout=10000)
            page.reload(wait_until="domcontentloaded")
            expect(page).to_have_url(session_url)
            expect(page.locator("aside").get_by_text("c02 持久化任务")).to_be_visible(
                timeout=10000
            )
            browser.close()
    finally:
        stack.close()


def test_w3_c02_negative() -> None:
    """A bad OAuth callback and the GitHub start button behave honestly."""
    stack = _Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            # The 密钥/导入 fields and the rejected-import alert assertions were
            # removed — the project-import UI is gone in W9-F1 (POST /projects
            # is API-only now). Nothing in the console may mint a project card.
            page = browser.new_page()
            _login(page, stack.origin)
            expect(page.locator("[data-project-id]")).to_have_count(0)
            failed = browser.new_page()
            failed.goto(
                f"{stack.origin}/oauth/callback?state=bad&code=bad",
                wait_until="domcontentloaded",
            )
            expect(failed.get_by_role("alert")).to_be_visible(timeout=10000)
            expect(failed.locator("[data-project-id]")).to_have_count(0)
            cloud = browser.new_page()
            cloud.route("https://github.com/**", lambda route: route.abort())
            cloud.goto(f"{stack.origin}/login", wait_until="domcontentloaded")
            with cloud.expect_response(
                lambda item: item.url.endswith("/api/v1/auth/github/start")
            ) as started:
                with cloud.expect_request(
                    lambda item: "github.com/login/oauth/authorize" in item.url
                ) as oauth:
                    cloud.get_by_role("button", name="使用 GitHub 继续").click()
            assert started.value.status == 200
            assert "client_id=" in oauth.value.url
            browser.close()
    finally:
        stack.close()
