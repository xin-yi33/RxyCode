"""Shared Playwright harness for the W3 chat-polish contract tests.

This module owns the expensive/duplicated machinery so the three chat contract
modules do not copy server-start or stub code:

* production build + vite preview origin (session-scoped fixture);
* per-test Chromium browser fixture and viewport/context helpers;
* ChatApi - a deterministic page.route stub for the whole /api/v1 surface that
  also records every write (task POSTs etc.);
* a controllable EventSource stub (installed before the app boots) so tests can
  push SSE frames at exact moments instead of waiting on real sockets;
* small DOM helpers (scroll distance, colors, overflow, whitespace, probes).

Honesty rules for the contract tests built on top of this harness:

* the harness only delivers deterministic API/SSE data - it never fabricates
  UI behavior;
* a contract item whose DOM marker is missing must be reported with
  pytest.skip(reason=...); a present-but-wrong implementation must FAIL.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page, sync_playwright

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
_WORKER = re.sub(r"[^A-Za-z0-9_]", "_", os.environ.get("PYTEST_XDIST_WORKER") or "main")
DIST = WEB / ("dist" if _WORKER == "main" else f"dist-{_WORKER}")

# Viewports named in the chat-polish contract (320/375/768/1440 widths).
VIEWPORTS: dict[str, tuple[int, int]] = {
    "mobile-320": (320, 640),
    "mobile-375": (375, 812),
    "tablet-768": (768, 1024),
    "desktop-1440": (1440, 900),
}

# Data-testid / class contract shared with the implementers.
TESTID_COMPOSER = "chat-composer"
TESTID_SCROLL = "chat-scroll"
TESTID_JUMP = "chat-jump-to-latest"
TESTID_PREVIEW_SPLIT = "chat-preview-split"
TESTID_PREVIEW_HANDLE = "chat-preview-handle"
TESTID_FILE_NAME = "chat-file-name"
CLASS_STREAM_GLYPH = "rxy-stream-glyph"
CLASS_COLLAPSE = "rxy-collapse"
CLASS_COLLAPSE_INNER = "rxy-collapse-inner"

# ---------------------------------------------------------------------------
# build + preview server
# ---------------------------------------------------------------------------


@contextmanager
def _preview_server(out_dir: Path) -> Iterator[str]:
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        pytest.skip("Node.js and the installed apps/web Vite dependency are required")

    subprocess.run(
        [node, str(vite), "build", "--outDir", out_dir.name],
        cwd=WEB,
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [
            node,
            str(vite),
            "preview",
            "--outDir",
            out_dir.name,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Vite preview exited with {server.returncode}")
            try:
                with urlopen(origin, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite preview did not become ready in 60 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


@pytest.fixture(scope="session")
def production_origin() -> str:
    """Build the shipped apps/web bundle once and serve it with vite preview.

    Shared by every W3 browser-contract module (do not redefine it per file).
    """
    with _preview_server(DIST) as origin:
        yield origin


# Playwright engines installed and launchable on this host. Tests use
# `browser` (chromium) by default; the cross-engine regression subset uses
# `engine_browser` + `engine_name`.
ENGINES: tuple[str, ...] = ("chromium", "firefox", "webkit")


def launch_browser(playwright, engine: str) -> Browser:
    """Launch one installed Playwright engine (no server/browser duplication)."""
    if engine == "chromium":
        executable = os.environ.get("RXY_MOBILE_CHROMIUM")
        if executable and not Path(executable).is_file():
            pytest.fail(f"RXY_MOBILE_CHROMIUM does not exist: {executable}")
        return playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
        )
    launcher = getattr(playwright, engine)
    return launcher.launch(headless=True)


@pytest.fixture
def browser() -> Browser:
    """Function-scoped Chromium.

    A session-scoped sync_playwright() stays open for the whole xdist worker and
    breaks later with-blocks; keep this function-scoped like the mobile module.
    """
    with sync_playwright() as playwright:
        try:
            instance = launch_browser(playwright, "chromium")
        except Exception as exc:  # pragma: no cover - environment guard
            pytest.skip(f"Chromium could not launch ({exc}); set RXY_MOBILE_CHROMIUM")
        yield instance
        instance.close()


@pytest.fixture(params=ENGINES)
def engine_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def engine_browser(engine_name: str) -> Browser:
    """Cross-engine fixture for the key regression subset (chromium/firefox/webkit)."""
    with sync_playwright() as playwright:
        try:
            instance = launch_browser(playwright, engine_name)
        except Exception as exc:  # pragma: no cover - environment guard
            pytest.skip(f"{engine_name} could not launch ({exc})")
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def dev_origin() -> str:
    """Vite dev server origin for component harness pages (preview split harness).

    The production bundle is the app under test; the harness page only renders
    already-shipped components (`apps/web/preview-harness.html`), which vite
    build does not emit. Startup lives here so no test module copies it.
    """
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        pytest.skip("Node.js and the installed apps/web Vite dependency are required")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [node, str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Vite dev server exited with {server.returncode}")
            try:
                with urlopen(origin + "/preview-harness.html", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite dev server did not become ready in 60 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


# ---------------------------------------------------------------------------
# contexts / pages
# ---------------------------------------------------------------------------


def new_context(
    browser: Browser,
    width: int = 1440,
    height: int = 900,
    *,
    mobile: bool = False,
    reduced_motion: str | None = None,
) -> BrowserContext:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2 if mobile else 1,
        is_mobile=mobile,
        has_touch=mobile,
        locale="zh-CN",
    )
    # reduced-motion is applied per page (Playwright exposes emulate_media on Page,
    # not BrowserContext): use apply_reduced_motion(page, value) after new_page().
    return context


def apply_reduced_motion(page: Page, value: str | None) -> None:
    if value:
        page.emulate_media(reduced_motion=value)  # "reduce" | "no-preference"


def context_for(browser: Browser, viewport: str = "desktop-1440") -> BrowserContext:
    width, height = VIEWPORTS[viewport]
    return new_context(browser, width, height, mobile=viewport.startswith("mobile"))


def open_page(
    context: BrowserContext,
    origin: str,
    path: str,
    *,
    clock: bool = False,
) -> Page:
    page = context.new_page()
    if clock:
        # Must be installed BEFORE the app's timers are created (IME 500ms guard).
        page.clock.install()
    page.goto(f"{origin}{path}")
    return page


def no_horizontal_overflow(page: Page) -> None:
    widths = page.evaluate(
        "() => ({document: document.documentElement.scrollWidth, window: innerWidth})"
    )
    assert widths["document"] <= widths["window"] + 1, widths


def norm_ws(text: str | None) -> str:
    return " ".join((text or "").split())


# ---------------------------------------------------------------------------
# API stub
# ---------------------------------------------------------------------------

ME = {
    "user": {
        "id": "user-ui-fixture",
        "kind": "password",
        "email": "synthetic-ui@example.invalid",
        "display_name": "Synthetic UI fixture",
        "github_id": None,
    },
    "organization": {"id": "org-ui-fixture", "tenant_id": "tenant-ui-fixture"},
    "membership": {"role": "owner"},
    "default_project_id": None,
}

DEFAULT_PREFS: dict[str, Any] = {
    "revision": 1,
    "locale": "auto",
    "sidebar": {"grouping": "merged", "sort": "updated_at", "show_projects": True},
    "appearance": {
        "mode": "light",
        "separate_modes": False,
        "shared": {},
        "light": None,
        "dark": None,
        "reduced_motion": "system",
        "diff_markers": "color",
    },
}

CAPABILITIES = {
    "mode": "password",
    "password": True,
    "registration": "open",
    "github": False,
    "local": False,
    "captcha": None,
    "code_delivery": "none",
}

MODELS: dict[str, Any] = {
    "models": [
        {
            "model_ref": "m_byok_test",
            "model_id": "byok-test",
            "display_name": "测试模型",
            "provider_id": "provider-test",
            "provider_name": "测试服务商",
            "connection_id": "conn-test",
            "connection_name": "测试连接",
            "source": "byok",
            "status": "available",
        }
    ],
    "default_model_ref": "m_byok_test",
}


def session_row(
    session_id: str,
    title: str = "聊天契约会话",
    last_run: dict[str, str] | None = None,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": session_id,
        "title": title,
        "project_id": "project-ui-fixture",
        "updated_at": updated_at,
        "last_run": last_run,
    }


def run_summary(
    run_id: str,
    status: str,
    message: str,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "created_at": created_at,
        "message": message,
        "permission_profile": "confirm",
        "final_preview": "",
        "model": None,
    }


def tool_filler_events(count: int = 40, *, start_seq: int = 2) -> list[dict[str, Any]]:
    """Enough single-line tool rows to make the timeline taller than a viewport."""
    events: list[dict[str, Any]] = []
    seq = start_seq
    for index in range(count):
        events.append(
            {
                "seq": seq,
                "type": "tool.completed",
                "payload": {
                    "tool": "bash",
                    "call_id": f"call_filler_{index:03d}",
                    "summary": f"filler command number {index}",
                    "status": "success",
                },
            }
        )
        seq += 1
    return events


def chat_events(
    *,
    message: str = "请总结这次改动",
    tool_rows: int = 40,
    final: str | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"seq": 1, "type": "run.created", "payload": {"message": message}},
    ]
    events.extend(tool_filler_events(tool_rows, start_seq=2))
    if final is not None:
        events.append(
            {
                "seq": events[-1]["seq"] + 1,
                "type": "assistant.final",
                "payload": {"text": final},
            }
        )
    return events


def sse_body(events: list[dict[str, Any]]) -> str:
    return "".join(
        "data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events
    )


class ChatApi:
    """Deterministic /api/v1 stub with write recording.

    Configure runs/events/artifacts per test; the stub fills the shell
    endpoints (auth, prefs, models, sessions) with a consistent authed state.
    """

    def __init__(
        self,
        *,
        sessions: list[dict[str, Any]] | None = None,
        session: dict[str, Any] | None = None,
        runs: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        session_files: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        prefs: dict[str, Any] | None = None,
        events_by_run: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.session = session or session_row("session-chat-1")
        self.sessions = sessions or [self.session]
        self.runs = runs or [run_summary("run-chat-1", "succeeded", "请总结这次改动")]
        self.events = events if events is not None else chat_events()
        self.events_by_run = events_by_run or {}
        self.session_files = session_files or []
        self.artifacts = artifacts or []
        self.prefs = json.loads(json.dumps(prefs or DEFAULT_PREFS))
        self.writes: list[dict[str, Any]] = []
        self.task_posts: list[dict[str, Any]] = []
        self.preview_creates = 0
        self._new_run_seq = 0

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _json(route, status: int, payload: object) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    def _record(self, request) -> None:
        method = request.method.upper()
        if method in {"GET", "HEAD"}:
            return
        try:
            body = json.loads(request.post_data or "{}")
        except ValueError:
            body = {}
        self.writes.append(
            {"method": method, "path": urlparse(request.url).path, "body": body}
        )

    def events_for(self, run_id: str) -> list[dict[str, Any]]:
        if run_id in self.events_by_run:
            return self.events_by_run[run_id]
        if self.runs and run_id == self.runs[-1]["run_id"]:
            return self.events
        return []

    def handle(self, route) -> None:
        request = route.request
        method = request.method.upper()
        path = urlparse(request.url).path
        self._record(request)

        if method == "PATCH" and path == "/api/v1/me/preferences":
            try:
                body = json.loads(request.post_data or "{}")
            except ValueError:
                body = {}
            appearance = body.get("appearance") or {}
            if isinstance(appearance, dict):
                self.prefs["appearance"].update(appearance)
            self.prefs["revision"] = int(self.prefs.get("revision", 1)) + 1
            self._json(route, 200, self.prefs)
            return
        if path == "/api/v1/me/preferences":
            self._json(route, 200, self.prefs)
            return
        if path == "/api/v1/me":
            self._json(route, 200, ME)
            return
        if path == "/api/v1/auth/csrf":
            self._json(route, 200, {"csrf_token": "chat-contract-csrf"})
            return
        if path == "/api/v1/auth/capabilities":
            self._json(route, 200, CAPABILITIES)
            return
        if path == "/api/v1/auth/device":
            self._json(route, 200, {"status": "active"})
            return
        if path == "/api/v1/models/access":
            self._json(
                route,
                200,
                {
                    "require_byok": False,
                    "platform_allowed": True,
                    "byok_available": True,
                    "default_model_ref": "m_byok_test",
                },
            )
            return
        if path == "/api/v1/models":
            self._json(route, 200, MODELS)
            return
        if path == "/api/v1/models/providers":
            self._json(route, 200, {"providers": []})
            return
        if path == "/api/v1/model-connections":
            self._json(route, 200, {"connections": []})
            return
        if path == "/api/v1/projects":
            self._json(route, 200, {"projects": []})
            return
        if path == "/api/v1/sessions":
            self._json(route, 200, {"sessions": self.sessions})
            return
        if path == "/api/v1/tasks" and method == "POST":
            if request.post_data:
                self.task_posts.append(json.loads(request.post_data))
            run_id = self._next_run_id()
            self._json(
                route,
                200,
                {
                    "run_id": run_id,
                    "status": "queued",
                    "session_id": self.session["id"],
                    "events_url": f"/api/v1/runs/{run_id}/events",
                },
            )
            return
        if path == f"/api/v1/sessions/{self.session['id']}":
            self._json(route, 200, self.session)
            return
        if path == f"/api/v1/sessions/{self.session['id']}/runs":
            if method == "POST":
                body = json.loads(request.post_data or "{}")
                self.task_posts.append(body)
                run_id = self._next_run_id()
                new_run = run_summary(run_id, "queued", str(body.get("message") or ""))
                self.runs.append(new_run)
                self._json(
                    route,
                    200,
                    {
                        "run_id": run_id,
                        "status": "queued",
                        "session_id": self.session["id"],
                        "events_url": f"/api/v1/runs/{run_id}/events",
                    },
                )
                return
            self._json(route, 200, {"runs": list(self.runs), "next_cursor": None})
            return
        if path == f"/api/v1/sessions/{self.session['id']}/files":
            self._json(route, 200, {"files": self.session_files})
            return
        if path.startswith("/api/v1/previews") and method == "POST":
            self.preview_creates += 1
            self._json(route, 200, self._preview_job())
            return
        if path.startswith("/api/v1/previews/"):
            self._json(route, 200, self._preview_job())
            return
        if path.startswith("/api/v1/runs/"):
            self._handle_run(route, path)
            return
        self._json(route, 200, {})

    def _preview_job(self) -> dict[str, Any]:
        return {
            "preview_id": "preview-fixture-1",
            "artifact_id": "artifact-fixture-1",
            "run_id": self.runs[-1]["run_id"] if self.runs else "run-chat-1",
            "sha256": "0" * 64,
            "kind": "frontend_static",
            "status": "ready",
            "entrypoint": "index.html",
            "preview_url": "about:blank",
            "error_code": None,
            "reason": None,
            "expires_at": None,
        }

    def _handle_run(self, route, path: str) -> None:
        parts = path.split("/")
        run_id = parts[4] if len(parts) > 4 else ""
        suffix = "/".join(parts[5:])
        known = {run["run_id"]: run for run in self.runs}
        summary = known.get(run_id)
        if suffix == "events":
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=sse_body(self.events_for(run_id)),
            )
            return
        if suffix == "artifacts":
            self._json(
                route,
                200,
                {
                    "run_id": run_id,
                    "manifest_status": "complete",
                    "manifest_revision": 1,
                    "next_cursor": None,
                    "artifacts": list(self.artifacts),
                },
            )
            return
        if suffix == "questions":
            self._json(route, 200, {"questions": []})
            return
        if suffix == "approvals":
            self._json(route, 200, {"approvals": []})
            return
        if suffix == "cancel":
            self._json(route, 200, {"status": "cancel_requested"})
            return
        if suffix == "" and summary is not None:
            self._json(
                route,
                200,
                {
                    "run_id": run_id,
                    "status": summary["status"],
                    "session_id": self.session["id"],
                    "event_seq": len(self.events_for(run_id)),
                    "created_at": summary.get("created_at"),
                    "message": summary.get("message", ""),
                    "permission_profile": "confirm",
                    "model": None,
                },
            )
            return
        self._json(route, 200, {})

    def _next_run_id(self) -> str:
        self._new_run_seq += 1
        return f"run-chat-new-{self._new_run_seq}"


# ---------------------------------------------------------------------------
# EventSource stub (controllable SSE) and page setup
# ---------------------------------------------------------------------------

SSE_MOCK_SCRIPT = r"""
(() => {
  if (window.__rxySseMockInstalled) return;
  window.__rxySseMockInstalled = true;
  const sources = [];
  window.__rxySseMock = {};
  class MockEventSource extends EventTarget {
    constructor(url) {
      super();
      this.url = String(url);
      this.readyState = 0;
      this.withCredentials = false;
      this._closed = false;
      this.onopen = null;
      this.onmessage = null;
      this.onerror = null;
      sources.push(this);
      setTimeout(() => {
        if (this._closed) return;
        this.readyState = 1;
        const event = new Event('open');
        if (this.onopen) this.onopen(event);
        this.dispatchEvent(event);
      }, 0);
    }
    close() {
      this._closed = true;
      this.readyState = 2;
    }
  }
  MockEventSource.CONNECTING = 0;
  MockEventSource.OPEN = 1;
  MockEventSource.CLOSED = 2;
  MockEventSource.prototype.CONNECTING = 0;
  MockEventSource.prototype.OPEN = 1;
  MockEventSource.prototype.CLOSED = 2;
  window.EventSource = MockEventSource;
  window.__rxySseMock.push = (event) => {
    const data = JSON.stringify(event);
    let open = 0;
    for (const source of sources) {
      if (source._closed) continue;
      open += 1;
      const message = new MessageEvent('message', { data });
      if (source.onmessage) source.onmessage(message);
      source.dispatchEvent(message);
    }
    return open;
  };
  window.__rxySseMock.pushRaw = (data) => {
    for (const source of sources) {
      if (source._closed) continue;
      const message = new MessageEvent('message', { data });
      if (source.onmessage) source.onmessage(message);
      source.dispatchEvent(message);
    }
  };
  window.__rxySseMock.error = () => {
    for (const source of sources) {
      if (source._closed) continue;
      const event = new Event('error');
      if (source.onerror) source.onerror(event);
      source.dispatchEvent(event);
    }
  };
  window.__rxySseMock.instances = () =>
    sources.map((source) => ({ url: source.url, closed: source._closed }));
  window.__rxySseMock.openCount = () =>
    sources.filter((source) => !source._closed).length;
})();
"""


def install_event_stream_mock(page: Page) -> None:
    page.add_init_script(SSE_MOCK_SCRIPT)


# Fake clock starts ticking after install(); pausing it is what makes the
# 499/500/501ms and 2499/2500ms boundaries exact. `page.wait_for_function`
# polling is unsafe under a paused clock, so all waits below poll from Python.
def install_paused_clock(page: Page) -> None:
    """Install a fake clock and freeze it right away.

    Must run AFTER the app booted (installing before navigation stalls boot timers).
    install() starts at the current time; pause_at() needs a target that is not in
    the past, so freeze half a second ahead.
    """
    page.clock.install()
    now_ms = page.evaluate("Date.now()")
    page.clock.pause_at((now_ms + 500) / 1000.0)


def wait_for_attribute(
    page: Page,
    selector: str,
    attribute: str,
    expected: str,
    timeout_s: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = page.evaluate(
            """({ selector, attribute }) => {
              const node = document.querySelector(selector);
              return node ? node.getAttribute(attribute) : null;
            }""",
            {"selector": selector, "attribute": attribute},
        )
        if last == expected:
            return
        time.sleep(0.03)
    raise AssertionError(
        f"{selector} [{attribute}] stayed {last!r}, expected {expected!r} after {timeout_s}s"
    )


def dom_visible(page: Page, selector: str) -> bool:
    return bool(
        page.evaluate(
            """(selector) => {
              const node = document.querySelector(selector);
              if (!node) return false;
              const style = getComputedStyle(node);
              if (style.display === 'none' || style.visibility === 'hidden') return false;
              if (Number(style.opacity) === 0) return false;
              const rect = node.getBoundingClientRect();
              return rect.width > 0 || rect.height > 0;
            }""",
            selector,
        )
    )


def install_api(page: Page, api: ChatApi) -> None:
    page.route("**/api/v1/**", api.handle)


def push_sse(page: Page, event: dict[str, Any]) -> int:
    """Deliver one SSE frame to every open (stubbed) EventSource."""
    return int(page.evaluate("(event) => window.__rxySseMock.push(event)", event))


def wait_sse_open(page: Page, timeout: float = 10_000) -> None:
    page.wait_for_function(
        "() => window.__rxySseMock && window.__rxySseMock.openCount() > 0",
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# probes / DOM helpers
# ---------------------------------------------------------------------------


def probe(page: Page, selector: str, *, reason: str) -> Locator:
    """Return a locator or skip the test with the given unimplemented reason."""
    locator = page.locator(selector)
    try:
        locator.first.wait_for(state="attached", timeout=5000)
    except Exception:
        pytest.skip(reason)
    return locator


def probe_testid(page: Page, testid: str, *, feature: str) -> Locator:
    return probe(
        page,
        f'[data-testid="{testid}"]',
        reason=f"{feature} not implemented yet: [data-testid={testid}] absent from DOM",
    )


def composer_box(page: Page) -> Locator:
    return page.get_by_role("textbox", name="消息")


def chat_scroll(page: Page) -> Locator:
    return probe_testid(
        page,
        TESTID_SCROLL,
        feature="single chat scroll container (task-6 useChatScrollController)",
    )


def wait_for_chat(page: Page, origin: str, api: ChatApi, path: str | None = None) -> None:
    """Navigate to the stub session and wait for the composer to exist."""
    target = path or f"/app/s/{api.session['id']}"
    page.goto(f"{origin}{target}")
    page.get_by_role("textbox", name="消息").wait_for(timeout=30_000)


def scroll_metrics(
    page: Page, selector: str = f'[data-testid="{TESTID_SCROLL}"]'
) -> dict[str, float]:
    return page.eval_on_selector(
        selector,
        """(el) => ({
          scrollTop: el.scrollTop,
          scrollHeight: el.scrollHeight,
          clientHeight: el.clientHeight,
          distanceToBottom: el.scrollHeight - el.scrollTop - el.clientHeight,
          overflowY: getComputedStyle(el).overflowY,
        })""",
    )


def distance_to_bottom(
    page: Page, selector: str = f'[data-testid="{TESTID_SCROLL}"]'
) -> float:
    return float(scroll_metrics(page, selector)["distanceToBottom"])


def scroll_to_distance(
    page: Page,
    distance: float,
    selector: str = f'[data-testid="{TESTID_SCROLL}"]',
    *,
    settle_ms: int = 120,
) -> None:
    """Place the scroll container at an exact distance from the bottom."""
    page.eval_on_selector(
        selector,
        """(el, target) => {
          el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight - target);
          el.dispatchEvent(new Event('scroll', { bubbles: true }));
        }""",
        distance,
    )
    page.wait_for_timeout(settle_ms)


def is_scrollable(
    page: Page, selector: str = f'[data-testid="{TESTID_SCROLL}"]'
) -> bool:
    metrics = scroll_metrics(page, selector)
    return metrics["scrollHeight"] > metrics["clientHeight"] + 1


def color_to_rgb(value: str) -> tuple[int, int, int]:
    text = (value or "").strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
        )
    match = re.match(r"rgba?\(([^)]+)\)", text)
    if not match:
        raise AssertionError(f"not a color: {value!r}")
    parts = [part.strip() for part in match.group(1).replace("/", " ").split(",")]
    channels: list[int] = []
    for part in parts[:3]:
        if part.endswith("%"):
            channels.append(round(float(part[:-1]) * 2.55))
        else:
            channels.append(round(float(part.split()[0])))
    return (channels[0], channels[1], channels[2])


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def css_var(page: Page, name: str) -> str:
    return page.evaluate(
        "(name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()",
        name,
    )


def has_css_var(page: Page, name: str) -> bool:
    return bool(css_var(page, name))


def element_is_non_focusable(page: Page, selector: str) -> bool:
    """Behavioral check: try to focus the node; true when focus cannot land."""
    return bool(
        page.evaluate(
            """(selector) => {
              const node = document.querySelector(selector);
              if (!node) return true;
              const target = node.matches('button, a, input, textarea, select, [tabindex]')
                ? node
                : node.querySelector('button, a, input, textarea, select, [tabindex]');
              if (!target) return true;
              target.focus({ preventScroll: true });
              return document.activeElement !== target;
            }""",
            selector,
        )
    )
