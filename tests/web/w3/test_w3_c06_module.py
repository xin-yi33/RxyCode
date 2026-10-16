"""WEB-W3-C06. Approve does not mark the run succeeded before the server says so."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
CARD = REPO / "apps" / "web" / "src" / "features" / "approvals" / "ApprovalCard.tsx"
_UNIT = Path(__file__).with_name("test_w3_c06_unit.py")
_spec = importlib.util.spec_from_file_location("w3c06_unit_mod", _UNIT)
assert _spec is not None and _spec.loader is not None
_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_unit)


def test_w3_c06_integration() -> None:
    """While the approve request is still open, the page does not say succeeded."""
    assert CARD.is_file(), "ApprovalCard.tsx is missing"
    from datetime import datetime, timedelta, timezone

    stack = _unit._c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _unit._c02._login(page, stack.origin)
            run_id, _approval_id = _unit._seed(datetime.now(timezone.utc) + timedelta(minutes=10))
            held: list = []

            def gate(route) -> None:
                if route.request.method == "POST" and "/approvals" in route.request.url:
                    held.append(route)
                    return
                route.continue_()

            page.route("**/*", gate)
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            page.locator("[data-approval-card]").get_by_role("button", name="批准").click()
            for _ in range(50):
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "the approve request never reached the server"
            expect(page.locator("body")).not_to_contain_text("succeeded")
            held[0].continue_()
            page.wait_for_timeout(500)
            expect(page.locator("body")).not_to_contain_text("succeeded")
            browser.close()
    finally:
        stack.close()
