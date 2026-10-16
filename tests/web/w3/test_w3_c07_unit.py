"""WEB-W3-C07. Keyboard focus returns, and an unreachable API is recoverable."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
BANNER = REPO / "apps" / "web" / "src" / "features" / "notifications" / "RunStatusBanner.tsx"
RESPONSIVE = REPO / "apps" / "web" / "src" / "app" / "responsive.css"

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c07", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)

_C06 = Path(__file__).with_name("test_w3_c06_unit.py")
_c06_spec = importlib.util.spec_from_file_location("w3c06_seed_c07", _C06)
assert _c06_spec is not None and _c06_spec.loader is not None
_c06 = importlib.util.module_from_spec(_c06_spec)
_c06_spec.loader.exec_module(_c06)


def test_w3_c07_contract() -> None:
    """Opening the approval dialog traps focus and restores it on close."""
    assert BANNER.is_file(), "RunStatusBanner.tsx is missing"
    assert RESPONSIVE.is_file(), "responsive.css is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            run_id, _approval_id = _c06._seed(_c06.datetime(2099, 1, 2, tzinfo=_c06.timezone.utc))
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            opener = page.get_by_role("button", name="打开审批")
            opener.focus()
            opener.press("Enter")
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            page.keyboard.press("Tab")
            assert dialog.locator(":focus").count() == 1
            page.keyboard.press("Escape")
            expect(opener).to_be_focused()
            browser.close()
    finally:
        stack.close()


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
            expect(page.get_by_role("alert")).to_contain_text("重试")
            assert page.locator("body").inner_text().strip() != ""
            browser.close()
    finally:
        stack.close()
