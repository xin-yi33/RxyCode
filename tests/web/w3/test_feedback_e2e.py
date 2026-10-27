"""Feedback UI browser contracts — built on the shared W3 harness.

Covers: settings feedback tab render (1440/390, no horizontal overflow),
image add/remove, successful submit toast, CAPTCHA_REQUIRED escalation
surface, RunCard「反馈此回答」prefill, and the auto-prompt card for a
live-failed run (show/dismiss/respond) — plus the no-show cases (historical
terminal run, successful run, reduced-motion).
"""

from __future__ import annotations

import hashlib
import io
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    session_row,
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
        # runs 分页 stub：首页 next_cursor，before= 请求回 older_runs。
        self.runs_next_cursor: str | None = None
        self.older_runs: list[dict] = []
        # True → 下一次带 captcha 的提交回 503 FEEDBACK_BUSY。
        self.busy_once = False
        # True → GET /sessions/{id} 回 500 —— 驱动 isError 态切换。
        self.session_fail = False
        # 「我的反馈」分页 stub：按 20/页 + 数字游标切片。
        self.mine_items: list[dict] = []

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
            if self.busy_once and body.get("captcha"):
                self.busy_once = False
                self._json(route, 503, {"code": "FEEDBACK_BUSY"})
                return
            if self.captcha_required and not body.get("captcha"):
                self._json(route, 400, {"code": "CAPTCHA_REQUIRED"})
                return
            self._json(route, 201, {"id": "fb-item-1", "batch_seq": 3, "state": "new"})
            return
        if path == "/api/v1/feedback/mine":
            start = int(
                parse_qs(urlparse(request.url).query).get("cursor", ["0"])[0]
            )
            page_items = self.mine_items[start : start + 20]
            nxt = start + 20
            self._json(
                route,
                200,
                {
                    "items": page_items,
                    "next_cursor": str(nxt) if nxt < len(self.mine_items) else None,
                },
            )
            return
        if path == "/api/v1/auth/altcha" and method == "GET":
            # 可真解的小挑战：maxnumber=64，number=42 —— widget 秒解；
            # 每次调用新 salt → 重挂 widget 拿到的是不同的挑战。
            salt = secrets.token_hex(12)
            challenge = hashlib.sha256(f"{salt}42".encode()).hexdigest()
            self._json(
                route,
                200,
                {
                    "algorithm": "SHA-256",
                    "challenge": challenge,
                    "maxnumber": 64,
                    "salt": salt,
                    "signature": secrets.token_hex(32),
                },
            )
            return
        if path == "/api/v1/me":
            me = json.loads(json.dumps(ME))
            me["feedback_admin"] = self.feedback_admin
            self._json(route, 200, me)
            return
        if path.startswith("/api/v1/admin/feedback"):
            self._json(route, 200, {"batches": [], "items": [], "groups": {}})
            return
        if (
            self.session_fail
            and path == f"/api/v1/sessions/{self.session['id']}"
            and method == "GET"
        ):
            self._json(route, 500, {"detail": "boom"})
            return
        if path == f"/api/v1/sessions/{self.session['id']}/runs" and method == "GET":
            before = parse_qs(urlparse(request.url).query).get("before", [None])[0]
            if before:
                self._json(
                    route, 200, {"runs": list(self.older_runs), "next_cursor": None}
                )
            else:
                self._json(
                    route,
                    200,
                    {"runs": list(self.runs), "next_cursor": self.runs_next_cursor},
                )
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
        assert "rxy.feedback.autoPrompt=0" in page.evaluate("document.cookie")
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
        asked = page.evaluate("document.cookie")
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


# ---- review-round-2 additions ----------------------------------------------


def test_auto_prompt_probe_race_no_false_empty(browser, production_origin):
    """探测先于事件返回终态：/runs/{id} 先回 succeeded、事件回放延迟 1s
    才到（含真实 final 文本）—— 不得在空时间线窗口误弹空回答卡片。"""
    context = context_for(browser, "desktop-1440")

    class ProbeRaceApi(FeedbackApi):
        def handle(self, route):
            path = urlparse(route.request.url).path
            if path == "/api/v1/runs/run-probe":
                run = dict(self.runs[0])
                run["status"] = "succeeded"
                self._json(route, 200, run)
                return
            if path.endswith("/events") and "/api/v1/runs/" in path:
                time.sleep(1.0)
            super().handle(route)

    events = chat_events(message="帮我写排序", tool_rows=0, final="已给出排序实现")
    events.append(
        {
            "seq": events[-1]["seq"] + 1,
            "type": "run.status",
            "payload": {"status": "succeeded"},
        }
    )
    api = ProbeRaceApi(
        runs=[run_summary("run-probe", "running", "帮我写排序")], events=events
    )
    page = _session_page(context, production_origin, api, "/app/s/session-chat-1")
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        time.sleep(3.5)  # 探测窗口 + 回放 + 1500ms 显示延迟全部覆盖
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
    finally:
        context.close()


def test_auto_prompt_card_cleared_on_session_switch(browser, production_origin):
    """A 会话卡片可见时切到 B 会话 —— 卡片必须消失（hook 按 sessionId 重置）。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(
        sessions=[
            session_row("session-chat-1", title="会话A"),
            session_row("session-b", title="会话B"),
        ],
    )
    page = _live_session(
        context, production_origin, api, run_summary("run-live-1", "running", "帮我写排序")
    )
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        push_sse(page, {"seq": 2, "type": "run.status", "payload": {"status": "failed"}})
        page.wait_for_selector('[data-testid="feedback-auto-prompt"]', timeout=10_000)
        page.locator('a[href$="/app/s/session-b"]').first.click()
        page.wait_for_selector(
            '[data-testid="feedback-auto-prompt"]', state="detached", timeout=10_000
        )
    finally:
        context.close()


def test_feedback_survives_disabled_storage(browser, production_origin):
    """存储被禁（document.cookie 读写抛 SecurityError）时：设置反馈页与
    会话页都不崩，自动询问退化为内存态。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(
        runs=[run_summary("run-old-1", "failed", "旧任务")],
        events=chat_events(message="旧任务", tool_rows=0),
    )
    context.route("**/api/v1/**", api.handle)
    page = context.new_page()
    install_event_stream_mock(page)
    page.add_init_script(
        "try{Object.defineProperty(document,'cookie',{"
        " get(){throw new DOMException('denied','SecurityError')},"
        " set(){throw new DOMException('denied','SecurityError')}})}catch(e){}"
    )
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        page.goto(f"{production_origin}/settings/feedback")
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)
        page.goto(f"{production_origin}/app/s/session-chat-1")
        page.wait_for_selector('[data-testid="run-feedback-btn"]', timeout=15_000)
        time.sleep(2.5)
        assert not errors, f"pageerrors: {errors}"
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
    finally:
        context.close()


def test_paged_history_run_is_not_a_followup(browser, production_origin):
    """候选窗内点「加载更早」插入与 live prompt 同文的历史抱怨 run ——
    不得被当后续消息（若误记：repeated_prompt+2、negative_followup+2=4≥3
    → succeeded 的 0 分候选也会被误弹）。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(
        runs=[run_summary("run-live-1", "running", "刚才的回答还是不行")],
        events=chat_events(message="刚才的回答还是不行", tool_rows=0, final="好的，重试一下"),
    )
    api.runs_next_cursor = "cursor-older-1"
    api.older_runs = [
        run_summary(
            "run-old-1",
            "failed",
            "刚才的回答还是不行",
            created_at="2020-01-01T00:00:00Z",
        )
    ]
    page = _session_page(
        context, production_origin, api, "/app/s/session-chat-1"
    )
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        wait_sse_open(page)
        # live run 成功且非空 final → 基础分 0，不应弹。
        push_sse(
            page,
            {"seq": 2, "type": "assistant.final", "payload": {"text": "好的，重试一下"}},
        )
        push_sse(
            page, {"seq": 3, "type": "run.status", "payload": {"status": "succeeded"}}
        )
        # 候选窗内点「加载更早」→ 历史 run 进列表（断言挂在 run 容器 id 上）。
        page.click("text=加载更早的任务")
        page.wait_for_selector("#run-run-old-1", timeout=5_000)
        time.sleep(3.5)
        assert not dom_visible(page, '[data-testid="feedback-auto-prompt"]')
    finally:
        context.close()


def test_captcha_refreshed_after_busy_submit(browser, production_origin):
    """带 captcha 的提交 503 → 挑战一次性，widget 必须重挂回未验证态，
    重新验证出新 payload 后提交成功（两次 captcha payload 不同）。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(captcha_required=True)
    api.busy_once = True
    # statechange 事件冒泡 —— document 级监听器必须在导航前注入
    #（altcha-widget 内部 state 是闭包 shadow DOM，DOM 上不可读）。
    context.route("**/api/v1/**", api.handle)
    page = context.new_page()
    install_event_stream_mock(page)
    page.add_init_script(
        "window.__altchaStates=[];"
        "document.addEventListener('statechange',"
        "e=>window.__altchaStates.push(e.detail?e.detail.state:'?'),true);"
    )
    page.goto(f"{production_origin}/settings/feedback")
    verified = "window.__altchaStates.filter(s=>s==='verified').length"
    try:
        page.wait_for_selector('[data-testid="feedback-form"]', timeout=15_000)
        page.locator("#feedback-title").fill("需要验证码的提交")
        page.locator("#feedback-body").fill("提交时服务正忙，需要重新验证。")
        page.locator('[data-testid="feedback-submit"]').click()
        page.wait_for_selector('[data-testid="feedback-captcha"]', timeout=10_000)
        page.wait_for_function(f"() => {verified} >= 1", timeout=30_000)
        page.locator('[data-testid="feedback-submit"]').click()
        # 503 后 widget 重挂：再次从 verifying → verified（第二次 verified）。
        page.wait_for_function(f"() => {verified} >= 2", timeout=30_000)
        page.wait_for_selector('[data-testid="feedback-captcha"]', timeout=10_000)
        page.locator('[data-testid="feedback-submit"]').click()
        page.wait_for_selector("text=FB-0003", timeout=10_000)
        posts = api.feedback_posts
        assert len(posts) == 3
        assert posts[0].get("captcha") is None
        assert posts[1].get("captcha") and posts[2].get("captcha")
        assert posts[1]["captcha"] != posts[2]["captcha"]  # 新挑战 → 新 payload
    finally:
        context.close()


def test_session_error_state_keeps_hooks_intact(browser, production_origin):
    """session 查询从 200 转 500 → 显示连接错误+重试 UI；hooks 必须在
    条件 return 之前全部就位（否则 React 抛 Rendered fewer hooks）。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi(
        sessions=[
            session_row("session-chat-1", title="会话A"),
            session_row("session-b", title="会话B"),
        ],
        runs=[run_summary("run-live-1", "succeeded", "帮我写排序")],
        events=chat_events(message="帮我写排序", tool_rows=0, final="完成"),
    )
    page = _session_page(context, production_origin, api, "/app/s/session-chat-1")
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        page.wait_for_selector('[data-testid="chat-scroll"]', timeout=15_000)
        api.session_fail = True
        # 离开再回来 → queryKey 重挂载且 staleTime=0 → refetch → 500 → isError。
        page.locator('a[href$="/app/s/session-b"]').first.click()
        page.locator('a[href$="/app/s/session-chat-1"]').first.click()
        page.wait_for_selector("text=无法连接服务器", timeout=10_000)
        assert page.locator("text=重试").count() >= 1
        assert not any(
            "Rendered fewer hooks" in e or "Rendered more hooks" in e
            for e in errors
        ), f"hook-order crash: {errors}"
    finally:
        context.close()


def _mine_item(i: int) -> dict:
    return {
        "id": f"fb-mine-{i}",
        "batch_seq": 1,
        "kind": "bug",
        "module": "chat",
        "state": "new",
        "title": f"反馈条目 {i}",
        "created_at": "2026-10-27T00:00:00Z",
        "images": [],
    }


def test_my_feedback_loads_more(browser, production_origin):
    """25 条历史 → 首屏 20 + 「加载更多」→ 25 条无重复、按钮消失。"""
    context = context_for(browser, "desktop-1440")
    api = FeedbackApi()
    api.mine_items = [_mine_item(i) for i in range(25)]
    page = _session_page(context, production_origin, api, "/settings/feedback")
    try:
        page.wait_for_selector('[data-testid="feedback-mine"]', timeout=15_000)
        page.wait_for_selector(
            '[data-testid="feedback-mine"] article', timeout=10_000
        )
        assert (
            page.locator('[data-testid="feedback-mine"] article').count() == 20
        )
        page.locator('[data-testid="feedback-mine-more"]').click()
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'[data-testid=feedback-mine] article').length === 25",
            timeout=10_000,
        )
        assert page.locator('[data-testid="feedback-mine-more"]').count() == 0
        titles = page.locator(
            '[data-testid="feedback-mine"] article header strong'
        ).all_text_contents()
        assert len(set(titles)) == 25, f"duplicates: {titles}"
    finally:
        context.close()
