"""Chat-polish composite end-to-end chains (W01 / W02 / W03) on
deterministic API + SSE stubs.

A chain is one user-visible story that crosses the composer, timeline and
preview surfaces. Each step probes the contract marker of the surface it needs;
when a surface is not implemented yet the chain SKIPS with the exact reason and
never reports a pass. Live-cloud-only parts are separate tests that skip
honestly (NOT RUN) - no test in this module can pass without the real DOM.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from _chat_case import (
    CLASS_COLLAPSE,
    TESTID_COMPOSER,
    TESTID_FILE_NAME,
    TESTID_JUMP,
    TESTID_PREVIEW_SPLIT,
    TESTID_SCROLL,
    ChatApi,
    chat_events,
    color_to_rgb,
    composer_box,
    context_for,
    css_var,
    distance_to_bottom,
    install_api,
    install_event_stream_mock,
    is_scrollable,
    new_context,
    no_horizontal_overflow,
    norm_ws,
    probe,
    probe_testid,
    push_sse,
    run_summary,
    scroll_metrics,
    scroll_to_distance,
    wait_sse_open,
)

# Re-export the shared fixtures so pytest registers them for this module.
from _chat_case import (  # noqa: F401  (shared Playwright fixtures)
    browser,
    dev_origin,
    engine_browser,
    engine_name,
    production_origin,
)

MESSAGE = "把这次改动的要点整理成三条"
LONG_FILE_NAME = "实验报告-第3章-HDFS分布式文件系统与容错机制详细说明和实现分析.tar.gz"


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _open_session(
    browser: Browser,
    origin: str,
    api: ChatApi,
    *,
    viewport: str = "desktop-1440",
) -> tuple[Any, Page]:
    context = context_for(browser, viewport)
    page = context.new_page()
    install_event_stream_mock(page)
    install_api(page, api)
    page.goto(f"{origin}/app/s/{api.session['id']}")
    composer_box(page).wait_for(timeout=30_000)
    return context, page


def _wait_task_posts(api: ChatApi, page: Page, count: int = 1, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(api.task_posts) >= count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(
        f"expected {count} task POST(s), saw {len(api.task_posts)}: {api.task_posts}"
    )


# ---------------------------------------------------------------------------
# W01: type -> IME-safe Enter -> exactly one task POST -> streamed answer
# ---------------------------------------------------------------------------


def test_w01_send_to_streamed_answer_chain(
    browser: Browser, production_origin: str
) -> None:
    # terminal run so the composer is enabled; the send creates the streamed run
    api = ChatApi(
        runs=[run_summary("run-w01", "succeeded", MESSAGE)],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": MESSAGE}},
        ],
    )
    context, page = _open_session(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="W01 needs the composer shell (task-5 data-testid chat-composer)",
        )
        if page.locator(f'[data-testid="{TESTID_SCROLL}"]').count() == 0:
            pytest.skip(
                "W01 needs the single chat scroll controller (task-6 data-testid chat-scroll)"
            )
        composer = composer_box(page)
        composer.click()
        composer.fill(MESSAGE)
        # IME candidate confirmation must not send
        page.evaluate(
            """() => {
              const el = document.querySelector('textarea[aria-label="消息"]');
              el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
              const event = new KeyboardEvent('keydown', {
                key: 'Enter', bubbles: true, cancelable: true, isComposing: true,
              });
              el.dispatchEvent(event);
              el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
            }"""
        )
        page.wait_for_timeout(200)
        assert api.task_posts == [], "IME confirm Enter must not create the task"

        # compositionend + 500ms grace: wait it out before the real send
        page.wait_for_timeout(560)
        composer.press("Enter")
        _wait_task_posts(api, page, 1)
        assert len(api.task_posts) == 1
        assert norm_ws(api.task_posts[0]["message"]) == MESSAGE
        wait_sse_open(page)

        # the accepted run streams two deltas and a final answer; the active run
        # timeline is the newest run card.
        newest = api.runs[-1]["run_id"]
        for index, text in enumerate(("第一条要点\n", "第二条要点\n")):
            push_sse(
                page,
                {
                    "seq": max((int(event.get("seq", 0)) for event in api.events), default=0) + 1 + index,
                    "type": "assistant.delta",
                    "payload": {"text": text},
                },
            )
            page.wait_for_timeout(200)
        push_sse(
            page,
            {
                "seq": max((int(event.get("seq", 0)) for event in api.events), default=0) + 3,
                "type": "assistant.final",
                "payload": {"text": "三条要点已整理完成。"},
            },
        )
        page.wait_for_timeout(300)
        run_card = page.locator(f'li[id="run-{newest}"]')
        card_text = run_card.inner_text()
        assert "第一条要点" in card_text, card_text
        assert "三条要点已整理完成。" in card_text
        assert page.locator("li[data-answer]").count() >= 1
    finally:
        context.close()


# ---------------------------------------------------------------------------
# W02: history scroll pause -> jump to latest -> collapse expand
# ---------------------------------------------------------------------------


def test_w02_history_scroll_jump_collapse_chain(
    browser: Browser, production_origin: str
) -> None:
    old = run_summary("run-w02-old", "succeeded", "历史任务")
    active = run_summary("run-w02-active", "running", MESSAGE)
    api = ChatApi(
        runs=[old, active],
        events_by_run={
            "run-w02-old": [
                {"seq": 1, "type": "run.created", "payload": {"message": "历史任务"}},
                {"seq": 2, "type": "assistant.final", "payload": {"text": "历史任务完成。"}},
            ],
            "run-w02-active": chat_events(tool_rows=44),
        },
    )
    context, page = _open_session(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_SCROLL,
            feature="W02 needs the single chat scroll controller (task-6 data-testid chat-scroll)",
        )
        jump = page.locator(f'[data-testid="{TESTID_JUMP}"]')
        if jump.count() == 0:
            pytest.skip("W02 needs jump-to-latest (task-6 data-testid chat-jump-to-latest)")
        wait_sse_open(page)
        if not is_scrollable(page):
            pytest.skip("W02 stub timeline is not tall enough to exercise scrolling")

        # upward scroll pauses the follow -> pushes must not move the viewport
        scroll_to_distance(page, 320.0)
        before = scroll_metrics(page)
        push_sse(
            page,
            {
                "seq": max(
                    (int(event.get("seq", 0)) for event in api.events_by_run.get("run-w02-active", [])),
                    default=0,
                ) + 1,
                "type": "assistant.delta",
                "payload": {"text": "滚动暂停期间的新输出"},
            },
        )
        page.wait_for_timeout(250)
        after = scroll_metrics(page)
        assert abs(after["scrollTop"] - before["scrollTop"]) <= 1.5
        assert after["distanceToBottom"] > before["distanceToBottom"]
        assert jump.first.is_visible()

        # jump-to-latest restores the bottom
        jump.first.click()
        page.wait_for_timeout(300)
        assert distance_to_bottom(page) <= 42

        # the shared collapse is expandable in the same session
        if page.locator(f".{CLASS_COLLAPSE}").count() == 0:
            pytest.skip(
                "W02 needs the shared Collapse (task-6 .rxy-collapse absent); "
                "scroll half of the chain passed"
            )
        toggle = page.locator("[aria-expanded]").first
        if toggle.count() == 0:
            pytest.skip("W02 needs a collapse toggle with aria-expanded")
        toggle.click()
        page.wait_for_timeout(350)
        assert toggle.get_attribute("aria-expanded") == "true"
    finally:
        context.close()


# ---------------------------------------------------------------------------
# W03: dark theme -> long filename -> preview split drag/Esc
# ---------------------------------------------------------------------------


def test_w03_theme_filename_preview_chain(
    browser: Browser, production_origin: str
) -> None:
    artifact = {
        "artifact_id": "artifact-w03",
        "filename": LONG_FILE_NAME,
        "relative_path": LONG_FILE_NAME,
        "availability": "available",
        "partial": False,
        "preview_kind": "frontend_static",
        "sha256": "0" * 64,
        "size": 589856,
        "content_type": "application/gzip",
        "expires_at": None,
        "download_url": "/api/v1/artifacts/artifact-w03/download",
    }
    api = ChatApi(
        runs=[run_summary("run-w03", "succeeded", "产物已生成")],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "产物已生成"}},
            {"seq": 2, "type": "assistant.final", "payload": {"text": "产物已生成。"}},
        ],
        artifacts=[artifact],
        session_files=[
            {"path": f"imports/artifact-w03/{LONG_FILE_NAME}", "size": 589856, "mtime": 1700000000}
        ],
    )
    context, page = _open_session(browser, production_origin, api)
    try:
        # W03-1: dark theme applies to the real document, not pure black.
        page.get_by_role("button", name="切换到深色").click()
        page.wait_for_function(
            "() => document.documentElement.dataset.theme === 'dark'", timeout=10_000
        )
        dark_bg = color_to_rgb(css_var(page, "--rxy-bg"))
        assert dark_bg != (0, 0, 0)

        # W03-2: long filename keeps its compound suffix and the accessible name.
        name_rows = page.locator(f'[data-testid="{TESTID_FILE_NAME}"]')
        try:
            name_rows.first.wait_for(timeout=8_000)
        except Exception:
            pytest.skip(
                "W03 needs the shared FileName surface (task-7 data-testid chat-file-name absent)"
            )
        names = name_rows.evaluate_all(
            "nodes => nodes.map(node => ({ title: node.getAttribute('title'), text: node.textContent }))"
        )
        long_rows = [row for row in names if (row["title"] or "") == LONG_FILE_NAME]
        assert long_rows, names
        assert long_rows[0]["text"].rstrip().endswith(".tar.gz"), long_rows[0]["text"]
        no_horizontal_overflow(page)

        # W03-3: the artifact preview opens the real split, drag then Esc restores it.
        preview_button = page.locator('button[aria-label^="预览 "]').first
        try:
            preview_button.wait_for(timeout=8_000)
        except Exception:
            pytest.skip(
                "W03 needs an artifact preview affordance (artifact preview button absent)"
            )
        preview_button.click()
        split = page.locator(f'[data-testid="{TESTID_PREVIEW_SPLIT}"]')
        try:
            split.wait_for(timeout=15_000)
        except Exception:
            pytest.skip("W03 needs the preview split (task-7 chat-preview-split absent)")
        page.wait_for_function(
            """() => document.querySelector('[data-testid="chat-preview-split"]')
              .getAttribute('data-preview-open') === 'true'""",
            timeout=15_000,
        )
        root = split.bounding_box()
        handle = page.locator('[data-testid="chat-preview-handle"]').bounding_box()
        assert root and handle
        y = handle["y"] + handle["height"] / 2
        page.mouse.move(handle["x"] + handle["width"] / 2, y)
        page.mouse.down()
        page.mouse.move(root["x"] + root["width"] * 0.7, y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(250)
        page.keyboard.press("Escape")
        page.wait_for_timeout(350)
        ratio = float(
            page.evaluate(
                """() => {
                  const rootNode = document.querySelector('[data-testid="chat-preview-split"]');
                  const pane = document.querySelector('[data-preview-chat-pane]');
                  return pane.getBoundingClientRect().width / rootNode.getBoundingClientRect().width;
                }"""
            )
        )
        assert abs(ratio - 0.5) <= 0.012, ratio
    finally:
        context.close()

# ---------------------------------------------------------------------------
# honest NOT-RUN markers: live cloud + real devices (never a pass)
# ---------------------------------------------------------------------------


def test_live_cloud_chat_chain_needs_deployed_stack() -> None:
    pytest.skip(
        "NOT RUN: live-cloud chat chain needs the deployed rxycode.xyz stack "
        "(docker compose on the VM) and a real account; this harness is deterministic "
        "stubs only. deploy-qa owns the live acceptance run."
    )


def test_real_device_browser_matrix_not_run() -> None:
    pytest.skip(
        "NOT RUN: vivo built-in browser and real iPhone Safari cannot be driven from "
        "this Windows host; the installed Playwright engines (chromium/firefox/webkit) "
        "do not substitute for those real devices."
    )
