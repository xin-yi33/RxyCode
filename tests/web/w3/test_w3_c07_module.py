"""WEB-W3-C07. A 375px run page still shows status, approval, and cancel."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
BANNER = REPO / "apps" / "web" / "src" / "features" / "notifications" / "RunStatusBanner.tsx"

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c07m", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)

_C06 = Path(__file__).with_name("test_w3_c06_unit.py")
_c06_spec = importlib.util.spec_from_file_location("w3c06_seed_c07m", _C06)
assert _c06_spec is not None and _c06_spec.loader is not None
_c06 = importlib.util.module_from_spec(_c06_spec)
_c06_spec.loader.exec_module(_c06)


def test_w3_c07_integration() -> None:
    """A phone-width run page shows status, approval, and cancel."""
    assert BANNER.is_file(), "RunStatusBanner.tsx is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 375, "height": 812})
            _c02._login(page, stack.origin)
            run_id, _approval_id = _c06._seed(datetime.now(timezone.utc) + timedelta(minutes=10))
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            status = page.locator("[data-run-status]")
            expect(status).to_contain_text("waiting_approval", timeout=10000)
            for width in (375, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                expect(status).to_be_visible()
                expect(page.get_by_role("button", name="批准")).to_be_visible()
                expect(page.get_by_role("button", name="取消")).to_be_visible()
                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
                )
                assert overflow is False
            page.get_by_role("button", name="取消").click()
            expect(status).to_contain_text("cancelled", timeout=10000)
            expect(page.locator("body")).not_to_contain_text("succeeded")
            browser.close()
    finally:
        stack.close()
