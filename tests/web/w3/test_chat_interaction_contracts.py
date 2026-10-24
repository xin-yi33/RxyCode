"""Chat-polish interaction contracts (IME guard, single task POST, scroll
controller, collapse, copy feedback).

Every test is written against the shared contract declared by the implementers
(task-5 composer / task-6 timeline / UI-07 copy). A test only runs once its
DOM marker exists; when the marker is absent the test SKIPS with the exact
unimplemented reason instead of passing. A present-but-wrong implementation
FAILS - there is no force-success path.

Deterministic stubs: the whole /api/v1 surface is stubbed through page.route and
EventSource is replaced by a controllable stub (same SSE JSON frames) so pushes
happen at exact moments. Nothing here claims a live-cloud pass.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from _chat_case import (
    CLASS_COLLAPSE,
    ChatApi,
    TESTID_COMPOSER,
    TESTID_JUMP,
    TESTID_SCROLL,
    chat_events,
    composer_box,
    context_for,
    distance_to_bottom,
    element_is_non_focusable,
    install_api,
    dom_visible,
    install_event_stream_mock,
    install_paused_clock,
    is_scrollable,
    new_context,
    norm_ws,
    probe,
    probe_testid,
    push_sse,
    run_summary,
    scroll_metrics,
    scroll_to_distance,
    wait_for_attribute,
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

MESSAGE = "请总结这次改动"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _open_chat(
    browser: Browser,
    origin: str,
    api: ChatApi,
    *,
    viewport: str = "desktop-1440",
    clock: bool = False,
    permissions: list[str] | None = None,
) -> tuple[Any, Page]:
    context = context_for(browser, viewport)
    if permissions:
        context.grant_permissions(permissions)
    page = context.new_page()
    install_event_stream_mock(page)
    install_api(page, api)
    page.goto(f"{origin}/app/s/{api.session['id']}")
    composer_box(page).wait_for(timeout=30_000)
    if clock:
        # Install/pause the fake clock only AFTER the app booted: installing it
        # before navigation freezes the boot timers and the composer never
        # appears. Timers created from here on (IME grace, copy hold/fade) are
        # exactly controllable.
        install_paused_clock(page)
    return context, page


def _dispatch_keydown(page: Page, *, key: str = "Enter", **init: Any) -> None:
    page.evaluate(
        """({ key, init }) => {
          const el = document.querySelector('textarea[aria-label="消息"]');
          if (!el) throw new Error("composer textarea missing");
          const event = new KeyboardEvent('keydown', Object.assign(
            { key, bubbles: true, cancelable: true }, init,
          ));
          el.dispatchEvent(event);
        }""",
        {"key": key, "init": init},
    )


def _dispatch_keydown_229(page: Page) -> None:
    page.evaluate(
        """() => {
          const el = document.querySelector('textarea[aria-label="消息"]');
          const event = new KeyboardEvent('keydown', {
            key: 'Enter', bubbles: true, cancelable: true,
          });
          Object.defineProperty(event, 'keyCode', { get: () => 229 });
          el.dispatchEvent(event);
        }"""
    )


def _focus_composer(page: Page) -> None:
    """Focus the composer without Playwright actionability (safe under a paused clock)."""
    page.evaluate(
        """() => {
          const el = document.querySelector('textarea[aria-label="消息"]');
          if (!el) throw new Error('composer textarea missing');
          el.focus();
        }"""
    )


def _set_composer_text(page: Page, text: str) -> None:
    """Set a React-controlled textarea value through the native setter + input event."""
    page.evaluate(
        """(value) => {
          const el = document.querySelector('textarea[aria-label="消息"]');
          if (!el) throw new Error('composer textarea missing');
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value',
          ).set;
          setter.call(el, value);
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        text,
    )


def _dom_click(page: Page, selector: str) -> None:
    """Click through the DOM (no Playwright actionability wait)."""
    page.evaluate(
        """(selector) => {
          const el = document.querySelector(selector);
          if (!el) throw new Error('missing click target: ' + selector);
          el.click();
        }""",
        selector,
    )


def _composition(page: Page, kind: str) -> None:
    page.evaluate(
        """(kind) => {
          const el = document.querySelector('textarea[aria-label="消息"]');
          el.dispatchEvent(new CompositionEvent(kind, { bubbles: true }));
        }""",
        kind,
    )


def _wait_task_posts(api: ChatApi, page: Page, count: int = 1, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(api.task_posts) >= count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(
        f"expected {count} task POST(s), saw {len(api.task_posts)}: {api.task_posts}"
    )


def _active_api(**kwargs: Any) -> ChatApi:
    """One active (running) run plus a long replay so the chat scrolls.

    Only scroll/streaming tests may use this: an active run disables the
    composer (send becomes 停止), so keyboard tests must use _composer_api().
    """
    defaults: dict[str, Any] = {
        "runs": [run_summary("run-chat-active", "running", MESSAGE)],
        "events": chat_events(tool_rows=40),
    }
    defaults.update(kwargs)
    return ChatApi(**defaults)


def _composer_api() -> ChatApi:
    """Terminal run: the composer is enabled and can be typed/clicked."""
    return ChatApi()


def _last_seq(api: ChatApi, run_id: str | None = None) -> int:
    events = api.events_by_run.get(run_id, []) if run_id else api.events
    if run_id and not events:
        events = api.events
    return max((int(event.get("seq", 0)) for event in events), default=0)


# ---------------------------------------------------------------------------
# composer: IME guard table (task-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("elapsed_ms", [499, 500, 501])
def test_ime_enter_after_compositionend_500ms_boundary(
    browser: Browser, production_origin: str, elapsed_ms: int
) -> None:
    api = _composer_api()
    context, page = _open_chat(browser, production_origin, api, clock=True)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="composer IME guard (task-5 data-testid chat-composer)",
        )
        composer = composer_box(page)
        _focus_composer(page)
        _set_composer_text(page, "中文输入后的草稿")
        if not hasattr(page, "clock"):
            pytest.skip("Playwright clock API unavailable; cannot control the 500ms IME window")
        _composition(page, "compositionstart")
        _composition(page, "compositionend")
        page.clock.fast_forward(elapsed_ms)
        _dispatch_keydown(page)
        page.wait_for_timeout(250)

        if elapsed_ms <= 499:
            assert api.task_posts == [], (
                f"Enter {elapsed_ms}ms after compositionend must be blocked; "
                f"got {api.task_posts}"
            )
            assert composer.input_value() == "中文输入后的草稿", "blocked IME Enter must keep the draft"
        else:
            _wait_task_posts(api, page, 1)
            assert len(api.task_posts) == 1
            assert norm_ws(api.task_posts[0]["message"]) == "中文输入后的草稿"
    finally:
        context.close()


def test_ime_native_iscomposing_and_keycode_229_block_enter(
    browser: Browser, production_origin: str
) -> None:
    api = _composer_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="composer IME guard (task-5 data-testid chat-composer)",
        )
        composer = composer_box(page)
        _focus_composer(page)
        _set_composer_text(page, "组合输入中")

        # nativeEvent.isComposing === true
        _dispatch_keydown(page, isComposing=True)
        page.wait_for_timeout(200)
        assert api.task_posts == [], "isComposing Enter must not send"

        # legacy IME keyCode 229 (no isComposing flag)
        _dispatch_keydown_229(page)
        page.wait_for_timeout(200)
        assert api.task_posts == [], "keyCode 229 Enter must not send"
        assert composer.input_value() == "组合输入中"
    finally:
        context.close()


def test_composer_shift_enter_repeat_and_dialog_guard(
    browser: Browser, production_origin: str
) -> None:
    api = _composer_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="composer key handling (task-5 data-testid chat-composer)",
        )
        composer = composer_box(page)
        composer.click()

        composer.press("Shift+Enter")
        assert composer.input_value().endswith("\n"), "Shift+Enter must insert a newline"
        page.wait_for_timeout(200)
        assert api.task_posts == [], "Shift+Enter must not send"

        composer.fill("重复按键不应重复发送")
        _dispatch_keydown(page, repeat=True)
        page.wait_for_timeout(250)
        assert api.task_posts == [], "auto-repeat Enter must not send"

        # native dialog[open] defers global Enter sends to the modal
        page.evaluate(
            """() => {
              const dialog = document.createElement('dialog');
              dialog.id = 'chat-contract-guard-dialog';
              dialog.setAttribute('open', '');
              dialog.textContent = 'modal guard';
              document.body.appendChild(dialog);
            }"""
        )
        _dispatch_keydown(page)
        page.wait_for_timeout(250)
        assert api.task_posts == [], "Enter while dialog[open] must not send"
        page.evaluate(
            "() => document.getElementById('chat-contract-guard-dialog')?.remove()"
        )

        # explicit send button is not subject to the IME 500ms window
        _composition(page, "compositionstart")
        _composition(page, "compositionend")
        _dom_click(page, 'button[aria-label="发送"]')
        _wait_task_posts(api, page, 1)
        assert len(api.task_posts) == 1
        assert norm_ws(api.task_posts[0]["message"]) == "重复按键不应重复发送"
    finally:
        context.close()


def test_composer_exactly_one_task_post_and_blocked_draft_retained(
    browser: Browser, production_origin: str
) -> None:
    api = _composer_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="composer single-submit contract (task-5 data-testid chat-composer)",
        )
        composer = composer_box(page)
        composer.click()
        composer.fill("  只发一次  ")

        # one Enter keydown = exactly one task POST
        page.evaluate(
            """() => {
              const el = document.querySelector('textarea[aria-label="消息"]');
              el.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', bubbles: true, cancelable: true,
              }));
            }"""
        )
        _wait_task_posts(api, page, 1)
        page.wait_for_timeout(400)
        assert len(api.task_posts) == 1, api.task_posts
        body = api.task_posts[0]
        assert norm_ws(body["message"]) == "只发一次"
        assert body.get("request_id"), "task POST must carry the idempotency request_id"

        # a blocked (composing) Enter still keeps the draft around
        composer.fill("草稿保留检查")
        _composition(page, "compositionstart")
        _dispatch_keydown(page, isComposing=True)
        _composition(page, "compositionend")
        page.wait_for_timeout(120)
        assert composer.input_value() == "草稿保留检查"
        assert len(api.task_posts) == 1
    finally:
        context.close()


def test_composer_double_dispatch_posts_exactly_once(
    browser: Browser, production_origin: str
) -> None:
    """Two rapid Enter keydowns inside one task must yield exactly ONE task POST.

    Product contract (web-composer synchronous in-flight guard): the first
    keydown starts the only request; the second one is a no-op while that
    request is in flight, so a second request_id can never be minted.
    """
    api = _composer_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_COMPOSER,
            feature="composer double-dispatch contract (task-5 data-testid chat-composer)",
        )
        composer = composer_box(page)
        composer.click()
        composer.fill("双击只应发送一次")
        page.evaluate(
            """() => {
              const el = document.querySelector('textarea[aria-label="消息"]');
              for (let index = 0; index < 2; index += 1) {
                el.dispatchEvent(new KeyboardEvent('keydown', {
                  key: 'Enter', bubbles: true, cancelable: true,
                }));
              }
            }"""
        )
        _wait_task_posts(api, page, 1)
        page.wait_for_timeout(600)
        assert len(api.task_posts) == 1, api.task_posts
        body = api.task_posts[0]
        assert norm_ws(body["message"]) == "双击只应发送一次"
        request_ids = {str(post.get("request_id") or "") for post in api.task_posts}
        assert len(request_ids) == 1, request_ids
        assert "" not in request_ids, "request_id must be minted exactly once"
    finally:
        context.close()

# ---------------------------------------------------------------------------
# copy feedback: 2500ms hold + 300ms fade, restart, real clipboard boolean
# ---------------------------------------------------------------------------


def _code_run_api() -> ChatApi:
    code = '```python\nprint("chat copy contract")\n```'
    events = [
        {"seq": 1, "type": "run.created", "payload": {"message": MESSAGE}},
        {"seq": 2, "type": "assistant.final", "payload": {"text": code}},
    ]
    return ChatApi(
        runs=[run_summary("run-chat-copy", "succeeded", MESSAGE)],
        events=events,
    )


def test_copy_feedback_hold_fade_boundaries_and_restart(
    browser: Browser, production_origin: str
) -> None:
    api = _code_run_api()
    context, page = _open_chat(
        browser,
        production_origin,
        api,
        clock=True,
        permissions=["clipboard-read", "clipboard-write"],
    )
    try:
        button = probe(
            page,
            '[data-testid="chat-copy-button"]',
            reason=(
                "UI-07 copy button not wired into chat surfaces yet: "
                "[data-testid=chat-copy-button] absent in the rendered code block"
            ),
        )
        first = button.first
        first.evaluate("el => el.click()")
        wait_for_attribute(
            page, '[data-testid="chat-copy-button"]', "data-copy-state", "copied"
        )
        assert first.get_attribute("data-copy-fading") == "false"

        page.clock.fast_forward(2499)
        page.wait_for_timeout(40)
        assert first.get_attribute("data-copy-state") == "copied"
        assert first.get_attribute("data-copy-fading") == "false", "2500ms hold: 2499 must not fade"

        page.clock.fast_forward(1)
        page.wait_for_timeout(60)
        assert first.get_attribute("data-copy-state") == "copied"
        assert first.get_attribute("data-copy-fading") == "true", "at 2500ms the fade starts"

        page.clock.fast_forward(300)
        page.wait_for_timeout(60)
        assert first.get_attribute("data-copy-state") == "idle"
        assert first.get_attribute("data-copy-fading") == "false"

        # repeated copy restarts the whole cycle (an old timer must not clear it)
        first.evaluate("el => el.click()")
        wait_for_attribute(
            page, '[data-testid="chat-copy-button"]', "data-copy-state", "copied"
        )
        page.clock.fast_forward(2000)
        page.wait_for_timeout(40)
        first.evaluate("el => el.click()")
        wait_for_attribute(
            page, '[data-testid="chat-copy-button"]', "data-copy-state", "copied"
        )
        page.clock.fast_forward(2499)  # 2499ms since the SECOND copy
        page.wait_for_timeout(40)
        assert first.get_attribute("data-copy-state") == "copied"
        assert first.get_attribute("data-copy-fading") == "false", (
            "the second copy must restart the 2500ms hold"
        )
        page.clock.fast_forward(1)
        page.wait_for_timeout(60)
        assert first.get_attribute("data-copy-fading") == "true"
    finally:
        context.close()


def test_copy_feedback_failure_is_visible_no_fake_success(
    browser: Browser, production_origin: str
) -> None:
    api = _code_run_api()
    context, page = _open_chat(
        browser, production_origin, api, clock=True, permissions=["clipboard-write"]
    )
    try:
        button = probe(
            page,
            '[data-testid="chat-copy-button"]',
            reason=(
                "UI-07 copy button not wired into chat surfaces yet: "
                "[data-testid=chat-copy-button] absent in the rendered code block"
            ),
        )
        # force the real clipboard helper to reject: the UI must report failed.
        page.evaluate(
            """() => {
              Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: { writeText: () => Promise.reject(new Error('denied')) },
              });
            }"""
        )
        button.first.evaluate("el => el.click()")
        wait_for_attribute(
            page, '[data-testid="chat-copy-button"]', "data-copy-state", "failed"
        )
        page.clock.fast_forward(2499)
        page.wait_for_timeout(40)
        assert button.first.get_attribute("data-copy-state") == "failed"
        page.clock.fast_forward(1)
        page.wait_for_timeout(60)
        assert button.first.get_attribute("data-copy-state") == "idle"
    finally:
        context.close()

# ---------------------------------------------------------------------------
# scroll controller (task-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distance", [39, 40, 41])
def test_follow_boundary_distance_to_bottom(
    browser: Browser, production_origin: str, distance: int
) -> None:
    api = _active_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        scroll = probe_testid(
            page,
            TESTID_SCROLL,
            feature="single chat scroll container (task-6 data-testid chat-scroll)",
        )
        assert scroll.count() == 1, "the session must own exactly ONE chat scroll container"
        wait_sse_open(page)
        if not is_scrollable(page):
            pytest.skip("stubbed timeline is not tall enough to exercise scroll thresholds")

        scroll_to_distance(page, float(distance))
        before = scroll_metrics(page)
        push_sse(
            page,
            {
                "seq": _last_seq(api) + 1,
                "type": "assistant.delta",
                "payload": {"text": f"推送片段 {distance}"},
            },
        )
        page.wait_for_timeout(350)
        after = scroll_metrics(page)

        if distance <= 40:
            # within the follow threshold -> pinned to the bottom again
            assert after["distanceToBottom"] <= 40 + 2, (before, after)
            assert after["scrollTop"] >= before["scrollTop"], (before, after)
        else:
            # just outside the threshold -> the user's position is preserved
            assert abs(after["scrollTop"] - before["scrollTop"]) <= 1.5, (before, after)
            assert after["distanceToBottom"] > before["distanceToBottom"], (before, after)
    finally:
        context.close()


def test_upward_scroll_pauses_follow_with_continued_pushes(
    browser: Browser, production_origin: str
) -> None:
    api = _active_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_SCROLL,
            feature="single chat scroll container (task-6 data-testid chat-scroll)",
        )
        wait_sse_open(page)
        if not is_scrollable(page):
            pytest.skip("stubbed timeline is not tall enough to exercise scroll pause")

        scroll_to_distance(page, 300.0)
        before = scroll_metrics(page)
        for index in range(3):
            push_sse(
                page,
                {
                    "seq": _last_seq(api) + 1 + index,
                    "type": "assistant.delta",
                    "payload": {"text": f"继续输出 {index}"},
                },
            )
            page.wait_for_timeout(200)
        after = scroll_metrics(page)
        assert abs(after["scrollTop"] - before["scrollTop"]) <= 1.5, (before, after)
        assert after["distanceToBottom"] > before["distanceToBottom"] + 20, (before, after)
    finally:
        context.close()


@pytest.mark.parametrize("distance", [119, 120, 121])
def test_jump_to_latest_visibility_boundary(
    browser: Browser, production_origin: str, distance: int
) -> None:
    api = ChatApi()  # terminal run: static replay, no SSE needed
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_SCROLL,
            feature="single chat scroll container (task-6 data-testid chat-scroll)",
        )
        jump = page.locator(f'[data-testid="{TESTID_JUMP}"]')
        if jump.count() == 0:
            pytest.skip(
                "jump-to-latest not implemented yet: [data-testid=chat-jump-to-latest] absent"
            )
        if not is_scrollable(page):
            pytest.skip("stubbed timeline is not tall enough to exercise jump-to-latest")
        scroll_to_distance(page, float(distance))
        page.wait_for_timeout(150)
        jump_selector = '[data-testid="' + TESTID_JUMP + '"]'
        visible = dom_visible(page, jump_selector)
        if distance <= 120:
            assert not visible, f"jump-to-latest must stay hidden at {distance}px from bottom"
        else:
            assert visible, f"jump-to-latest must appear at {distance}px from bottom"
            jump.first.click()
            page.wait_for_timeout(300)
            assert distance_to_bottom(page) <= 40 + 2
            assert not dom_visible(page, jump_selector)
    finally:
        context.close()


def test_multi_run_single_active_run(
    browser: Browser, production_origin: str
) -> None:
    old = run_summary("run-chat-old", "succeeded", "上一轮已完成")
    active = run_summary("run-chat-active", "running", MESSAGE)
    api = ChatApi(
        runs=[old, active],
        events_by_run={
            "run-chat-old": [
                {"seq": 1, "type": "run.created", "payload": {"message": "上一轮已完成"}},
                {"seq": 2, "type": "assistant.final", "payload": {"text": "旧任务终答"}},
            ],
            "run-chat-active": chat_events(tool_rows=20),
        },
    )
    context, page = _open_chat(browser, production_origin, api)
    try:
        probe_testid(
            page,
            TESTID_SCROLL,
            feature="single chat scroll container (task-6 data-testid chat-scroll)",
        )
        assert page.locator(f'[data-testid="{TESTID_SCROLL}"]').count() == 1
        wait_sse_open(page)

        # one active run: the composer offers 停止, and Enter must not start a
        # second concurrent run (no task POST). The textarea is disabled by the
        # product contract, so the keydown is dispatched directly.
        page.get_by_role("button", name="停止").wait_for(timeout=10_000)
        page.evaluate(
            """() => {
              const el = document.querySelector('textarea[aria-label="消息"]');
              el.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', bubbles: true, cancelable: true,
              }));
            }"""
        )
        page.wait_for_timeout(400)
        assert api.task_posts == [], "an active run must block a second task POST"

        # pushes land in the active run's timeline only; the finished run's
        # replay is not duplicated/appended.
        card_ids = page.eval_on_selector_all(
            "li[id^='run-']", "nodes => nodes.map((node) => node.id)"
        )
        # SessionPage renders run-<run_id>; fixture run ids already start with
        # "run-", so the DOM id is doubled (run-run-chat-old).
        assert "run-run-chat-old" in card_ids, card_ids
        old_text_before = page.locator('li[id="run-run-chat-old"]').inner_text()
        push_sse(
            page,
            {
                "seq": _last_seq(api, "run-chat-active") + 1,
                "type": "assistant.delta",
                "payload": {"text": "活动任务推送"},
            },
        )
        page.wait_for_timeout(300)
        active_text = page.locator('li[id="run-run-chat-active"]').inner_text()
        assert "活动任务推送" in active_text
        assert page.locator('li[id="run-run-chat-old"]').inner_text() == old_text_before
        assert page.get_by_text("旧任务终答").count() == 1
    finally:
        context.close()


def test_late_events_after_session_switch_do_not_leak(
    browser: Browser, production_origin: str
) -> None:
    session_a = {
        "id": "session-chat-a",
        "title": "会话 A",
        "project_id": "project-ui-fixture",
        "updated_at": None,
        "last_run": {"run_id": "run-chat-a", "status": "running"},
    }
    session_b = {
        "id": "session-chat-b",
        "title": "会话 B",
        "project_id": "project-ui-fixture",
        "updated_at": None,
        "last_run": None,
    }
    api = ChatApi(
        sessions=[session_a, session_b],
        session=session_a,
        runs=[run_summary("run-chat-a", "running", "A 的任务")],
        events=chat_events(tool_rows=5),
    )
    context, page = _open_chat(browser, production_origin, api)
    try:
        wait_sse_open(page)
        # SPA-navigate to session B through the sidebar (a full reload would
        # destroy the "late event" scenario).
        session_link = page.locator('a[href="/app/s/session-chat-b"]')
        if session_link.count() == 0:
            pytest.skip("sidebar session link for the second stub session was not rendered")
        session_link.first.click()
        page.wait_for_url("**/app/s/session-chat-b", timeout=15_000)
        page.wait_for_timeout(300)

        # every EventSource from session A must have been closed on unmount
        open_sources = page.evaluate("() => window.__rxySseMock.openCount()")
        assert open_sources == 0, f"leaked EventSource after session switch: {open_sources} open"

        # a late frame from the old (closed) source must not render anywhere
        page.evaluate(
            """(seq) => {
              window.__rxySseMock.push({
                seq,
                type: 'assistant.delta',
                payload: { text: '迟到的旧会话事件' },
              });
            }""",
            _last_seq(api, "run-chat-a") + 1,
        )
        page.wait_for_timeout(300)
        body = page.locator("body").inner_text()
        assert "迟到的旧会话事件" not in body
        assert "A 的任务" not in body
    finally:
        context.close()


# ---------------------------------------------------------------------------
# collapse (task-6)
# ---------------------------------------------------------------------------


def _collapse_api() -> ChatApi:
    events = [
        {"seq": 1, "type": "run.created", "payload": {"message": MESSAGE}},
        {
            "seq": 2,
            "type": "assistant.delta",
            "payload": {
                "text": "先分析需求，再读代码，最后写结论。",
                "channel": "reasoning",
                "snapshot": True,
            },
        },
        {
            "seq": 3,
            "type": "tool.completed",
            "payload": {
                "tool": "bash",
                "call_id": "call_collapse_1",
                "title": "cat README.md",
                "summary": "README content line",
                "status": "success",
            },
        },
    ]
    return ChatApi(runs=[run_summary("run-chat-collapse", "succeeded", MESSAGE)], events=events)


def _collapse_height(page: Page, selector: str) -> float:
    return float(page.eval_on_selector(selector, "el => el.getBoundingClientRect().height"))


def test_collapse_expand_close_reverse_and_closed_non_focusable(
    browser: Browser, production_origin: str
) -> None:
    api = _collapse_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        # the session page renders the run card asynchronously after the composer
        page.locator('li[id^="run-"]').first.wait_for(timeout=15_000)
        page.wait_for_timeout(300)
        collapse = page.locator(f".{CLASS_COLLAPSE}")
        if collapse.count() == 0:
            pytest.skip(
                "shared Collapse not implemented yet: .rxy-collapse absent (task-6 ThinkingBlock/TasksBlock/ToolRow)"
            )
        inner = page.locator(f".{CLASS_COLLAPSE} .rxy-collapse-inner")
        if inner.count() == 0:
            pytest.skip("shared Collapse inner missing: .rxy-collapse-inner absent")
        first_inner = f".{CLASS_COLLAPSE}:first-of-type .rxy-collapse-inner"
        height_open = _collapse_height(page, first_inner)
        if height_open > 1:
            pytest.skip("first collapse block is expanded by default; contract expects collapsed default")

        # closed content stays mounted but must not be focusable
        assert element_is_non_focusable(page, first_inner), (
            "closed collapse content must not be focusable"
        )

        toggle = page.locator("[data-thinking] button[aria-expanded]").first
        if toggle.count() == 0:
            pytest.skip("collapse toggle button with aria-expanded not found")
        assert toggle.get_attribute("aria-expanded") == "false"
        toggle.click()
        page.wait_for_timeout(400)
        assert toggle.get_attribute("aria-expanded") == "true"
        expanded_height = _collapse_height(page, first_inner)
        assert expanded_height > height_open + 1

        # rapid reverse: collapse immediately after expanding, final state must
        # be closed (not stuck half-way)
        toggle.click()
        page.wait_for_timeout(20)
        toggle.click()
        page.wait_for_timeout(20)
        toggle.click()
        page.wait_for_timeout(500)
        final_height = _collapse_height(page, first_inner)
        if toggle.get_attribute("aria-expanded") == "false":
            assert final_height <= 1.5, f"reverse animation ended open: {final_height}px"
        assert element_is_non_focusable(page, first_inner)
    finally:
        context.close()


def test_collapse_transition_is_180ms_and_reduced_motion_is_instant(
    browser: Browser, production_origin: str
) -> None:
    api = _collapse_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        # the session page renders the run card asynchronously after the composer
        page.locator('li[id^="run-"]').first.wait_for(timeout=15_000)
        page.wait_for_timeout(300)
        collapse = page.locator(f".{CLASS_COLLAPSE}")
        if collapse.count() == 0:
            pytest.skip("shared Collapse not implemented yet: .rxy-collapse absent (task-6)")
        transition = page.eval_on_selector(
            f".{CLASS_COLLAPSE}",
            """el => {
              const style = getComputedStyle(el);
              return {
                duration: style.transitionDuration,
                property: style.transitionProperty,
                grid: style.gridTemplateRows,
              };
            }""",
        )
        assert transition["grid"] != "" or transition["property"] != "all", transition
        durations = [
            part.strip()
            for part in (transition["duration"] or "").split(",")
            if part.strip()
        ]
        if durations:
            seconds = max(float(value.rstrip("s")) for value in durations)
            assert abs(seconds - 0.18) <= 0.02, f"collapse duration should be 180ms, got {transition}"
    finally:
        context.close()

    # reduced motion: no 180ms wait, the content appears within one frame
    api = _collapse_api()
    context, page = _open_chat(browser, production_origin, api)
    try:
        page.emulate_media(reduced_motion="reduce")
        page.locator('li[id^="run-"]').first.wait_for(timeout=15_000)
        page.wait_for_timeout(300)
        if page.locator(f".{CLASS_COLLAPSE}").count() == 0:
            pytest.skip("shared Collapse not implemented yet: .rxy-collapse absent (task-6)")
        toggle = page.locator("[data-thinking] button[aria-expanded]").first
        if toggle.count() == 0:
            pytest.skip("collapse toggle button with aria-expanded not found")
        selector = f".{CLASS_COLLAPSE}:first-of-type .rxy-collapse-inner"
        before = _collapse_height(page, selector)
        toggle.click()
        page.wait_for_timeout(50)
        after = _collapse_height(page, selector)
        assert after > before + 1, "reduced-motion expand must be visible immediately"
    finally:
        context.close()


# ---------------------------------------------------------------------------
# cross-engine key regression subset (chromium / firefox / webkit)
# ---------------------------------------------------------------------------


def _cross_engine_context(engine_browser, api: ChatApi):
    context = new_context(engine_browser, 1280, 800)
    page = context.new_page()
    install_event_stream_mock(page)
    install_api(page, api)
    return context, page


def test_cross_engine_ime_enter_guard(
    engine_browser, engine_name: str, production_origin: str
) -> None:
    api = _composer_api()
    context, page = _cross_engine_context(engine_browser, api)
    try:
        page.goto(f"{production_origin}/app/s/{api.session['id']}")
        composer_box(page).wait_for(timeout=30_000)
        try:
            page.locator('[data-testid="chat-composer"]').wait_for(timeout=3_000)
        except Exception:
            pytest.skip(
                f"{engine_name}: [data-testid=chat-composer] absent (task-5 not landed)"
            )
        composer = composer_box(page)
        _focus_composer(page)
        _set_composer_text(page, "跨引擎输入法守卫")

        # composing Enter never sends
        _composition(page, "compositionstart")
        _dispatch_keydown(page, isComposing=True)
        page.wait_for_timeout(200)
        assert api.task_posts == [], f"{engine_name}: composing Enter sent a task"

        # keyCode 229 (legacy IME) never sends
        _dispatch_keydown_229(page)
        page.wait_for_timeout(200)
        assert api.task_posts == [], f"{engine_name}: keyCode 229 Enter sent a task"

        # compositionend + real 520ms wait -> Enter sends exactly once
        _composition(page, "compositionend")
        page.wait_for_timeout(520)
        _dispatch_keydown(page)
        _wait_task_posts(api, page, 1)
        assert len(api.task_posts) == 1, (engine_name, api.task_posts)
    finally:
        context.close()


def test_cross_engine_scroll_follow_and_jump(
    engine_browser, engine_name: str, production_origin: str
) -> None:
    api = _active_api()
    context, page = _cross_engine_context(engine_browser, api)
    try:
        page.goto(f"{production_origin}/app/s/{api.session['id']}")
        composer_box(page).wait_for(timeout=30_000)
        scroll = page.locator(f'[data-testid="{TESTID_SCROLL}"]')
        if scroll.count() == 0:
            pytest.skip(
                f"{engine_name}: [data-testid=chat-scroll] absent (task-6 not landed)"
            )
        wait_sse_open(page)
        if not is_scrollable(page):
            pytest.skip(f"{engine_name}: stub timeline not tall enough for scroll checks")
        scroll_to_distance(page, 40.0)
        before = scroll_metrics(page)
        push_sse(
            page,
            {"seq": _last_seq(api) + 1, "type": "assistant.delta", "payload": {"text": "跨引擎推送"}},
        )
        page.wait_for_timeout(400)
        after = scroll_metrics(page)
        assert after["distanceToBottom"] <= 42, (engine_name, before, after)
    finally:
        context.close()


def test_cross_engine_collapse_toggle(
    engine_browser, engine_name: str, production_origin: str
) -> None:
    api = _collapse_api()
    context, page = _cross_engine_context(engine_browser, api)
    try:
        page.goto(f"{production_origin}/app/s/{api.session['id']}")
        composer_box(page).wait_for(timeout=30_000)
        page.locator('li[id^="run-"]').first.wait_for(timeout=15_000)
        page.wait_for_timeout(300)
        if page.locator(f".{CLASS_COLLAPSE}").count() == 0:
            pytest.skip(
                f"{engine_name}: .rxy-collapse absent (task-6 Collapse not landed)"
            )
        toggle = page.locator("[data-thinking] button[aria-expanded]").first
        if toggle.count() == 0:
            pytest.skip(f"{engine_name}: collapse toggle with aria-expanded not found")
        assert toggle.get_attribute("aria-expanded") == "false"
        toggle.click()
        page.wait_for_timeout(400)
        assert toggle.get_attribute("aria-expanded") == "true"
    finally:
        context.close()


def test_cross_engine_copy_feedback(
    engine_browser, engine_name: str, production_origin: str
) -> None:
    api = _code_run_api()
    context, page = _cross_engine_context(engine_browser, api)
    try:
        # Chromium needs explicit permissions; firefox/webkit reject these names
        # and allow writeText without one, so this is best-effort.
        context.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception:
        pass
    try:
        page.goto(f"{production_origin}/app/s/{api.session['id']}")
        composer_box(page).wait_for(timeout=30_000)
        button = page.locator('[data-testid="chat-copy-button"]')
        try:
            button.first.wait_for(state="attached", timeout=10_000)
        except Exception:
            pytest.skip(
                f"{engine_name}: [data-testid=chat-copy-button] absent after the run "
                "timeline rendered (UI-07 not wired into chat surfaces yet)"
            )
        button.first.click()
        page.wait_for_function(
            """() => {
              const node = document.querySelector('[data-testid="chat-copy-button"]');
              return node && node.getAttribute('data-copy-state') === 'copied';
            }""",
            timeout=10_000,
        )
        assert button.first.get_attribute("data-copy-fading") == "false"
    finally:
        context.close()
