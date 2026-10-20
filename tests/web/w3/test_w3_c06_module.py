"""WEB-W3-C06. Approve does not mark the run succeeded before the server says so."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
_UNIT = Path(__file__).with_name("test_w3_c06_unit.py")
_spec = importlib.util.spec_from_file_location("w3c06_unit_mod", _UNIT)
assert _spec is not None and _spec.loader is not None
_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_unit)


def test_w3_c06_integration() -> None:
    """While the approve request is still open, the page does not say succeeded."""
    # The approve button is F4-RunTimeline scope; the in-flight decision now
    # goes through page.evaluate(fetch) so the held-route gate still works.
    from datetime import datetime, timedelta, timezone

    stack = _unit._c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _unit._c02._login(page, stack.origin)
            run_id, approval_id = _unit._seed(
                datetime.now(timezone.utc) + timedelta(minutes=10)
            )
            asks = page.request.get(f"{stack.origin}/api/v1/runs/{run_id}/approvals")
            revision = asks.json()["approvals"][0]["revision"]
            csrf = page.request.get(f"{stack.origin}/api/v1/auth/csrf")
            token = csrf.json()["csrf_token"]
            held: list = []

            def gate(route) -> None:
                if route.request.method == "POST" and "/approvals" in route.request.url:
                    held.append(route)
                    return
                route.continue_()

            page.route("**/*", gate)
            session_id = page.request.get(
                f"{stack.origin}/api/v1/runs/{run_id}"
            ).json()["session_id"]
            page.goto(
                f"{stack.origin}/app/s/{session_id}", wait_until="domcontentloaded"
            )
            expect(
                page.locator("[data-run-status='waiting_approval']").first
            ).to_be_visible(timeout=10000)
            # The request stays held by the route gate — do not return the
            # fetch promise or evaluate waits for it forever.
            page.evaluate(
                """([runId, approvalId, revision, token]) => {
                    fetch(`/api/v1/runs/${runId}/approvals`, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "content-type": "application/json",
                            "x-csrf-token": token,
                        },
                        body: JSON.stringify({
                            approval_id: approvalId,
                            decision: "approve",
                            revision,
                        }),
                    })
                }""",
                [run_id, approval_id, revision, token],
            )
            for _ in range(50):
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "the approve request never reached the server"
            expect(page.locator("body")).not_to_contain_text("succeeded")
            expect(page.locator("body")).not_to_contain_text("已完成")
            held[0].continue_()
            page.wait_for_timeout(500)
            expect(page.locator("body")).not_to_contain_text("succeeded")
            expect(page.locator("body")).not_to_contain_text("已完成")
            browser.close()
    finally:
        stack.close()
