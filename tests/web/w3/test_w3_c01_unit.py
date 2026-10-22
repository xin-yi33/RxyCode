"""WEB-W3-C01. The login page shows an error and a retry control when the API is down."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
_FORBIDDEN = (
    "electron",
    "contextBridge",
    "ipcRenderer",
    "child_process",
    "node:fs",
    "node:child_process",
    "preload.js",
    "@electron-toolkit",
    "localStorage",
    "sk-ant-",
    "sk-proj-",
    "api_key",
    "BEGIN PRIVATE KEY",
    "local-web-secret",
)


def _bun() -> str:
    from tests.support.pgurl import bun_path

    found = bun_path()
    if found:
        return found
    raise FileNotFoundError("bun")


def _source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(WEB.rglob("*")):
        if not path.is_file() or "node_modules" in path.parts or "dist" in path.parts:
            continue
        digest.update(str(path.relative_to(WEB)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_web() -> Path:
    """Install and build the shipped Vite app. A second call reuses that dist."""
    package = WEB / "package.json"
    assert package.is_file(), "apps/web/package.json is missing"
    dist = WEB / "dist"
    stamp = dist / ".built"
    digest = _source_digest()
    fresh = stamp.is_file() and stamp.read_text(encoding="utf-8") == digest
    if fresh and (dist / "index.html").is_file():
        return dist
    if dist.exists():
        shutil.rmtree(dist)
    subprocess.run([_bun(), "install"], cwd=WEB, check=True)
    subprocess.run([_bun(), "run", "build"], cwd=WEB, check=True)
    assert (dist / "index.html").is_file()
    stamp.write_text(digest, encoding="utf-8")
    return dist


def bundle_text(dist: Path) -> str:
    parts: list[str] = []
    for path in dist.rglob("*"):
        if path.is_file() and path.suffix in {".js", ".css", ".html"} and path.name != ".built":
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _serve(dist: Path, hits: list[str]) -> tuple[ThreadingHTTPServer, int]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            hits.append(path)
            if path.startswith("/api/"):
                body = b'{"code":"UNAVAILABLE"}'
                self.send_response(503)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            rel = path.lstrip("/") or "index.html"
            target = dist / rel
            if not target.is_file():
                target = dist / "index.html"
            data = target.read_bytes()
            self.send_response(200)
            if target.suffix == ".js":
                kind = "text/javascript"
            elif target.suffix == ".css":
                kind = "text/css"
            else:
                kind = "text/html"
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


def _me_hits(hits: list[str]) -> int:
    return sum(1 for path in hits if path.startswith("/api/v1/me"))


def test_w3_c01_contract() -> None:
    """A down API shows an error and a focused retry control instead of a blank page."""
    dist = build_web()
    hits: list[str] = []
    server, port = _serve(dist, hits)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/login", wait_until="domcontentloaded")
            alert = page.get_by_role("alert")
            expect(alert).to_be_visible(timeout=10000)
            assert re.search(r"error|错误|未就绪|无法连接", alert.inner_text(), re.I)
            retry = page.get_by_role("button", name=re.compile(r"retry|重试", re.I))
            retry.focus()
            active = page.evaluate("() => document.activeElement?.textContent || ''")
            assert re.search(r"retry|重试", active, re.I)
            assert page.locator("main").inner_text().strip()
            assert _me_hits(hits) >= 1
            before = _me_hits(hits)
            retry.click()
            deadline = time.time() + 5
            while time.time() < deadline and _me_hits(hits) <= before:
                time.sleep(0.05)
            assert _me_hits(hits) > before
            expect(alert).to_be_visible()
            browser.close()
    finally:
        server.shutdown()


def test_w3_c01_negative() -> None:
    """The browser bundle has no Electron API, node builtins, or stored secret."""
    dist = build_web()
    text = bundle_text(dist)
    assert text.strip()
    for needle in _FORBIDDEN:
        assert needle not in text, needle
    assert "require(\"fs\")" not in text
    assert "from\"fs\"" not in text
    assert "from 'fs'" not in text
