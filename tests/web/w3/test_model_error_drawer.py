"""Model-unavailable failed run + mobile Settings drawer browser contracts.

Covers (v1.4.6 fix):
- A run whose events carry ``run.error{code: MODEL_UNAVAILABLE, raw}`` plus a
  terminal ``run.status: failed`` renders the 「失败」 chip (never 「已完成」),
  the readable Chinese error card, a collapsed 详情 block holding the raw
  provider text, and a 「切换模型」 action that opens the real Composer
  ModelPicker dialog.
- On a 390x844 viewport the Settings section switcher is a slide-in drawer
  (role=dialog, aria-modal, focus trap, backdrop + Esc close, section pick
  navigates and closes) — the old <select> is gone. Desktop keeps the sidebar.

Screenshots land under RXY_SHOT_DIR (default ~/.rxycode/output/fix-model-mobile).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _chat_case import (  # noqa: E402
    ChatApi,
    browser,
    context_for,
    dom_visible,
    install_event_stream_mock,
    no_horizontal_overflow,
    production_origin,
    run_summary,
    session_row,
)

_ = (browser, production_origin)  # 让 pytest 发现导入的 fixture

SHOT_DIR = Path(
    os.environ.get(
        "RXY_SHOT_DIR",
        r"C:\Users\Administrator\.rxycode\output\fix-model-mobile",
    )
)

MODEL_GONE_DETAIL = (
    "模型 deepseek-flash 已被服务商（OpenCode Go）停用，"
    "请在模型选择中换一个模型后重试。"
)
MODEL_GONE_RAW = (
    "APIStatusError: Error code: 410 - {'type': 'error', 'error': "
    "{'type': 'ModelDeprecated', 'message': 'Model deepseek-flash is deprecated'}}"
)


def _session_page(context, origin, api: ChatApi, path: str):
    context.route("**/api/v1/**", api.handle)
    page = context.new_page()
    install_event_stream_mock(page)
    page.goto(f"{origin}{path}")
    return page


def _model_gone_api() -> ChatApi:
    api = ChatApi(
        session=session_row("session-chat-1", "模型下线复现"),
        runs=[
            run_summary(
                "run-chat-1",
                "failed",
                "帮我写排序",
            )
        ],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "帮我写排序"}},
            {
                "seq": 2,
                "type": "run.error",
                "payload": {
                    "detail": MODEL_GONE_DETAIL,
                    "code": "MODEL_UNAVAILABLE",
                    "raw": MODEL_GONE_RAW,
                    "model": "deepseek-flash",
                    "provider": "OpenCode Go",
                },
            },
            {"seq": 3, "type": "run.status", "payload": {"status": "failed"}},
        ],
    )
    return api


# ---- 失败 run：MODEL_UNAVAILABLE --------------------------------------------


def test_failed_run_shows_failed_chip_error_card_and_switch_model(
    browser, production_origin
):
    context = context_for(browser, "desktop-1440")
    page = _session_page(context, production_origin, _model_gone_api(), "/app/s/session-chat-1")
    try:
        page.wait_for_selector('[data-run-status="failed"]', timeout=15_000)
        assert page.locator('[data-run-status="failed"]').inner_text() == "失败"
        assert not dom_visible(page, '[data-run-status="succeeded"]')

        card = page.locator("[data-run-error]")
        card.wait_for(timeout=10_000)
        assert MODEL_GONE_DETAIL in card.inner_text()
        # 原始报文折叠进 详情，不内联展开。
        details = card.locator("details")
        assert details.count() == 1
        assert details.get_attribute("open") is None
        raw_text = details.locator("pre").text_content() or ""
        assert "410" in raw_text
        assert "ModelDeprecated" in raw_text

        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / "failed-run-model-unavailable.png"))

        # 「切换模型」→ 打开既有 ModelPicker（登录态直接展开）。
        card.get_by_role("button", name="切换模型").click()
        page.wait_for_selector('[role="dialog"]', timeout=10_000)
        assert dom_visible(page, '[role="listbox"]')
        page.screenshot(path=str(SHOT_DIR / "model-picker-open.png"))
    finally:
        context.close()


def test_failed_run_without_code_has_no_switch_model(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    api = ChatApi(
        runs=[run_summary("run-chat-1", "failed", "普通失败")],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "普通失败"}},
            {
                "seq": 2,
                "type": "run.error",
                "payload": {"detail": "构建未完成，请重试。"},
            },
            {"seq": 3, "type": "run.status", "payload": {"status": "failed"}},
        ],
    )
    page = _session_page(context, production_origin, api, "/app/s/session-chat-1")
    try:
        page.wait_for_selector("[data-run-error]", timeout=15_000)
        assert page.get_by_role("button", name="切换模型").count() == 0
    finally:
        context.close()


# ---- 移动端 Settings 抽屉 ----------------------------------------------------


def test_mobile_settings_drawer_opens_navigates_and_closes(
    browser, production_origin
):
    context = context_for(browser, "mobile-375")
    page = _session_page(
        context, production_origin, ChatApi(), "/settings/general-settings"
    )
    try:
        # <select> 已移除 —— 触发器显示当前分区名。
        trigger = page.locator('[data-testid="settings-nav-trigger"]')
        trigger.wait_for(timeout=15_000)
        # 分区切换器不再是 <select>（分区面板内部的表单控件不算）。
        assert page.locator("aside select").count() == 0
        assert "通用" in trigger.inner_text()
        trigger.click()

        drawer = page.locator('[data-testid="settings-nav-drawer"]')
        drawer.wait_for(timeout=5_000)
        assert drawer.get_attribute("aria-modal") == "true"
        # 分区项与桌面侧栏同序同标（含 通用/主题/反馈）。
        labels = [
            drawer.locator("nav a").nth(i).inner_text() for i in range(7)
        ]
        assert labels[-1].strip() == "反馈"
        assert len(labels) == 7
        # 焦点被圈禁进抽屉。
        assert page.evaluate(
            "document.querySelector('[data-testid=settings-nav-drawer]')"
            ".contains(document.activeElement)"
        )

        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / "settings-drawer-open.png"))

        # 选区 → 导航 + 抽屉关闭。
        drawer.locator("nav a").nth(1).click()
        page.wait_for_url("**/settings/appearance", timeout=10_000)
        assert page.locator('[data-testid="settings-nav-drawer"]').count() == 0
        no_horizontal_overflow(page)
    finally:
        context.close()


def test_mobile_settings_drawer_esc_and_backdrop_close(browser, production_origin):
    context = context_for(browser, "mobile-375")
    page = _session_page(context, production_origin, ChatApi(), "/settings/general-settings")
    try:
        trigger = page.locator('[data-testid="settings-nav-trigger"]')
        trigger.wait_for(timeout=15_000)
        trigger.click()
        page.wait_for_selector('[data-testid="settings-nav-drawer"]', timeout=5_000)
        page.keyboard.press("Escape")
        page.wait_for_selector(
            '[data-testid="settings-nav-drawer"]', state="detached", timeout=5_000
        )
        # 关闭后焦点回到触发按钮。
        assert page.evaluate(
            "document.activeElement === "
            "document.querySelector('[data-testid=settings-nav-trigger]')"
        )

        trigger.click()
        page.wait_for_selector('[data-testid="settings-nav-drawer"]', timeout=5_000)
        # 遮罩点击关闭。
        page.mouse.click(360, 400)
        page.wait_for_selector(
            '[data-testid="settings-nav-drawer"]', state="detached", timeout=5_000
        )
    finally:
        context.close()


def test_mobile_drawer_closes_when_viewport_crosses_desktop(
    browser, production_origin
):
    """Codex P2：抽屉开着时视口越过 md 断点（横屏），必须逻辑关闭 —
    否则焦点圈禁与背景滚动锁还作用在桌面页面上。"""
    context = context_for(browser, "mobile-375")
    page = _session_page(
        context, production_origin, ChatApi(), "/settings/general-settings"
    )
    try:
        page.locator('[data-testid="settings-nav-trigger"]').click()
        page.wait_for_selector('[data-testid="settings-nav-drawer"]', timeout=5_000)
        assert page.evaluate("document.body.style.overflow") == "hidden"
        page.set_viewport_size({"width": 900, "height": 844})
        page.wait_for_selector(
            '[data-testid="settings-nav-drawer"]', state="detached", timeout=5_000
        )
        assert page.evaluate("document.body.style.overflow") != "hidden"
        # 桌面侧栏恢复可见、键盘 Tab 不再被圈禁。
        assert dom_visible(page, "aside nav")
    finally:
        context.close()


def test_desktop_settings_sidebar_unchanged_no_trigger(browser, production_origin):
    context = context_for(browser, "desktop-1440")
    page = _session_page(
        context, production_origin, ChatApi(), "/settings/general-settings"
    )
    try:
        page.wait_for_selector("aside nav", timeout=15_000)
        # 桌面：侧栏导航可见、抽屉触发器（md:hidden）不可见、无 <select>。
        assert dom_visible(page, "aside nav")
        assert page.locator("aside select").count() == 0
        assert not dom_visible(page, '[data-testid="settings-nav-trigger"]')
        assert page.locator('[role="dialog"][aria-modal="true"]').count() == 0
    finally:
        context.close()
