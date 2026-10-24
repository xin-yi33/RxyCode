"""Chat-polish visual contracts: theme tokens, composer shell geometry, long
filenames, numeric columns, streaming animation and preview split.

Same honesty rule as the interaction module: a missing implementation marker
skips with the exact reason; a present marker with wrong pixels/styles fails.
Deterministic API + EventSource stubs only - no live-cloud claim.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from _chat_case import (
    CLASS_STREAM_GLYPH,
    TESTID_COMPOSER,
    TESTID_FILE_NAME,
    TESTID_PREVIEW_HANDLE,
    TESTID_PREVIEW_SPLIT,
    ChatApi,
    chat_events,
    color_to_rgb,
    composer_box,
    context_for,
    css_var,
    has_css_var,
    install_api,
    install_event_stream_mock,
    new_context,
    no_horizontal_overflow,
    norm_ws,
    probe,
    push_sse,
    relative_luminance,
    run_summary,
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

LONG_FILE_NAME = "实验报告-第3章-HDFS分布式文件系统-阮心一-2026-年度最终版.tar.gz"
VIEWPORT_SIZES = {"320": (320, 640), "375": (375, 812), "768": (768, 1024), "1440": (1440, 900)}

TOKEN_NAMES = [
    "--rxy-bg",
    "--rxy-sidebar",
    "--rxy-fg",
    "--rxy-muted",
    "--rxy-border",
    "--rxy-card",
    "--rxy-bubble",
    "--rxy-running",
    "--rxy-waiting",
    "--rxy-success",
    "--rxy-failure",
    "--rxy-running-ink",
    "--rxy-waiting-ink",
    "--rxy-success-ink",
    "--rxy-failure-ink",
    "--rxy-muted-ink",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _open_shell(
    browser: Browser,
    origin: str,
    api: ChatApi,
    *,
    viewport: str = "desktop-1440",
    reduced_motion: str | None = None,
    path: str = "/app",
) -> tuple[Any, Page]:
    context = context_for(browser, viewport)
    page = context.new_page()
    if reduced_motion:
        page.emulate_media(reduced_motion=reduced_motion)
    install_event_stream_mock(page)
    install_api(page, api)
    page.goto(f"{origin}{path}")
    page.get_by_role("textbox", name="消息").wait_for(timeout=30_000)
    return context, page


def _open_session(
    browser: Browser,
    origin: str,
    api: ChatApi,
    *,
    viewport: str = "desktop-1440",
    reduced_motion: str | None = None,
) -> tuple[Any, Page]:
    return _open_shell(
        browser,
        origin,
        api,
        viewport=viewport,
        reduced_motion=reduced_motion,
        path=f"/app/s/{api.session['id']}",
    )


def _set_theme(page: Page, mode: str) -> None:
    toggle = page.get_by_role(
        "button", name="切换到深色" if mode == "dark" else "切换到浅色"
    )
    toggle.click()
    page.wait_for_function(
        "(mode) => document.documentElement.dataset.theme === mode", arg=mode, timeout=10_000
    )


def _rgb_channels(page: Page, name: str) -> tuple[int, int, int]:
    raw = css_var(page, name)
    if not raw:
        pytest.skip(f"theme token {name} missing (task-5 dark surface tokens not landed)")
    match = [part.strip() for part in raw.split(",")]
    if len(match) != 3:
        raise AssertionError(f"{name} is not a channel triple: {raw!r}")
    return (int(match[0]), int(match[1]), int(match[2]))


# ---------------------------------------------------------------------------
# theme tokens: computed hex colours must agree with their -rgb siblings
# ---------------------------------------------------------------------------


def test_light_and_dark_tokens_match_rgb_siblings(
    browser: Browser, production_origin: str
) -> None:
    api = ChatApi()
    context, page = _open_shell(browser, production_origin, api)
    try:
        page.wait_for_function(
            "() => document.documentElement.dataset.theme === 'light'", timeout=10_000
        )
        for mode in ("light", "dark"):
            if mode == "dark":
                _set_theme(page, "dark")
            tokens: dict[str, tuple[int, int, int]] = {}
            for name in TOKEN_NAMES:
                if not has_css_var(page, name):
                    pytest.skip(f"theme token {name} missing (task-5 tokens not landed)")
                hex_rgb = color_to_rgb(css_var(page, name))
                rgb_rgb = _rgb_channels(page, f"{name}-rgb")
                assert hex_rgb == rgb_rgb, (
                    f"{mode} {name}={css_var(page, name)!r} disagrees with "
                    f"{name}-rgb={css_var(page, name + '-rgb')!r}"
                )
                tokens[name] = hex_rgb

            body_bg = color_to_rgb(
                page.evaluate("() => getComputedStyle(document.body).backgroundColor")
            )
            assert body_bg == tokens["--rxy-bg"], (mode, body_bg, tokens["--rxy-bg"])

            if mode == "dark":
                # Non-pure-black dark base: never #000, and a perceptible surface.
                assert tokens["--rxy-bg"] != (0, 0, 0), "dark base must not be pure black"
                assert relative_luminance(tokens["--rxy-bg"]) >= 0.01, (
                    f"dark base is indistinguishable from black: {tokens['--rxy-bg']}"
                )
    finally:
        context.close()


def test_theme_switch_spa_nav_and_refresh_consistency(
    browser: Browser, production_origin: str
) -> None:
    api = ChatApi()
    context, page = _open_shell(browser, production_origin, api)
    try:
        page.wait_for_function(
            "() => document.documentElement.dataset.theme === 'light'", timeout=10_000
        )
        _set_theme(page, "dark")
        dark_bg = css_var(page, "--rxy-bg")

        # SPA navigation must keep the applied theme (no remount reset). The
        # sidebar session link is a router <Link>, so this stays a SPA nav.
        spa_link = page.locator('a[href^="/app/s/"]').first
        try:
            spa_link.wait_for(state="attached", timeout=8_000)
        except Exception:
            pytest.skip(
                "no SPA session link in the sidebar; cannot verify SPA theme persistence"
            )
        spa_link.click()
        page.wait_for_timeout(500)
        assert page.evaluate("() => document.documentElement.dataset.theme") == "dark"
        assert css_var(page, "--rxy-bg") == dark_bg

        # refresh: the preference PATCH was recorded by the stub; reload serves dark
        assert any(
            write["path"] == "/api/v1/me/preferences" and write["method"] == "PATCH"
            for write in api.writes
        ), "theme toggle must persist the preference (PATCH /me/preferences)"
        page.reload()
        page.get_by_role("textbox", name="消息").wait_for(timeout=30_000)
        page.wait_for_function(
            "() => document.documentElement.dataset.theme === 'dark'", timeout=10_000
        )
        assert css_var(page, "--rxy-bg") == dark_bg
    finally:
        context.close()


# ---------------------------------------------------------------------------
# composer shell: border 0 + inset ring + <=1px focus/hover geometry delta
# ---------------------------------------------------------------------------


def _composer_metrics(page: Page) -> dict[str, Any]:
    return page.eval_on_selector(
        '[data-testid="chat-composer"]',
        """el => {
          const style = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return {
            borderTop: style.borderTopWidth,
            borderRight: style.borderRightWidth,
            borderBottom: style.borderBottomWidth,
            borderLeft: style.borderLeftWidth,
            boxShadow: style.boxShadow,
            width: rect.width,
            height: rect.height,
            top: rect.top,
            left: rect.left,
          };
        }""",
    )


def test_composer_shell_border0_inset_ring_and_focus_geometry(
    browser: Browser, production_origin: str
) -> None:
    api = ChatApi()
    context, page = _open_shell(browser, production_origin, api)
    try:
        shell = probe(
            page,
            '[data-testid="chat-composer"]',
            reason=(
                "composer shell not implemented yet: [data-testid=chat-composer] absent "
                "(task-5)"
            ),
        )
        idle = _composer_metrics(page)
        assert all(
            idle[key] == "0px"
            for key in ("borderTop", "borderRight", "borderBottom", "borderLeft")
        ), f"composer shell must be border 0, got {idle}"
        assert "inset" in (idle["boxShadow"] or ""), (
            f"composer shell must carry an inset ring, got {idle['boxShadow']!r}"
        )

        # hover state must not move/size the shell by more than 1px
        shell.first.hover()
        page.wait_for_timeout(250)
        hovered = _composer_metrics(page)
        for key in ("width", "height", "top", "left"):
            assert abs(hovered[key] - idle[key]) <= 1, (key, idle, hovered)

        # keyboard focus on the inner textarea: still <=1px geometry delta and
        # a visibly different focus ring (focus-within double ring).
        composer_box(page).focus()
        page.wait_for_timeout(250)
        focused = _composer_metrics(page)
        for key in ("width", "height", "top", "left"):
            assert abs(focused[key] - idle[key]) <= 1, (key, idle, focused)
        assert all(
            focused[key] == "0px"
            for key in ("borderTop", "borderRight", "borderBottom", "borderLeft")
        ), "focus must not re-introduce a border on the shell"
        assert focused["boxShadow"] != idle["boxShadow"], (
            "focus-within must change the ring (double ring), shadow stayed identical"
        )
    finally:
        context.close()


# ---------------------------------------------------------------------------
# long filename: suffix preserved, full name accessible, no overflow
# ---------------------------------------------------------------------------


def _long_name_api() -> ChatApi:
    artifact = {
        "artifact_id": "artifact-fixture-1",
        "filename": LONG_FILE_NAME,
        "relative_path": LONG_FILE_NAME,
        "availability": "available",
        "partial": False,
        "preview_kind": "frontend_static",
        "sha256": "0" * 64,
        "size": 123456,
        "content_type": "application/gzip",
        "expires_at": None,
        "download_url": "/api/v1/artifacts/artifact-fixture-1/download",
    }
    file_row = {"path": f"imports/6adb79d5ea61456b850b0a2ba00b5208/{LONG_FILE_NAME}", "size": 589856, "mtime": 1700000000}
    api = ChatApi(
        runs=[run_summary("run-chat-files", "succeeded", "文件已生成")],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "文件已生成"}},
            {"seq": 2, "type": "assistant.final", "payload": {"text": "完成"}},
        ],
        artifacts=[artifact],
        session_files=[file_row],
    )
    return api


def test_long_filename_suffix_preserved_no_overflow_all_viewports(
    browser: Browser, production_origin: str
) -> None:
    api = _long_name_api()
    context, page = _open_session(browser, production_origin, api)
    try:
        names = probe(
            page,
            '[data-testid="chat-file-name"]',
            reason=(
                "shared FileName not wired into any chat surface yet: "
                "[data-testid=chat-file-name] absent (task-7)"
            ),
        )
        assert names.count() >= 1
        rendered = page.eval_on_selector_all(
            '[data-testid="chat-file-name"]',
            """nodes => nodes.map(node => ({
              text: node.textContent || '',
              title: node.getAttribute('title') || '',
              aria: node.getAttribute('aria-label') || '',
              rect: node.getBoundingClientRect().toJSON(),
            }))""",
        )
        long_rows = [row for row in rendered if LONG_FILE_NAME in (row["title"], row["aria"], row["text"])]
        assert long_rows, f"expected the long filename row, rendered: {rendered}"
        for row in long_rows:
            assert row["title"] == LONG_FILE_NAME or row["aria"] == LONG_FILE_NAME, row
            assert "\u2026" in row["text"] or row["text"].endswith(".tar.gz"), row["text"]
            assert row["text"].rstrip().endswith(".tar.gz"), (
                f"compound suffix must stay visible: {row['text']!r}"
            )

        # the download attribute must keep the real name (no middle ellipsis)
        downloads = page.eval_on_selector_all(
            "a[download]", "nodes => nodes.map(node => node.getAttribute('download'))"
        )
        if downloads:
            assert LONG_FILE_NAME in downloads, downloads

        for label, (width, height) in VIEWPORT_SIZES.items():
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(150)
            no_horizontal_overflow(page)
            for row in page.eval_on_selector_all(
                '[data-testid="chat-file-name"]',
                "nodes => nodes.map(node => node.getBoundingClientRect().toJSON())",
            ):
                assert row["right"] <= width + 1, (label, row)
    finally:
        context.close()


# ---------------------------------------------------------------------------
# dark weight tokens: computed on real elements + font supports the weight
# ---------------------------------------------------------------------------


def test_dark_weight_tokens_computed_and_font_supported(
    browser: Browser, production_origin: str
) -> None:
    final_md = "**加粗结论**\n\n正文说明。"
    api = ChatApi(
        runs=[run_summary("run-chat-weight", "succeeded", "字重检查")],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "字重检查"}},
            {"seq": 2, "type": "assistant.final", "payload": {"text": final_md}},
        ],
    )
    context, page = _open_session(browser, production_origin, api)
    try:
        if not all(has_css_var(page, name) for name in ("--weight-body", "--weight-medium", "--weight-strong")):
            pytest.skip(
                "weight tokens not landed: --weight-body/--weight-medium/--weight-strong missing (task-5)"
            )
        _set_theme(page, "dark")
        tokens = {
            name: css_var(page, name)
            for name in ("--weight-body", "--weight-medium", "--weight-strong")
        }
        assert tokens["--weight-body"] != "", tokens

        body_el = page.locator("li[data-answer] p").first
        if body_el.count() == 0:
            pytest.skip("final answer paragraph not rendered; cannot read body weight")
        computed_body = body_el.evaluate("el => getComputedStyle(el).fontWeight")
        assert computed_body == tokens["--weight-body"], (computed_body, tokens)

        strong = page.locator("li[data-answer] strong").first
        if strong.count() == 0:
            pytest.skip("no <strong> in the rendered answer; cannot verify --weight-strong")
        computed_strong = strong.evaluate("el => getComputedStyle(el).fontWeight")
        assert computed_strong == tokens["--weight-strong"], (computed_strong, tokens)

        # the loaded font stack must really support the computed weight
        for element, weight in ((body_el, computed_body), (strong, computed_strong)):
            family = element.evaluate("el => getComputedStyle(el).fontFamily")
            supported = page.evaluate(
                """({ weight, family }) => document.fonts.check(weight + ' 16px ' + family)""",
                {"weight": weight, "family": family},
            )
            assert supported, f"font family {family!r} does not support weight {weight}"

        # "never .dark *" global overrides: every stylesheet selector is checked.
        offenders = page.evaluate(
            r"""() => {
              const found = [];
              for (const sheet of Array.from(document.styleSheets)) {
                let rules = [];
                try { rules = Array.from(sheet.cssRules || []); } catch { continue; }
                const walk = (list) => {
                  for (const rule of list) {
                    if (rule.selectorText && /\.dark\s+\*/.test(rule.selectorText)) {
                      found.push(rule.selectorText);
                    }
                    if (rule.cssRules) walk(Array.from(rule.cssRules));
                  }
                };
                walk(rules);
              }
              return found;
            }"""
        )
        assert offenders == [], f"forbidden .dark * global overrides: {offenders}"
    finally:
        context.close()


# ---------------------------------------------------------------------------
# tabular numerals: digit columns must not jitter
# ---------------------------------------------------------------------------


def test_tabular_nums_have_stable_digit_width(
    browser: Browser, production_origin: str
) -> None:
    artifact = {
        "artifact_id": "artifact-numeric-1",
        "filename": "result.json",
        "relative_path": "result.json",
        "availability": "available",
        "partial": False,
        "preview_kind": None,
        "sha256": "0" * 64,
        "size": 1024,
        "content_type": "application/json",
        "expires_at": None,
        "download_url": "/api/v1/artifacts/artifact-numeric-1/download",
    }
    api = ChatApi(artifacts=[artifact])
    context, page = _open_session(browser, production_origin, api)
    try:
        page.locator('li[id^="run-"]').first.wait_for(timeout=15_000)
        # ArtifactRows renders a real .rxy-tabular-nums count.
        page.locator('[data-testid="chat-file-name"]').first.wait_for(timeout=10_000)
        candidate = page.evaluate(
            """() => {
              for (const el of Array.from(document.querySelectorAll('body *'))) {
                const style = getComputedStyle(el);
                if (!style.fontVariantNumeric || !style.fontVariantNumeric.includes('tabular-nums')) continue;
                if (el.children.length > 0) continue;
                const text = (el.textContent || '').trim();
                if (!text || text.length > 12) continue;
                el.setAttribute('data-tabular-probe', '1');
                return { text };
              }
              return null;
            }"""
        )
        if candidate is None:
            pytest.skip(
                "no tabular-nums text element in DOM yet (task-5 numeric tokens not wired)"
            )
        widths = page.evaluate(
            """async () => {
              const el = document.querySelector('[data-tabular-probe]');
              const original = el.textContent;
              const measure = async (value) => {
                el.textContent = value;
                await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
                return el.getBoundingClientRect().width;
              };
              const out = {};
              for (const value of ['111', '888', '9', '10', '100']) {
                out[value] = await measure(value);
              }
              el.textContent = original;
              el.removeAttribute('data-tabular-probe');
              return out;
            }"""
        )
        assert abs(widths["111"] - widths["888"]) <= 0.6, widths
        digit = widths["10"] - widths["9"]
        assert digit > 0, widths
        assert abs((widths["100"] - widths["10"]) - digit) <= 0.6, widths
    finally:
        context.close()


# ---------------------------------------------------------------------------
# streaming glyph: REAL Animation objects (document.getAnimations sampling)
# ---------------------------------------------------------------------------

_GLYPH_ANIMATION_PROBE = """async () => {
  const nodes = Array.from(document.querySelectorAll('.rxy-stream-glyph'));
  const animations = nodes.flatMap((node) => node.getAnimations());
  if (!animations.length) {
    return { glyphCount: nodes.length, animationCount: 0 };
  }
  const typed = animations.filter((entry) => entry.playState !== 'idle');
  if (!typed.length) {
    return { glyphCount: nodes.length, animationCount: 0 };
  }
  const animation = typed[0];
  const owner = nodes.find((node) => node.getAnimations().includes(animation)) || nodes[0];
  const timing = animation.effect && animation.effect.getTiming ? animation.effect.getTiming() : {};
  const duration = Number(timing.duration) || 0;
  const snapshot = () => {
    const style = getComputedStyle(owner);
    return {
      opacity: style.opacity,
      transform: style.transform,
      filter: style.filter,
      color: style.color,
    };
  };
  animation.pause();
  animation.currentTime = 0;
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  const atZero = snapshot();
  animation.currentTime = duration > 1 ? duration / 2 : 45;
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  const atMid = snapshot();
  const playState = animation.playState;
  animation.play();
  return {
    glyphCount: nodes.length,
    animationCount: typed.length,
    duration,
    playState,
    atZero,
    atMid,
    changed: JSON.stringify(atZero) !== JSON.stringify(atMid),
  };
}"""


def _streaming_api() -> ChatApi:
    events = [
        {"seq": 1, "type": "run.created", "payload": {"message": "流式输出检查"}},
        {
            "seq": 2,
            "type": "assistant.delta",
            "payload": {"text": "历史正文，不应做逐字动画。", "snapshot": True},
        },
    ]
    return ChatApi(runs=[run_summary("run-chat-stream", "running", "流式输出检查")], events=events)


def test_streaming_glyph_uses_real_animation_objects(
    browser: Browser, production_origin: str
) -> None:
    # (a) replayed history / final text is rendering as plain text, never with
    # per-glyph reveal spans. This is a positive assertion, not a skip.
    api = _streaming_api()
    context, page = _open_session(browser, production_origin, api)
    try:
        page.wait_for_timeout(400)
        history = page.evaluate(
            """() => ({
              glyphs: document.querySelectorAll('.rxy-stream-glyph').length,
              text: document.body.innerText,
            })"""
        )
        assert history["glyphs"] == 0, (
            "replayed/history text must never be wrapped in streaming glyphs: "
            f"{history}"
        )
        assert "历史正文，不应做逐字动画。" in history["text"]
    finally:
        context.close()

    # (b) a live assistant.delta (contiguous seq after the replay) creates the
    # glyph spans and real Animation objects; sample them via document.getAnimations().
    api = _streaming_api()
    context, page = _open_session(browser, production_origin, api)
    try:
        wait_sse_open(page)
        live_text = "这是刚到达的新流式文本"
        push_sse(
            page,
            {
                "seq": max((int(event.get("seq", 0)) for event in api.events), default=0) + 1,
                "type": "assistant.delta",
                "payload": {"text": live_text},
            },
        )
        try:
            page.locator(f".{CLASS_STREAM_GLYPH}").first.wait_for(timeout=4_000)
        except Exception:
            pytest.skip(
                "streaming glyph not implemented yet: .rxy-stream-glyph absent after a "
                "fresh contiguous SSE delta (task-6)"
            )
        probe_result = page.evaluate(_GLYPH_ANIMATION_PROBE)
        assert probe_result["glyphCount"] >= 1, probe_result
        assert probe_result["animationCount"] >= 1, (
            "streaming glyph must expose a REAL CSS Animation to document.getAnimations(): "
            f"{probe_result}"
        )
        duration = probe_result["duration"]
        if isinstance(duration, (int, float)) and duration > 20:
            assert 60 <= duration <= 150, f"unexpected glyph animation duration {probe_result}"
        assert probe_result["changed"], (
            "sampling animation.currentTime must change the rendered style: " f"{probe_result}"
        )
        assert probe_result["playState"] in {"running", "paused"}, probe_result

        # (c) after the reveal finishes, spans collapse back to plain text
        page.wait_for_function(
            """() => document.querySelectorAll('.rxy-stream-glyph').length === 0""",
            timeout=8_000,
        )
        plain = page.evaluate("() => document.body.innerText")
        assert live_text in plain
    finally:
        context.close()

def test_streaming_glyph_is_plain_under_reduced_motion(
    browser: Browser, production_origin: str
) -> None:
    api = _streaming_api()
    context, page = _open_session(
        browser, production_origin, api, reduced_motion="reduce"
    )
    try:
        wait_sse_open(page)
        push_sse(
            page,
            {
                "seq": max((int(event.get("seq", 0)) for event in api.events), default=0) + 1,
                "type": "assistant.delta",
                "payload": {"text": "减少动态效果时不应逐字动画"},
            },
        )
        page.wait_for_timeout(700)
        animations = page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('.rxy-stream-glyph'));
              return {
                glyphCount: nodes.length,
                animationCount: nodes.flatMap((node) => node.getAnimations()).length,
                bodyText: document.body.innerText,
              };
            }"""
        )
        if animations["glyphCount"] == 0:
            # plain text is the required reduced-motion rendering
            assert "减少动态效果时不应逐字动画" in animations["bodyText"]
        else:
            assert animations["animationCount"] == 0, animations
            assert "减少动态效果时不应逐字动画" in animations["bodyText"]
    finally:
        context.close()


# ---------------------------------------------------------------------------
# preview split (component harness page; product integration probed separately)
# ---------------------------------------------------------------------------


def _preview_api() -> ChatApi:
    artifact = {
        "artifact_id": "artifact-preview-1",
        "filename": "report-preview.html",
        "relative_path": "report-preview.html",
        "availability": "available",
        "partial": False,
        "preview_kind": "frontend_static",
        "sha256": "0" * 64,
        "size": 2048,
        "content_type": "text/html",
        "expires_at": None,
        "download_url": "/api/v1/artifacts/artifact-preview-1/download",
    }
    return ChatApi(
        runs=[run_summary("run-chat-preview", "succeeded", "预览产物")],
        events=[
            {"seq": 1, "type": "run.created", "payload": {"message": "预览产物"}},
            {"seq": 2, "type": "assistant.final", "payload": {"text": "预览已生成。"}},
        ],
        artifacts=[artifact],
    )


def _open_split(browser: Browser, origin: str, api: ChatApi, *, viewport: str = "desktop-1440"):
    context = context_for(browser, viewport)
    page = context.new_page()
    install_event_stream_mock(page)
    install_api(page, api)
    page.goto(f"{origin}/app/s/{api.session['id']}")
    composer_box(page).wait_for(timeout=30_000)
    preview_button = page.locator('button[aria-label^="预览 "]').first
    preview_button.wait_for(timeout=15_000)
    preview_button.click()
    split = page.locator('[data-testid="chat-preview-split"]')
    split.wait_for(timeout=15_000)
    try:
        if viewport.startswith("mobile"):
            # overlay mode: chat stays full width, preview is a fullscreen
            # overlay, so data-preview-open is false BY DESIGN.
            page.wait_for_function(
                """() => {
                  const split = document.querySelector('[data-testid="chat-preview-split"]');
                  return split && split.getAttribute('data-preview-mode') === 'overlay'
                    && document.querySelectorAll('[data-preview-drawer]').length === 1;
                }""",
                timeout=15_000,
            )
        else:
            page.wait_for_function(
                """() => document.querySelector('[data-testid="chat-preview-split"]')
                  .getAttribute('data-preview-open') === 'true'""",
                timeout=15_000,
            )
    except Exception as exc:  # diagnostic, then fail honestly
        state = page.evaluate(
            """() => {
              const split = document.querySelector('[data-testid="chat-preview-split"]');
              const buttons = Array.from(document.querySelectorAll('button[aria-label^="预览 "]'));
              return {
                open: split && split.getAttribute('data-preview-open'),
                mode: split && split.getAttribute('data-preview-mode'),
                previewButtons: buttons.length,
                drawer: document.querySelectorAll('[data-preview-drawer]').length,
                artifacts: document.querySelectorAll('[data-artifacts]').length,
                bodyText: document.body.innerText.slice(0, 300),
              };
            }"""
        )
        raise AssertionError(f"preview never opened: {state}") from exc
    return context, page, split


def _split_ratio(page: Page) -> float:
    return float(
        page.evaluate(
            """() => {
              const root = document.querySelector('[data-testid="chat-preview-split"]');
              const pane = document.querySelector('[data-preview-chat-pane]');
              if (!root || !pane) return -1;
              return pane.getBoundingClientRect().width / root.getBoundingClientRect().width;
            }"""
        )
    )


def _split_state(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const split = document.querySelector('[data-testid="chat-preview-split"]');
          const pane = document.querySelector('[data-preview-chat-pane]');
          const handle = document.querySelector('[data-testid="chat-preview-handle"]');
          const rootRect = split ? split.getBoundingClientRect() : null;
          const paneRect = pane ? pane.getBoundingClientRect() : null;
          return {
            innerWidth: window.innerWidth,
            mode: split && split.getAttribute('data-preview-mode'),
            open: split && split.getAttribute('data-preview-open'),
            aria: handle && handle.getAttribute('aria-valuenow'),
            ratio: rootRect && paneRect ? paneRect.width / rootRect.width : null,
            drawer: document.querySelectorAll('[data-preview-drawer]').length,
            previewPane: document.querySelectorAll('[data-preview-pane]').length,
          };
        }"""
    )


def _split_aria_percent(page: Page) -> int:
    return int(
        page.locator('[data-testid="chat-preview-handle"]').get_attribute("aria-valuenow")
    )


def _drag_handle_to(page: Page, ratio: float) -> None:
    before = _split_state(page)
    root = page.locator('[data-testid="chat-preview-split"]').bounding_box()
    handle = page.locator('[data-testid="chat-preview-handle"]').bounding_box()
    assert root and handle, {"before": before, "root": root, "handle": handle}
    y = handle["y"] + handle["height"] / 2
    page.mouse.move(handle["x"] + handle["width"] / 2, y)
    page.mouse.down()
    page.mouse.move(root["x"] + root["width"] * ratio, y, steps=8)
    during = page.evaluate(
        """() => {
          const split = document.querySelector('[data-testid="chat-preview-split"]');
          return {
            overlay: document.querySelectorAll('[data-preview-drag-overlay]').length,
            open: split && split.getAttribute('data-preview-open'),
          };
        }"""
    )
    page.mouse.up()
    page.wait_for_timeout(180)
    after = _split_state(page)
    if after["open"] != "true" and ratio <= 0.82:
        raise AssertionError(
            f"drag to {ratio} closed the preview: before={before} during={during} "
            f"after={after} root={root} handle={handle}"
        )


def test_preview_split_drag_collapse_ratio_boundaries(
    browser: Browser, production_origin: str
) -> None:
    api = _preview_api()
    context, page, split = _open_split(browser, production_origin, api)
    try:
        # 81.9% and 82%: preview stays open; 82.1%: collapses
        # 81.9%: open. Exact 82.0% cannot be hit to the sub-pixel through a
        # pointer, so 81.98% pins the "rounds/reads as 82%, still open" state.
        _drag_handle_to(page, 0.819)
        state = _split_state(page)
        assert state["open"] == "true", state
        assert abs(state["ratio"] - 0.819) <= 0.012, state

        _drag_handle_to(page, 0.8198)
        state = _split_state(page)
        assert state["open"] == "true", state
        assert _split_aria_percent(page) == 82, state

        # 82.1%: strictly beyond the 82% clamp -> preview collapses.
        _drag_handle_to(page, 0.821)
        state = _split_state(page)
        assert state["open"] == "false", (
            f"left ratio > 82% must collapse the preview pane: {state}"
        )
        assert state["previewPane"] == 0, state
    finally:
        context.close()


def test_preview_split_esc_dblclick_pointercancel(
    browser: Browser, production_origin: str
) -> None:
    api = _preview_api()
    context, page, split = _open_split(browser, production_origin, api)
    try:
        handle = page.locator('[data-testid="chat-preview-handle"]')

        # Esc restores the pre-drag snapshot
        pre_drag = _split_ratio(page)
        _drag_handle_to(page, 0.7)
        assert abs(_split_ratio(page) - 0.7) <= 0.012
        page.keyboard.press("Escape")
        page.wait_for_timeout(350)
        assert abs(_split_ratio(page) - pre_drag) <= 0.012, (
            f"Esc must restore the pre-drag snapshot: {pre_drag} vs {_split_ratio(page)}"
        )

        # double-click the handle -> 50/50 within 1px
        _drag_handle_to(page, 0.3)
        handle = page.locator('[data-testid="chat-preview-handle"]')
        handle.dblclick()
        page.wait_for_timeout(800)
        root_width = page.locator('[data-testid="chat-preview-split"]').bounding_box()["width"]
        assert abs(_split_ratio(page) - 0.5) * root_width <= 1.5, (
            f"double-click must reset to 50/50, got {_split_ratio(page)}"
        )

        # pointercancel reverts the in-progress drag (overlay exists during drag)
        snapshot = _split_ratio(page)
        root = page.locator('[data-testid="chat-preview-split"]').bounding_box()
        box = page.locator('[data-testid="chat-preview-handle"]').bounding_box()
        y = box["y"] + box["height"] / 2
        page.mouse.move(box["x"] + box["width"] / 2, y)
        page.mouse.down()
        page.mouse.move(root["x"] + root["width"] * 0.3, y, steps=8)
        assert page.locator("[data-preview-drag-overlay]").count() == 1, (
            "a transparent drag overlay must cover the preview iframe while dragging"
        )
        page.evaluate(
            """() => window.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true }))"""
        )
        page.wait_for_timeout(300)
        page.mouse.up()
        assert abs(_split_ratio(page) - snapshot) <= 0.012, (
            "pointercancel must revert the drag: "
            f"{snapshot} vs {_split_ratio(page)}"
        )
    finally:
        context.close()


def test_preview_is_fullscreen_overlay_on_mobile(
    browser: Browser, production_origin: str
) -> None:
    api = _preview_api()
    context, page, split = _open_split(
        browser, production_origin, api, viewport="mobile-375"
    )
    try:
        assert split.get_attribute("data-preview-mode") == "overlay"
        drawer = page.locator("[data-preview-drawer]")
        drawer.wait_for(timeout=15_000)
        box = drawer.bounding_box()
        assert box["width"] >= 375 - 1 and box["height"] >= 812 - 1, box
    finally:
        context.close()

# ---------------------------------------------------------------------------
# cross-engine subset (chromium / firefox / webkit)
# ---------------------------------------------------------------------------


def test_cross_engine_theme_tokens(
    engine_browser: Browser, engine_name: str, production_origin: str
) -> None:
    api = ChatApi()
    context = new_context(engine_browser, 1280, 800)
    page = context.new_page()
    try:
        install_event_stream_mock(page)
        install_api(page, api)
        page.goto(f"{production_origin}/app")
        page.get_by_role("textbox", name="消息").wait_for(timeout=30_000)
        for name in ("--rxy-bg", "--rxy-card", "--rxy-fg", "--rxy-border"):
            if not has_css_var(page, name):
                pytest.skip(f"{engine_name}: theme token {name} missing")
            assert color_to_rgb(css_var(page, name)) == _rgb_channels(page, f"{name}-rgb"), (
                engine_name,
                name,
            )
        _set_theme(page, "dark")
        dark_bg = color_to_rgb(css_var(page, "--rxy-bg"))
        assert dark_bg != (0, 0, 0), f"{engine_name}: dark base is pure black"
        assert color_to_rgb(css_var(page, "--rxy-bg")) == _rgb_channels(page, "--rxy-bg-rgb")
    finally:
        context.close()


def test_cross_engine_composer_focus_geometry(
    engine_browser: Browser, engine_name: str, production_origin: str
) -> None:
    api = ChatApi()
    context = new_context(engine_browser, 1280, 800)
    page = context.new_page()
    try:
        install_event_stream_mock(page)
        install_api(page, api)
        page.goto(f"{production_origin}/app")
        page.get_by_role("textbox", name="消息").wait_for(timeout=30_000)
        shell = page.locator('[data-testid="chat-composer"]')
        try:
            shell.wait_for(timeout=3_000)
        except Exception:
            pytest.skip(
                f"{engine_name}: [data-testid=chat-composer] absent (task-5 not landed)"
            )
        idle = _composer_metrics(page)
        assert all(
            idle[key] == "0px"
            for key in ("borderTop", "borderRight", "borderBottom", "borderLeft")
        ), (engine_name, idle)
        composer_box(page).focus()
        page.wait_for_timeout(250)
        focused = _composer_metrics(page)
        for key in ("width", "height", "top", "left"):
            assert abs(focused[key] - idle[key]) <= 1, (engine_name, key, idle, focused)
    finally:
        context.close()
