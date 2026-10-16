"""WEB-W3-C05. A real PTY echoes python -i, and another tenant cannot attach."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
PANE = REPO / "apps" / "web" / "src" / "features" / "terminal" / "TerminalPane.tsx"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c05", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)


def _open(page, origin: str) -> dict[str, object]:
    csrf = page.request.get(f"{origin}/api/v1/auth/csrf")
    assert csrf.ok
    token = csrf.json()["csrf_token"]
    created = page.request.post(
        f"{origin}/api/v1/terminals",
        data=json.dumps(
            {
                "argv": [sys.executable, "-i", "-u"],
                "cols": 80,
                "rows": 24,
                "tenant_id": "other-tenant",
                "host": "evil.example",
            }
        ),
        headers={
            "content-type": "application/json",
            "origin": origin,
            "x-csrf-token": token,
        },
    )
    assert created.status == 201, created.text()
    body = created.json()
    assert body.get("host") != "evil.example"
    assert body.get("tenant_id") != "other-tenant"
    assert isinstance(body.get("pid"), int)
    assert body.get("exit_code") is None
    return body


def test_w3_c05_contract() -> None:
    """python -i prints the typed expression, resizes, and returns a real exit code."""
    assert PANE.is_file(), "TerminalPane.tsx is missing"
    if str(_RUNNER) not in sys.path:
        sys.path.insert(0, str(_RUNNER))
    from rxycode_runner.local.pty import live_pids
    from websockets.sync.client import connect

    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            opened = _open(page, stack.origin)
            cookies = {item["name"]: item["value"] for item in page.context.cookies()}
            uri = f"ws://127.0.0.1:{stack.api_port}/api/v1/terminals/{opened['id']}/ws"
            with connect(
                uri,
                additional_headers={"Cookie": f"rxy_session={cookies['rxy_session']}"},
                open_timeout=10,
            ) as socket:
                seen = ""
                socket.send(json.dumps({"type": "input", "data": "print('c05-ok')\r\n"}))
                while "c05-ok" not in seen:
                    seen += str(json.loads(socket.recv(timeout=15))["data"])
                socket.send(json.dumps({"type": "resize", "cols": 40, "rows": 12}))
                socket.send(
                    json.dumps(
                        {
                            "type": "input",
                            "data": "import shutil; print(tuple(shutil.get_terminal_size()))\r\n",
                        }
                    )
                )
                while "(40, 12)" not in seen:
                    seen += str(json.loads(socket.recv(timeout=15))["data"])
                socket.send(json.dumps({"type": "input", "data": "exit()\r\n"}))
                code = None
                while code is None:
                    frame = json.loads(socket.recv(timeout=15))
                    if frame.get("type") == "exit":
                        code = frame["exit_code"]
                    elif "data" in frame:
                        seen += str(frame["data"])
            assert code == 0
            assert opened["pid"] not in set(live_pids())
            page.goto(
                f"{stack.origin}/terminal/{opened['id']}",
                wait_until="domcontentloaded",
            )
            expect(page.locator(".xterm")).to_be_visible(timeout=10000)
            browser.close()
    finally:
        stack.close()


def test_w3_c05_negative() -> None:
    """A foreign session cookie is rejected and does not start another process."""
    assert PANE.is_file(), "TerminalPane.tsx is missing"
    if str(_RUNNER) not in sys.path:
        sys.path.insert(0, str(_RUNNER))
    from rxycode_runner.local.pty import live_pids
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            opened = _open(page, stack.origin)
            before = set(live_pids())
            uri = f"ws://127.0.0.1:{stack.api_port}/api/v1/terminals/{opened['id']}/ws"
            refused = False
            try:
                with connect(
                    uri,
                    additional_headers={"Cookie": "rxy_session=not-the-owner"},
                    open_timeout=10,
                ) as socket:
                    socket.recv(timeout=3)
            except InvalidStatus:
                refused = True
            except Exception as exc:
                refused = True
                assert "403" in str(exc) or "401" in str(exc) or "refused" in str(exc).lower()
            assert refused
            assert set(live_pids()) == before
            status = page.request.get(f"{stack.origin}/api/v1/terminals/{opened['id']}")
            assert status.ok
            body = status.json()
            assert body["pid"] == opened["pid"]
            assert body["alive"] is True
            assert body["exit_code"] is None
            browser.close()
    finally:
        stack.close()
