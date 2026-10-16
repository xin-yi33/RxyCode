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
    """Choosing Local on 127.0.0.1 creates a server session without GitHub."""
    stack = _mod._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            seen: list[str] = []
            page.on("request", lambda item: seen.append(item.url))
            _mod._login(page, stack.origin)
            expect(page.get_by_text("不需要 GitHub")).to_be_visible()
            page.get_by_label("仓库名称").fill("local-repo")
            page.get_by_role("button", name="导入").click()
            with page.expect_response(
                lambda item: "/sessions" in item.url and item.request.method == "POST"
            ) as created:
                page.get_by_role("button", name="创建会话").click()
            session_id = created.value.json()["id"]
            expect(page.locator(f"[data-session-id='{session_id}']")).to_be_visible()
            expect(page.get_by_text("等待运行")).to_be_visible()
            assert page.url.startswith("http://127.0.0.1")
            assert all("github.com" not in url for url in seen)
            browser.close()
    finally:
        stack.close()
