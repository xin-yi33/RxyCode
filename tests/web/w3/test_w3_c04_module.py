"""WEB-W3-C04. A stale base_revision is a conflict and does not overwrite the file."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

_UNIT = Path(__file__).with_name("test_w3_c04_unit.py")
_spec = importlib.util.spec_from_file_location("w3c04_unit", _UNIT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_w3_c04_integration() -> None:
    """Submitting the old base_revision after a new edit is rejected."""
    assert _mod.TREE.is_file(), "FileTree.tsx is missing"
    root = _mod._workspace()
    stack = _mod._c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _mod._c02._login(page, stack.origin)
            project_id = _mod._project(root, "local:c04-race")
            page.goto(
                f"{stack.origin}/projects/{project_id}/workspace",
                wait_until="domcontentloaded",
            )
            page.get_by_role("button", name="hello.txt").click()
            expect(page.locator("[data-base-revision]")).to_be_visible(timeout=10000)
            revision = page.locator("[data-base-revision]").get_attribute("data-base-revision")
            assert revision
            (root / "hello.txt").write_text("one\ntwo\nraced\n", encoding="utf-8", newline="\n")
            with page.expect_response(lambda item: item.request.method == "POST") as posted:
                page.get_by_role("button", name="接受").click()
            assert posted.value.status == 409
            assert "CONFLICT" in posted.value.text()
            expect(page.get_by_role("alert")).to_contain_text("刷新")
            disk = (root / "hello.txt").read_text(encoding="utf-8")
            assert disk == "one\ntwo\nraced\n"
            assert revision not in disk
            browser.close()
    finally:
        stack.close()
