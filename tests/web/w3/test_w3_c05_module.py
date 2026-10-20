"""WEB-W3-C05. Reloading the page leaves the PTY alive and can attach again."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
PANE = REPO / "apps" / "web" / "src" / "features" / "terminal" / "TerminalPane.tsx"
_UNIT = Path(__file__).with_name("test_w3_c05_unit.py")
_spec = importlib.util.spec_from_file_location("w3c05_unit_mod", _UNIT)
assert _spec is not None and _spec.loader is not None
_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_unit)


def test_w3_c05_integration() -> None:
    """A refresh does not kill the PTY, and the page can show the same output."""
    assert PANE.is_file(), "TerminalPane.tsx is missing"
    stack = _unit._c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _unit._c02._login(page, stack.origin)
            opened = _unit._open(page, stack.origin)
            cookies = {item["name"]: item["value"] for item in page.context.cookies()}
            from websockets.sync.client import connect

            uri = f"ws://127.0.0.1:{stack.api_port}/api/v1/terminals/{opened['id']}/ws"
            with connect(
                uri,
                additional_headers={
                    "Cookie": f"rxy_session={cookies['rxy_session']}",
                    "Origin": stack.origin,
                },
                open_timeout=10,
            ) as socket:
                seen = ""
                socket.send(json.dumps({"type": "input", "data": "print('c05-stay')\r\n"}))
                while "c05-stay" not in seen:
                    seen += str(json.loads(socket.recv(timeout=15))["data"])
            page.goto(
                f"{stack.origin}/terminal/{opened['id']}",
                wait_until="domcontentloaded",
            )
            page.reload(wait_until="domcontentloaded")
            status = page.request.get(f"{stack.origin}/api/v1/terminals/{opened['id']}")
            assert status.ok
            body = status.json()
            assert body["alive"] is True
            assert body["exit_code"] is None
            expect(page.locator("body")).to_contain_text("c05-stay", timeout=10000)
            browser.close()
    finally:
        stack.close()
