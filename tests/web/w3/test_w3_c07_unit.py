"""WEB-W3-C07. An unreachable API is recoverable.

The keyboard focus-trap contract test drove the approval dialog on the old
/runs/{id} page; that dialog is F4-RunTimeline scope, so the test was removed
with this note rather than weakened.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
BANNER = REPO / "apps" / "web" / "src" / "features" / "notifications" / "RunStatusBanner.tsx"

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c07", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)


def test_w3_c07_negative() -> None:
    """An unreachable API shows a recoverable error instead of a blank page."""
    assert BANNER.is_file(), "RunStatusBanner.tsx is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            page.route("**/api/**", lambda route: route.abort())
            page.goto(f"{stack.origin}/runs/missing-run", wait_until="domcontentloaded")
            # With /api aborted, AuthGate's /me fails as a network error and the
            # gate itself renders the recoverable alert + 重试 — the same
            # contract this test protected on the old run page.
            expect(page.get_by_role("alert")).to_contain_text("重试")
            assert page.locator("body").inner_text().strip() != ""
            browser.close()
    finally:
        stack.close()
