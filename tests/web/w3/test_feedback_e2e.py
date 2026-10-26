"""Feedback UI browser contracts — built on the shared W3 harness.

Covers: settings feedback tab render (1440/390, no horizontal overflow),
image add/remove, successful submit toast, CAPTCHA_REQUIRED escalation
surface, RunCard「反馈此回答」prefill, and the auto-prompt card for a
live-failed run (show/dismiss/respond) — plus the no-show cases (historical
terminal run, successful run, reduced-motion).
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import BrowserContext, Page

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _chat_case import (  # noqa: E402
    ChatApi,
    ME,
    apply_reduced_motion,
    browser,
    chat_events,
    context_for,
    dom_visible,
    install_event_stream_mock,
    no_horizontal_overflow,
    production_origin,
    push_sse,
    run_summary,
    wait_sse_open,
)

_ = (browser, production_origin)  # 让 pytest 发现导入的 fixture


class FeedbackApi(ChatApi):
    """ChatApi + the feedback surface (records submits, serves admin stubs)."""

    def __init__(
        self,
        *,
        captcha_required: bool = False,
        feedback_admin: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.captcha_required = captcha_required
        self.feedback_admin = feedback_admin
        self.feedback_posts: list[dict] = []
        self.image_posts = 0

    def handle(self, route) -> None:
        request = route.request
        method = request.method.upper()
        path = urlparse(request.url).path

        if path == "/api/v1/feedback/images" and method == "POST":
            self.image_posts += 1
            self._json(
                route,
                201,
                {
                    "image_id": f"img-{self.image_posts}",
                    "width": 8,
                    "height": 8,
                    "size_bytes": 123,
                    "content_type": "image/png",
                },
            )
            return
        if path == "/api/v1/feedback" and method == "POST":
            try:
                body = json.loads(request.post_data or "{}")
            except ValueError:
                body = {}
            self.feedback_posts.append(body)
            if self.captcha_required and not body.get("captcha"):
                self._json(route, 400, {"code": "CAPTCHA_REQUIRED"})
                return
            self._json(route, 201, {"id": "fb-item-1", "batch_seq": 3, "state": "new"})
            return
        if path == "/api/v1/feedback/mine":
            self._json(route, 200, {"items": [], "next_cursor": None})
            return
        if path == "/api/v1/me":
            me = json.loads(json.dumps(ME))
            me["feedback_admin"] = self.feedback_admin
            self._json(route, 200, me)
            return
        if path.startswith("/api/v1/admin/feedback"):
            self._json(route, 200, {"batches": [], "items": [], "groups": {}})
            return
        super().handle(route)


def _png_file() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _session_page(
    context: BrowserContext, origin: str, api: ChatApi, path: str
) -> Page:
    """Route stubs go on the context BEFORE first navigation, and the SSE
    mock's init script must precede app boot — so navigate manually here
    rather than through open_page."""
    context.route("**/api/v1/**", api.handle)
    page = context.new_page()
    install_event_stream_mock(page)
    page.goto(f"{origin}{path}")
    return page


# ---- settings tab -----------------------------------------------------------


def test_settings_feedback_renders_desktop(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    page = _session_page(context, production_origin, FeedbackApi(), "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="settings-feedback"]', timeout=15_000)
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=10_000)
        assert page.locator("#feedback-title").count() == 1
        assert page.locator("#feedback-body").count() == 1
        assert page.locator('[data-testid="feedback-kind"]').count() == 1
        assert page.locator('[data-testid="feedback-autoprompt-toggle"]').count() == 1
        no_horizontal_overflow(page)
    finally:
        context.close()


def test_settings_feedback_mobile_no_overflow(browser, production_origin):
    context = context_for(browser, "mobile-375")
    page = _session_page(context, production_origin, FeedbackApi(), "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)
        no_horizontal_overflow(page)
    finally:
        context.close()


def test_settings_feedback_dark(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    context.add_cookies(
        [{"name": "rxy_theme", "value": "dark", "url": production_origin}]
    )
    page = _session_page(context, production_origin, FeedbackApi(), "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)
        assert page.locator('[data-testid="feedback-form"]').is_visible()
        no_horizontal_overflow(page)
    finally:
        context.close()


# ---- submit + images --------------------------------------------------------


def test_feedback_submit_success_and_image(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    page = _session_page(context, production_origin, api, "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)

        # 图片：选择 → 缩略图 → 移除 → 再添加
        file_input = page.locator('input[type="file"][accept*="image"]')
        file_input.set_input_files(
            {"name": "shot.png", "mimeType": "image/png", "buffer": _png_file()}
        )
        page.wait_for_selector(".feedback-image-card", timeout=10_000)
        assert api.image_posts == 1
        page.locator('.feedback-image-card button[aria-label="移除图片"]').first.click()
        page.wait_for_selector(".feedback-image-card", state="detached", timeout=5_000)
        file_input.set_input_files(
            {"name": "shot.png", "mimeType": "image/png", "buffer": _png_file()}
        )
        page.wait_for_selector(".feedback-image-card", timeout=10_000)

        page.locator("#feedback-title").fill("会话页卡死")
        page.locator("#feedback-body").fill("打开会话后整个页面没有响应，需要强刷。")
        page.locator('[data-testid="feedback-submit"]').click()

        # toast「已提交（FB-0003）」+ 表单清空
        page.wait_for_selector("text=FB-0003", timeout=10_000)
        assert api.feedback_posts, "feedback POST not recorded"
        body = api.feedback_posts[-1]
        assert body["kind"] == "bug"
        assert body["module"] == "chat"
        assert body["title"] == "会话页卡死"
        assert body["image_ids"] == ["img-2"]
        assert body["page_path"] == "/settings/feedback"
        assert body["source"] == "manual"
        assert page.locator("#feedback-title").input_value() == ""
    finally:
        context.close()


def test_feedback_captcha_escalation_shows_widget(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(captcha_required=True)
    page = _session_page(context, production_origin, api, "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)
        page.locator("#feedback-title").fill("需要验证码的提交")
        page.locator("#feedback-body").fill("第四次提交应该触发验证码升级。")
        page.locator('[data-testid="feedback-submit"]').click()
        page.wait_for_selector('[data-testid="feedback-captcha"]', timeout=10_000)
        assert api.feedback_posts[-1].get("captcha") is None
    finally:
        context.close()


def test_feedback_toggle_persists(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    page = _session_page(context, production_origin, FeedbackApi(), "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-autoprompt-toggle"]', timeout=15_000)
        toggle = page.locator('[data-testid="feedback-autoprompt-toggle"]')
        assert toggle.is_checked()
        toggle.click()
        assert page.evaluate("localStorage.getItem('rxy.feedback.autoPrompt')") == "0"
    finally:
        context.close()


# ---- RunCard 反馈按钮 ---------------------------------------------------------


def test_runcard_feedback_button_prefills(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(
        runs=[run_summary("run-chat-1", "failed", "帮我写排序")],
        events=chat_events(message="帮我写排序", tool_rows=0, final="bad"),
    )
    page = _session_page(context, production_origin, api, "/app/s/session-chat-1")
    try:
        page.wait_for_selector('[data-testid="run-feedback-btn"]', timeout=15_000)
        page.locator('[data-testid="run-feedback-btn"]').click()
        page.wait_for_selector("dialog[open] [data-testid='feedback-form']", timeout=10_000)
        # 预填：module=run_output
        assert (
            page.locator("dialog[open] select#feedback-module").input_value()
            == "run_output"
        )
        page.locator("dialog[open] #feedback-title").fill("回答内容不对")
        page.locator("dialog[open] #feedback-body").fill("这个回答没有解决我的问题。")
        page.locator('dialog[open] [data-testid="feedback-submit"]').click()
        page.wait_for_selector("text=FB-0003", timeout=10_000)
        body = api.feedback_posts[-1]
        assert body["run_id"] == "run-chat-1"
        assert body["session_id"] == "session-chat-1"
        assert body["module"] == "run_output"
        assert body["kind"] == "content_quality"
        assert body["source"] == "manual"
    finally:
        context.close()


# ---- 自动询问卡片 ------------------------------------------------------------


def _live_session(
    context: BrowserContext, origin: str, api: FeedbackApi, run: dict
) -> Page:
    api.runs = [run]
    api.events = chat_events(message=run["message"], tool_rows=0)
    page = _session_page(context, origin, api, "/app/s/session-chat-1")
    wait_sse_open(page)
    return page


def test_auto_prompt_shows_on_live_failure(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    page = _live_session(
        context, production_origin, api, run_summary("run-live-1", "running", "帮我写排序")
    )
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
        push_sse(page, {"seq": 2, "type": "run.status", "payload": {"status": "failed"}})
        page.wait_for_selector('[data-testid="feedback-auto-prompt"]', timeout=10_000)
        asked = page.evaluate("localStorage.getItem('rxy.feedback.askedRuns')")
        assert "run-live-1" in (asked or "")
        page.locator('[data-testid="feedback-auto-dismiss"]').click()
        page.wait_for_selector(
            '[data-testid="feedback-auto-prompt"]', state="detached", timeout=5_000
        )
    finally:
        context.close()


def test_auto_prompt_not_for_history(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    # 历史 failed run —— 回放不算“实时观察”；终态 run 也不会开 SSE。
    api = FeedbackApi(
        runs=[run_summary("run-old-1", "failed", "旧任务")],
        events=chat_events(message="旧任务", tool_rows=0),
    )
    page = _session_page(context, production_origin, api, "/app/s/session-chat-1")
    try:
        page.wait_for_selector('[data-testid="run-feedback-btn"]', timeout=15_000)
        time.sleep(2.5)  # 超过 1500ms 延迟窗
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
    finally:
        context.close()


def test_auto_prompt_not_for_success(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    page = _live_session(
        context, production_origin, api, run_summary("run-ok-1", "running", "正常任务")
    )
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        push_sse(page, {"seq": 2, "type": "assistant.final", "payload": {"text": "完成"}})
        push_sse(
            page, {"seq": 3, "type": "run.status", "payload": {"status": "succeeded"}}
        )
        time.sleep(2.5)
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
    finally:
        context.close()


def test_auto_prompt_respond_opens_prefilled_form(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    page = _live_session(
        context, production_origin, api, run_summary("run-live-1", "running", "帮我写排序")
    )
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        push_sse(page, {"seq": 2, "type": "run.status", "payload": {"status": "failed"}})
        page.wait_for_selector('[data-testid="feedback-auto-prompt"]', timeout=10_000)
        page.locator('[data-testid="feedback-auto-respond"]').click()
        page.wait_for_selector(
            "dialog[open] [data-testid='feedback-form']", timeout=10_000
        )
        page.locator("dialog[open] #feedback-title").fill("运行失败了")
        page.locator("dialog[open] #feedback-body").fill("任务直接失败，没有任何输出。")
        page.locator('dialog[open] [data-testid="feedback-submit"]').click()
        page.wait_for_selector("text=FB-0003", timeout=10_000)
        body = api.feedback_posts[-1]
        assert body["source"] == "auto_prompt"
        assert body["run_id"] == "run-live-1"
        assert "run_failed" in (body.get("trigger_reasons") or [])
    finally:
        context.close()


def test_auto_prompt_reduced_motion(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    page = _live_session(
        context, production_origin, api, run_summary("run-live-1", "running", "帮我写排序")
    )
    try:
        apply_reduced_motion(page, "reduce")
        push_sse(page, {"seq": 2, "type": "run.status", "payload": {"status": "failed"}})
        page.wait_for_selector('[data-testid="feedback-auto-prompt"]', timeout=10_000)
        animation = page.evaluate(
            "getComputedStyle(document.querySelector('[data-testid=feedback-auto-prompt]')).animationName"
        )
        assert animation in ("none", "")
    finally:
        context.close()
