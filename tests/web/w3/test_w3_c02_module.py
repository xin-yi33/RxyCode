"""WEB-W3-C02. Local mode on localhost can open a session without a public account."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_unit_stack", _UNIT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_w3_c02_integration() -> None:
    """Local-secret login reaches /app and submits a task without GitHub."""
    stack = _mod._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            seen: list[str] = []
            page.on("request", lambda item: seen.append(item.url))
            _mod._login(page, stack.origin)
            # W9-F3: the import/创建会话 widgets are gone — POST /tasks is the
            # entrypoint. Dev has no worker so the run stays 排队中.
            with page.expect_response(
                lambda item: item.url.endswith("/api/v1/tasks")
                and item.request.method == "POST"
            ) as created:
                page.get_by_label("消息").fill("c02 module 任务")
                page.get_by_role("button", name="发送").click()
            session_id = created.value.json()["session_id"]
            assert created.value.status == 202
            page.wait_for_url(f"**/app/s/{session_id}", timeout=10000)
            expect(page.get_by_text("排队中").first).to_be_visible(timeout=10000)
            expect(page.locator("aside").get_by_text("c02 module 任务")).to_be_visible(
                timeout=10000
            )
            assert page.url.startswith("http://127.0.0.1")
            assert all("github.com" not in url for url in seen)
            browser.close()
    finally:
        stack.close()
