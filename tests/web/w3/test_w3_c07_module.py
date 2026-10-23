"""WEB-W3-C07. A 375px session page still shows status without overflow."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
AXE = REPO / "apps" / "web" / "node_modules" / "axe-core" / "axe.min.js"

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
    """A phone-width session page shows the parked status without overflow."""
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 375, "height": 812})
            _c02._login(page, stack.origin)
            # c06's _seed resolves its own copy of the c02 module — point it at
            # this stack's per-stack database or it seeds into the base db.
            _c06._c02.URL = stack.url
            run_id, _approval_id = _c06._seed(datetime.now(timezone.utc) + timedelta(minutes=10))
            # /runs/{id} now resolves to the owning session page; the approve/
            # cancel buttons on the card are F4-RunTimeline scope, so the
            # responsive + a11y contract is asserted on the session page.
            session_id = page.request.get(
                f"{stack.origin}/api/v1/runs/{run_id}"
            ).json()["session_id"]
            page.goto(
                f"{stack.origin}/app/s/{session_id}", wait_until="domcontentloaded"
            )
            status = page.locator("[data-run-status='waiting_approval']").first
            expect(status).to_be_visible(timeout=10000)
            for width in (375, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                expect(status).to_be_visible()
                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
                )
                assert overflow is False
            expect(page.locator("body")).not_to_contain_text("succeeded")
            expect(page.locator("body")).not_to_contain_text("已完成")
            assert AXE.is_file(), "axe-core is missing"
            page.add_script_tag(path=str(AXE))
            violations = page.evaluate(
                """() => axe.run(document).then((result) =>
                  result.violations
                    .filter((item) => item.impact === "serious" || item.impact === "critical")
                    .flatMap((item) => item.nodes.map((node) => item.id + " " + node.target.join(" ")))
                )"""
            )
            assert violations == [], violations
            browser.close()
    finally:
        stack.close()
