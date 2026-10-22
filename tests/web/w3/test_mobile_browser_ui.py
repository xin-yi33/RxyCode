"""Mobile browser UI coverage for the public shell and controlled BYOK views.

The authenticated-looking test state below is synthetic and API-stubbed. It is
not a real account, and every non-GET request is blocked. The standalone live
smoke mode starts only empty-cookie visitor contexts and never submits forms.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"


def _json(route, status: int, payload: object) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


def _models(count: int = 32) -> list[dict[str, object]]:
    return [
        {
            "model_ref": f"m_mobile_{index}",
            "model_id": f"mobile-model-{index:02d}",
            "display_name": f"移动测试模型 {index:02d}",
            "provider_id": "provider-test",
            "provider_name": "测试服务商",
            "connection_id": "conn-mobile-test",
            "connection_name": "测试连接",
            "source": "byok",
            "status": "available",
        }
        for index in range(count)
    ]


def _install_api(
    page: Page,
    *,
    authenticated: bool,
    blocked: list[str],
    model_payload: dict[str, Any] | None = None,
) -> None:
    """Stub app APIs and make all state-changing requests fail closed."""
    me = {
        "user": {
            "id": "user-ui-fixture",
            "kind": "password",
            "email": "synthetic-ui@example.invalid",
            "display_name": "Synthetic UI fixture",
            "github_id": None,
        },
        "organization": {"id": "org-ui-fixture", "tenant_id": "tenant-ui-fixture"},
        "membership": {"role": "owner"},
        "default_project_id": None,
    }
    sessions = [
        {
            "id": f"session-fixture-{index:02d}",
            "title": f"测试会话 {index:02d}",
            "project_id": "project-ui-fixture",
            "updated_at": None,
            "last_run": None,
        }
        for index in range(36)
    ]
    connection = {
        "id": "conn-mobile-test",
        "provider_id": "provider-test",
        "provider_name": "测试服务商",
        "display_name": "合成 BYOK 连接",
        "base_url": "https://api.example.invalid/v1",
        "api_transport": "openai_compat",
        "has_key": True,
        "credential_version": 1,
        "state": "active",
        "test_status": "untested",
        "test_error": None,
        "tested_at": None,
        "updated_at": None,
        "model_count": 32,
    }
    providers = {
        "providers": [
            {
                "id": "provider-test",
                "name": "测试服务商预设",
                "base_url": "https://preset.example.invalid/v1",
            }
        ]
    }

    def handle(route) -> None:
        request = route.request
        method = request.method.upper()
        path = urlparse(request.url).path
        if method not in {"GET", "HEAD"}:
            blocked.append(f"{method} {path}")
            route.abort()
            return
        if path == "/api/v1/me":
            _json(route, 200, me) if authenticated else _json(
                route, 401, {"detail": "UNAUTHORIZED"}
            )
        elif path == "/api/v1/me/preferences":
            _json(
                route,
                200,
                {
                    "revision": 1,
                    "locale": "auto",
                    "sidebar": {"grouping": "merged", "sort": "updated_at", "show_projects": True},
                    "appearance": {
                        "mode": "light",
                        "separate_modes": False,
                        "shared": {},
                        "light": None,
                        "dark": None,
                        "reduced_motion": "system",
                        "diff_markers": "color",
                    },
                },
            )
        elif path == "/api/v1/sessions":
            _json(route, 200, {"sessions": sessions if authenticated else []})
        elif path == "/api/v1/auth/device":
            _json(route, 200, {"status": "active"})
        elif path == "/api/v1/models/access":
            _json(
                route,
                200,
                {
                    "require_byok": False,
                    "platform_allowed": True,
                    "byok_available": True,
                    "default_model_ref": "m_mobile_00",
                },
            )
        elif path == "/api/v1/models/providers":
            _json(route, 200, providers)
        elif path == "/api/v1/model-connections":
            _json(route, 200, {"connections": [connection]})
        elif path == "/api/v1/models":
            _json(
                route,
                200,
                model_payload
                or {"models": _models(), "default_model_ref": "m_mobile_00"},
            )
        elif path == "/api/v1/auth/capabilities":
            _json(
                route,
                200,
                {
                    "mode": "password",
                    "password": True,
                    "registration": "open",
                    "github": False,
                    "local": False,
                    "captcha": None,
                    "code_delivery": "none",
                },
            )
        else:
            _json(route, 200, {})

    page.route("**/api/v1/**", handle)


def _new_mobile_context(browser: Browser, width: int, height: int):
    # Always make a fresh context: no persistent profile, CDP session, or cookies.
    return browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )


def _assert_mobile_control_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const viewport = window.visualViewport;
          const vv = viewport
            ? {top: viewport.offsetTop, left: viewport.offsetLeft,
               width: viewport.width, height: viewport.height}
            : {top: 0, left: 0, width: innerWidth, height: innerHeight};
          const composer = document.querySelector('[aria-label="消息"]');
          const send = document.querySelector('[aria-label="发送"]');
          const rect = (node) => {
            if (!node) return null;
            const r = node.getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                    width: r.width, height: r.height};
          };
          return {
            vv,
            composerFont: composer ? parseFloat(getComputedStyle(composer).fontSize) : 0,
            composerHeight: composer ? composer.getBoundingClientRect().height : 0,
            send: rect(send),
            documentWidth: document.documentElement.scrollWidth,
            windowWidth: innerWidth,
          };
        }"""
    )


def _assert_no_horizontal_overflow(page: Page) -> None:
    widths = page.evaluate(
        "() => ({document: document.documentElement.scrollWidth, window: innerWidth})"
    )
    assert widths["document"] <= widths["window"] + 1, widths


@pytest.fixture(scope="session")
def production_origin():
    """Build and serve the production bundle only when this test module is selected."""
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        pytest.skip("Node.js and installed apps/web Vite dependencies are required")

    subprocess.run(
        [node, str(vite), "build"],
        cwd=WEB,
        check=True,
        timeout=240,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [node, str(vite), "preview", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Vite preview exited with {server.returncode}")
            try:
                with urlopen(origin, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite production preview did not become ready in 40 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


# Function scope on purpose: a session-scoped ``sync_playwright`` stays open
# for the whole run and makes every later ``with sync_playwright()`` in the
# same worker raise "Sync API inside the asyncio loop".
@pytest.fixture
def browser() -> Browser:
    executable = os.environ.get("RXY_MOBILE_CHROMIUM")
    if executable and not Path(executable).is_file():
        pytest.fail(f"RXY_MOBILE_CHROMIUM does not exist: {executable}")
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(
                headless=True,
                executable_path=executable or None,
            )
        except Exception as exc:
            pytest.skip(f"Chromium could not launch ({exc}); set RXY_MOBILE_CHROMIUM")
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def screenshot_dir() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="rxy-mobile-ui-pytest-"))
    print(f"Mobile UI screenshots: {folder}")
    return folder


def test_guest_composer_sidebar_keyboard_and_resize(
    browser: Browser, production_origin: str, screenshot_dir: Path
) -> None:
    blocked: list[str] = []
    context = _new_mobile_context(browser, 320, 640)
    page = context.new_page()
    _install_api(page, authenticated=False, blocked=blocked)
    page.goto(f"{production_origin}/app", wait_until="networkidle")
    composer = page.get_by_role("textbox", name="消息")
    expect(composer).to_be_visible()

    metrics = _assert_mobile_control_metrics(page)
    assert metrics["composerFont"] >= 16, metrics
    assert metrics["composerHeight"] >= 44, metrics
    assert metrics["send"]["height"] >= 44, metrics
    assert metrics["send"]["bottom"] <= metrics["vv"]["top"] + metrics["vv"]["height"] + 1
    _assert_no_horizontal_overflow(page)
    page.screenshot(path=str(screenshot_dir / "guest-composer-320x640.png"), full_page=True)

    composer.fill("draft survives resize")
    page.set_viewport_size({"width": 667, "height": 375})
    expect(composer).to_have_value("draft survives resize")
    composer.press("Shift+Enter")
    assert composer.input_value() == "draft survives resize\n"
    composer.evaluate(
        "node => node.dispatchEvent(new KeyboardEvent('keydown', "
        "{key:'Enter', bubbles:true, cancelable:true, isComposing:true}))"
    )
    assert composer.input_value() == "draft survives resize\n"
    page.evaluate(
        """() => {
          const vv = window.visualViewport;
          Object.defineProperty(vv, 'height', {configurable:true, value:250});
          Object.defineProperty(vv, 'offsetTop', {configurable:true, value:12});
          vv.dispatchEvent(new Event('resize'));
        }"""
    )
    page.wait_for_function(
        "getComputedStyle(document.documentElement).getPropertyValue('--rxy-viewport-height').trim() === '250px'"
    )
    keyboard_metrics = _assert_mobile_control_metrics(page)
    assert keyboard_metrics["send"]["top"] >= keyboard_metrics["vv"]["top"] - 1
    assert keyboard_metrics["send"]["bottom"] <= (
        keyboard_metrics["vv"]["top"] + keyboard_metrics["vv"]["height"] + 1
    ), keyboard_metrics
    assert blocked == [], f"Keyboard interaction attempted a write: {blocked}"

    opener = page.get_by_role("button", name="打开会话列表")
    opener.click()
    drawer = page.get_by_role("dialog", name="会话列表")
    expect(drawer).to_be_visible()
    nav = drawer.get_by_role("navigation")
    expect(nav).to_be_visible()
    # Guests intentionally see only a sign-in prompt (sessions are
    # auth-gated), so the list can never overflow here — assert the scroll
    # contract structurally instead of requiring actual overflow.
    assert nav.evaluate("node => getComputedStyle(node).overflowY") == "auto"
    assert page.locator("body").evaluate("node => getComputedStyle(node).overflow") == "hidden"
    page.screenshot(path=str(screenshot_dir / "guest-drawer-667x375.png"), full_page=True)
    drawer.get_by_role("button", name="关闭会话列表").click()
    expect(drawer).to_have_count(0)
    expect(opener).to_be_focused()
    assert page.locator("body").evaluate("node => getComputedStyle(node).overflow") != "hidden"
    _assert_no_horizontal_overflow(page)
    assert blocked == [], f"Guest UI attempted a write: {blocked}"
    print(f"Guest keyboard/drawer screenshots: {screenshot_dir}")
    context.close()


def test_model_picker_and_byok_modal_fit_phone_and_landscape(
    browser: Browser, production_origin: str, screenshot_dir: Path
) -> None:
    blocked: list[str] = []
    context = _new_mobile_context(browser, 320, 640)
    page = context.new_page()
    _install_api(page, authenticated=True, blocked=blocked)
    page.goto(f"{production_origin}/app", wait_until="networkidle")
    expect(page.get_by_role("button", name="选择模型", exact=False)).to_be_visible()

    page.get_by_role("button", name="选择模型", exact=False).click()
    menu = page.get_by_role("dialog", name="选择模型")
    expect(menu).to_be_visible()
    page.get_by_role("textbox", name="搜索模型").wait_for(state="visible")
    menu_bounds = menu.evaluate(
        "node => {const r=node.getBoundingClientRect(), v=visualViewport; "
        "return {top:r.top,bottom:r.bottom,height:r.height,vtop:v.offsetTop,vbottom:v.offsetTop+v.height}}"
    )
    assert menu_bounds["top"] >= menu_bounds["vtop"] - 1, menu_bounds
    assert menu_bounds["bottom"] <= menu_bounds["vbottom"] + 1, menu_bounds
    listbox = menu.get_by_role("listbox", name="可用模型")
    assert listbox.evaluate("node => node.scrollHeight > node.clientHeight")
    search = page.get_by_role("textbox", name="搜索模型")
    assert search.evaluate("node => parseFloat(getComputedStyle(node).fontSize)") >= 16
    assert search.evaluate("node => node.getBoundingClientRect().height") >= 44
    _assert_no_horizontal_overflow(page)
    page.screenshot(path=str(screenshot_dir / "model-picker-320x640.png"), full_page=True)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    page.goto(f"{production_origin}/app/settings?section=models", wait_until="networkidle")
    expect(page.get_by_text("模型连接", exact=True)).to_be_visible()
    expect(page.get_by_text("模型目录", exact=True)).to_be_visible()
    confirm_label = page.locator(".rxy-billable-confirm").first
    assert confirm_label.evaluate("node => node.getBoundingClientRect().height") >= 44
    native_checkbox = confirm_label.locator('input[type="checkbox"]')
    assert native_checkbox.evaluate(
        "node => node.getBoundingClientRect().width === 20 && node.getBoundingClientRect().height === 20"
    )
    page.set_viewport_size({"width": 667, "height": 375})
    _assert_no_horizontal_overflow(page)
    page.screenshot(path=str(screenshot_dir / "settings-models-landscape-667x375.png"), full_page=True)

    page.get_by_role("button", name="添加连接").click()
    dialog = page.get_by_role("dialog", name="添加连接")
    expect(dialog).to_be_visible()
    dialog.get_by_label("服务商").select_option(label="自定义服务商")

    # Model forms are shown only with synthetic API responses; no real login/key is used.
    for label in ("Base URL", "服务商名称（可选）", "显示名称（可选）"):
        field = dialog.get_by_label(label)
        assert field.evaluate("node => parseFloat(getComputedStyle(node).fontSize)") >= 16, label
        assert field.evaluate("node => node.getBoundingClientRect().height") >= 44, label
    api_key = dialog.locator('input[name="api-key"]')
    assert api_key.evaluate("node => parseFloat(getComputedStyle(node).fontSize)") >= 16
    assert api_key.evaluate("node => node.getBoundingClientRect().height") >= 44
    toggle = dialog.get_by_role("button", name="显示 API Key")
    assert toggle.evaluate("node => node.getBoundingClientRect().height") >= 44
    dialog_button_heights = dialog.locator("button").evaluate_all(
        "nodes => nodes.map(node => node.getBoundingClientRect().height)"
    )
    assert dialog_button_heights and min(dialog_button_heights) >= 44, dialog_button_heights

    dialog_bounds = dialog.evaluate(
        "node => {const r=node.getBoundingClientRect(), v=visualViewport; "
        "return {top:r.top,bottom:r.bottom,height:r.height,vtop:v.offsetTop,vbottom:v.offsetTop+v.height}}"
    )
    assert dialog_bounds["top"] >= dialog_bounds["vtop"] - 1, dialog_bounds
    assert dialog_bounds["bottom"] <= dialog_bounds["vbottom"] + 1, dialog_bounds
    assert dialog.evaluate("node => node.scrollHeight > node.clientHeight")
    page.screenshot(path=str(screenshot_dir / "byok-custom-form-landscape.png"), full_page=True)

    # Simulate the reduced VisualViewport reported by a soft keyboard; this validates
    # our viewport hook/layout response without claiming to emulate a real OS keyboard.
    api_key.focus()
    page.evaluate(
        """() => {
          const vv = window.visualViewport;
          Object.defineProperty(vv, 'height', {configurable:true, value:230});
          Object.defineProperty(vv, 'offsetTop', {configurable:true, value:12});
          vv.dispatchEvent(new Event('resize'));
        }"""
    )
    page.wait_for_function(
        "getComputedStyle(document.documentElement).getPropertyValue('--rxy-viewport-height').trim() === '230px'"
    )
    keyboard_bounds = dialog.evaluate(
        "node => {const r=node.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height}}"
    )
    assert keyboard_bounds["top"] >= 12, keyboard_bounds
    assert keyboard_bounds["bottom"] <= 242, keyboard_bounds
    assert keyboard_bounds["height"] <= 214, keyboard_bounds
    focused_key_bounds = api_key.evaluate(
        "node => {const r=node.getBoundingClientRect(), d=node.closest('dialog').getBoundingClientRect(); "
        "return {top:r.top,bottom:r.bottom,dialogTop:d.top,dialogBottom:d.bottom}}"
    )
    assert focused_key_bounds["top"] >= focused_key_bounds["dialogTop"] - 1, focused_key_bounds
    assert focused_key_bounds["bottom"] <= focused_key_bounds["dialogBottom"] + 1, focused_key_bounds
    page.screenshot(path=str(screenshot_dir / "byok-custom-form-short-vv.png"), full_page=True)

    save_button = dialog.get_by_role("button", name="保存连接")
    save_button.focus()
    save_bounds = save_button.evaluate(
        "node => {const r=node.getBoundingClientRect(), d=node.closest('dialog').getBoundingClientRect(); "
        "return {top:r.top,bottom:r.bottom,dialogTop:d.top,dialogBottom:d.bottom}}"
    )
    assert save_bounds["top"] >= save_bounds["dialogTop"] - 1, save_bounds
    assert save_bounds["bottom"] <= save_bounds["dialogBottom"] + 1, save_bounds
    page.screenshot(path=str(screenshot_dir / "byok-custom-form-short-vv-save.png"), full_page=True)

    assert blocked == [], f"Synthetic UI test attempted a write: {blocked}"
    print(f"Synthetic account/BYOK UI screenshots (not a real account): {screenshot_dir}")
    context.close()


def test_model_picker_hides_platform_and_keeps_duplicate_refs_distinct(
    browser: Browser, production_origin: str, screenshot_dir: Path
) -> None:
    blocked: list[str] = []
    long_provider = "synthetic-provider-name-that-must-only-be-searchable-" * 3
    long_model = "Synthetic shared model display name that is intentionally very long " * 2
    model_payload = {
        "models": [
            {
                "model_ref": "byok-ref-a",
                "model_id": "synthetic-shared-id",
                "display_name": long_model,
                "provider_id": "provider-a",
                "provider_name": long_provider,
                "connection_id": "conn-mobile-test",
                "connection_name": "synthetic-connection-a",
                "source": "byok",
                "status": "available",
            },
            {
                "model_ref": "byok-ref-b",
                "model_id": "synthetic-shared-id",
                "display_name": long_model,
                "provider_id": "provider-b",
                "provider_name": "another-synthetic-provider-that-must-not-render-" * 2,
                "connection_id": "conn-mobile-test",
                "connection_name": "synthetic-connection-b",
                "source": "byok",
                "status": "available",
            },
            {
                "model_ref": "legacy-platform-ref",
                "model_id": "synthetic-platform-id",
                "display_name": "SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR",
                "provider_id": "platform",
                "provider_name": "平台额度",
                "connection_id": "platform",
                "connection_name": "平台额度",
                "source": "platform",
                "status": "available",
            },
        ],
        "default_model_ref": "legacy-platform-ref",
    }

    context = browser.new_context(
        viewport={"width": 320, "height": 640},
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    _install_api(
        page,
        authenticated=True,
        blocked=blocked,
        model_payload=model_payload,
    )

    page.goto(f"{production_origin}/app", wait_until="networkidle")
    # A stale platform default is ignored as a selection; Composer still refuses to send until BYOK is chosen.
    picker = page.get_by_role("button", name="选择模型")
    expect(picker).to_be_visible()
    composer = page.get_by_role("textbox", name="消息")
    composer.fill("synthetic request guard check")
    page.get_by_role("button", name="发送").click()
    expect(page.get_by_role("alert")).to_contain_text("重新选择自有模型")
    assert blocked == [], "legacy platform default must not issue any task request"

    picker.click()
    menu = page.get_by_role("dialog", name="选择模型")
    options = menu.get_by_role("option")
    expect(options).to_have_count(2)
    menu_text = menu.inner_text()
    assert long_provider not in menu_text
    assert "another-synthetic-provider" not in menu_text
    assert "synthetic-shared-id" not in menu_text
    assert "SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR" not in menu_text
    menu_bounds = menu.evaluate(
        "node => {const r=node.getBoundingClientRect(); return {left:r.left,right:r.right,width:r.width}}"
    )
    assert menu_bounds["left"] >= -1 and menu_bounds["right"] <= 321, menu_bounds
    page.screenshot(path=str(screenshot_dir / "model-picker-synthetic-320x640.png"), full_page=True)
    _assert_no_horizontal_overflow(page)

    search = page.get_by_role("textbox", name="搜索模型")
    search.fill("synthetic-provider-name-that-must-only-be-searchable")
    expect(menu.get_by_role("option")).to_have_count(1)
    expect(menu).not_to_contain_text(long_provider)
    search.fill("")
    menu.get_by_role("option").nth(1).click()
    picker = page.get_by_role("button", name=f"选择模型：{long_model}")
    expect(picker).to_be_visible()
    assert long_provider not in picker.get_attribute("aria-label")
    picker.click()
    expect(menu.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
    expect(menu.get_by_role("option").nth(0)).to_have_attribute("aria-selected", "false")
    assert menu.get_by_role("option").nth(1).get_attribute("id") == "model-opt-byok-ref-b"
    assert "synthetic-shared-id" not in menu.inner_text()
    page.keyboard.press("Escape")

    assert blocked == [], f"Synthetic picker test attempted an unexpected write: {blocked}"

    page.goto(f"{production_origin}/app/settings?section=models", wait_until="networkidle")
    expect(page.get_by_text("模型目录", exact=True)).to_be_visible()
    expect(page.get_by_text("SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR")).to_have_count(0)
    expect(page.get_by_text("平台额度")).to_have_count(0)
    assert "可先使用平台模型" not in page.locator("body").inner_text()
    context.close()


def test_mobile_auth_layout_keeps_fields_accessible(
    browser: Browser, production_origin: str, screenshot_dir: Path
) -> None:
    blocked: list[str] = []
    context = _new_mobile_context(browser, 320, 568)
    page = context.new_page()
    _install_api(page, authenticated=False, blocked=blocked)
    page.goto(f"{production_origin}/login", wait_until="networkidle")
    expect(page.locator(".rxy-auth-layout")).to_be_visible()
    page.screenshot(path=str(screenshot_dir / "login-320x568.png"), full_page=True)
    fields = page.locator(".rxy-auth-layout input:not([type=checkbox]):not([type=radio])")
    if fields.count():
        assert fields.first.evaluate("node => parseFloat(getComputedStyle(node).fontSize)") >= 16
        assert fields.first.evaluate("node => node.getBoundingClientRect().height") >= 44
    _assert_no_horizontal_overflow(page)
    assert blocked == [], f"Auth layout check attempted a write: {blocked}"
    context.close()


def _public_live_smoke(
    live_origin: str,
    browser_path: str | None,
    screenshot_dir: Path,
) -> list[Path]:
    if browser_path and not Path(browser_path).is_file():
        raise FileNotFoundError(f"Chromium executable not found: {browser_path}")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    blocked: list[str] = []
    blocked_telemetry: list[str] = []
    screenshots: list[Path] = []
    live_url = urlparse(live_origin)

    def same_live_origin(request_url) -> bool:
        def effective_port(parsed) -> int | None:
            if parsed.port is not None:
                return parsed.port
            return {"http": 80, "https": 443}.get(parsed.scheme.lower())

        return (
            request_url.scheme.lower() == live_url.scheme.lower()
            and (request_url.hostname or "").lower() == (live_url.hostname or "").lower()
            and effective_port(request_url) == effective_port(live_url)
        )

    def guard_non_get(route) -> None:
        request = route.request
        method = request.method.upper()
        parsed = urlparse(request.url)
        if (
            method == "POST"
            and same_live_origin(parsed)
            and parsed.path == "/cdn-cgi/rum"
        ):
            blocked_telemetry.append(request.url)
            route.abort()
            return
        if method not in {"GET", "HEAD"}:
            blocked.append(f"{method} {request.url}")
            route.abort()
            return
        route.continue_()

    def wait_for_theme_colors(page: Page, expected_theme: str) -> dict[str, str]:
        page.wait_for_function(
            """(expectedTheme) => {
              const root = document.documentElement;
              const textarea = document.querySelector('textarea[aria-label="消息"]');
              const card = textarea?.closest('.bg-card');
              const topbar = document.querySelector('.rxy-app-topbar');
              const toggle = topbar?.querySelector('button[aria-label^="切换到"]');
              if (root.dataset.theme !== expectedTheme || !textarea || !card || !topbar || !toggle) return false;
              const colorProperties = new Set(['background-color', 'color', 'border-color']);
              const targets = [topbar, toggle, card, textarea];
              return targets.every((target) => target.getAnimations()
                .filter((animation) => colorProperties.has(animation.transitionProperty))
                .every((animation) => animation.playState === 'finished'));
            }""",
            arg=expected_theme,
            timeout=10000,
        )
        colors = page.evaluate(
            """() => {
              const root = document.documentElement;
              const textarea = document.querySelector('textarea[aria-label="消息"]');
              const card = textarea.closest('.bg-card');
              const topbar = document.querySelector('.rxy-app-topbar');
              const resolve = (variable) => {
                const probe = document.createElement('span');
                probe.style.color = `var(${variable})`;
                document.body.append(probe);
                const color = getComputedStyle(probe).color;
                probe.remove();
                return color;
              };
              return {
                theme: root.dataset.theme,
                topbarBackground: getComputedStyle(topbar).backgroundColor,
                expectedBackground: resolve('--rxy-bg'),
                cardBackground: getComputedStyle(card).backgroundColor,
                expectedCard: resolve('--rxy-card'),
                composerText: getComputedStyle(textarea).color,
                expectedText: resolve('--rxy-fg'),
              };
            }"""
        )
        assert colors["theme"] == expected_theme, colors
        assert colors["topbarBackground"] == colors["expectedBackground"], colors
        assert colors["cardBackground"] == colors["expectedCard"], colors
        assert colors["composerText"] == colors["expectedText"], colors
        return colors

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path or None)
        try:
            print(f"Isolated browser: Chromium {browser.version}; live smoke is guest/read-only only.")
            for width, height, suffix in (
                (320, 640, "320x640"),
                (667, 375, "667x375-landscape"),
            ):
                # A brand-new context per viewport guarantees no user profile/session leakage.
                context = _new_mobile_context(browser, width, height)
                page = context.new_page()
                page.route("**/*", guard_non_get)
                page.goto(f"{live_origin.rstrip('/')}/app", wait_until="domcontentloaded", timeout=45000)
                page.get_by_role("textbox", name="消息").wait_for(state="visible", timeout=30000)
                initial_theme = wait_for_theme_colors(page, "light")
                page.screenshot(path=str(screenshot_dir / f"public-guest-app-{suffix}.png"), full_page=True)
                screenshots.append(screenshot_dir / f"public-guest-app-{suffix}.png")

                theme_button = page.get_by_role("button", name="切换到深色")
                theme_button.click()
                dark_theme = wait_for_theme_colors(page, "dark")
                assert dark_theme["cardBackground"] != initial_theme["cardBackground"], dark_theme
                page.screenshot(
                    path=str(screenshot_dir / f"public-guest-theme-dark-{suffix}.png"),
                    full_page=True,
                )
                screenshots.append(screenshot_dir / f"public-guest-theme-dark-{suffix}.png")

                page.get_by_role("button", name="切换到浅色").click()
                restored_theme = wait_for_theme_colors(page, "light")
                assert restored_theme["cardBackground"] == initial_theme["cardBackground"], restored_theme
                page.screenshot(
                    path=str(screenshot_dir / f"public-guest-theme-restored-{suffix}.png"),
                    full_page=True,
                )
                screenshots.append(screenshot_dir / f"public-guest-theme-restored-{suffix}.png")

                page.get_by_role("button", name="打开会话列表").click()
                drawer = page.get_by_role("dialog", name="会话列表")
                expect(drawer).to_be_visible()
                drawer_handle = drawer.element_handle()
                assert drawer_handle is not None
                page.wait_for_function(
                    """(drawer) => {
                      const transform = getComputedStyle(drawer).transform;
                      let translateX = 0;
                      if (transform !== 'none') {
                        const values = transform.slice(transform.indexOf('(') + 1, -1).split(',').map(Number);
                        translateX = transform.startsWith('matrix3d(') ? values[12] : values[4];
                      }
                      return Math.abs(drawer.getBoundingClientRect().left) <= 1 &&
                        Number.isFinite(translateX) && Math.abs(translateX) <= 1;
                    }""",
                    arg=drawer_handle,
                    timeout=30000,
                )
                page.screenshot(path=str(screenshot_dir / f"public-guest-drawer-{suffix}.png"), full_page=True)
                screenshots.append(screenshot_dir / f"public-guest-drawer-{suffix}.png")
                drawer.get_by_role("button", name="关闭会话列表").click()
                expect(page.get_by_role("button", name="打开会话列表")).to_be_focused()
                context.close()

                # Keep the login view in a second clean context as well; never carry
                # cookies/storage set by the public shell into another route check.
                login_context = _new_mobile_context(browser, width, height)
                login_page = login_context.new_page()
                login_page.route("**/*", guard_non_get)
                with login_page.expect_response(
                    lambda response: urlparse(response.url).path == "/api/v1/auth/capabilities",
                    timeout=30000,
                ) as capabilities_response:
                    login_page.goto(
                        f"{live_origin.rstrip('/')}/login",
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                response = capabilities_response.value
                assert response.status == 200, f"Capabilities request returned HTTP {response.status}"
                capabilities = response.json()
                login_page.locator(".rxy-auth-layout").wait_for(state="visible", timeout=30000)
                login_page.get_by_text(
                    "正在确认验证码配置，请稍候。", exact=True
                ).wait_for(state="detached", timeout=10000)
                assert login_page.get_by_text(
                    "无法确认验证码配置，请检查网络后重试。", exact=True
                ).count() == 0, "Capabilities query did not reach a usable state"
                if capabilities.get("captcha") == "altcha":
                    login_page.get_by_text("验证通过", exact=True).wait_for(
                        state="visible", timeout=90000
                    )
                login_page.screenshot(
                    path=str(screenshot_dir / f"public-login-{suffix}.png"),
                    full_page=True,
                )
                screenshots.append(screenshot_dir / f"public-login-{suffix}.png")
                login_context.close()
        finally:
            browser.close()

    if blocked:
        raise AssertionError(f"Public visitor smoke blocked attempted non-read-only requests: {blocked}")
    if blocked_telemetry:
        print(f"Aborted same-origin Cloudflare RUM telemetry POSTs (not business writes): {blocked_telemetry}")
    return screenshots


def _model_picker_live_smoke(
    live_origin: str,
    browser_path: str | None,
    screenshot_dir: Path,
) -> list[Path]:
    """Exercise deployed static files with synthetic auth/catalog and no writes."""
    if browser_path and not Path(browser_path).is_file():
        raise FileNotFoundError(f"Chromium executable not found: {browser_path}")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "models": [
            {
                "model_ref": "live-synthetic-byok-a",
                "model_id": "live-synthetic-shared-id",
                "display_name": "Synthetic shared model name intentionally long for truncation " * 2,
                "provider_id": "live-synthetic-provider-a",
                "provider_name": "live-synthetic-provider-searchable-" * 3,
                "connection_id": "live-synthetic-connection-a",
                "connection_name": "Synthetic connection A",
                "source": "byok",
                "status": "available",
            },
            {
                "model_ref": "live-synthetic-byok-b",
                "model_id": "live-synthetic-shared-id",
                "display_name": "Synthetic shared model name intentionally long for truncation " * 2,
                "provider_id": "live-synthetic-provider-b",
                "provider_name": "another-live-synthetic-provider-searchable-" * 2,
                "connection_id": "live-synthetic-connection-b",
                "connection_name": "Synthetic connection B",
                "source": "byok",
                "status": "available",
            },
            {
                "model_ref": "live-synthetic-legacy-platform",
                "model_id": "SYNTHETIC_PLATFORM_ID",
                "display_name": "SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR",
                "provider_id": "platform",
                "provider_name": "平台额度",
                "connection_id": "platform",
                "connection_name": "平台额度",
                "source": "platform",
                "status": "available",
            },
        ],
        "default_model_ref": "live-synthetic-legacy-platform",
    }
    blocked: list[str] = []
    blocked_telemetry: list[str] = []
    screenshots: list[Path] = []
    live_url = urlparse(live_origin)

    def same_live_origin(request_url) -> bool:
        def effective_port(parsed) -> int | None:
            if parsed.port is not None:
                return parsed.port

            return {"http": 80, "https": 443}.get(parsed.scheme.lower())

        return (
            request_url.scheme.lower() == live_url.scheme.lower()
            and (request_url.hostname or "").lower() == (live_url.hostname or "").lower()
            and effective_port(request_url) == effective_port(live_url)
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path or None)
        try:
            for width, height, suffix in (
                (320, 640, "320x640"),
                (667, 375, "667x375-landscape"),
            ):
                context = _new_mobile_context(browser, width, height)
                page = context.new_page()

                def guard_non_get(route) -> None:
                    request = route.request
                    method = request.method.upper()
                    parsed = urlparse(request.url)
                    if (
                        method == "POST"
                        and same_live_origin(parsed)
                        and parsed.path == "/cdn-cgi/rum"
                    ):
                        blocked_telemetry.append(request.url)
                        route.abort()
                    elif method not in {"GET", "HEAD"}:
                        blocked.append(f"{method} {request.url}")
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", guard_non_get)
                _install_api(page, authenticated=True, blocked=blocked, model_payload=payload)
                page.goto(f"{live_origin.rstrip('/')}/app", wait_until="domcontentloaded", timeout=45000)
                page.get_by_role("textbox", name="消息").wait_for(state="visible", timeout=30000)
                picker = page.get_by_role("button", name="选择模型")
                expect(picker).to_be_visible()
                page.get_by_role("textbox", name="消息").fill("synthetic live smoke")
                page.get_by_role("button", name="发送").click()
                expect(page.get_by_role("alert")).to_contain_text("重新选择自有模型")
                assert not any("POST "+f"{live_origin.rstrip('/')}/api/v1/tasks" in item for item in blocked)

                picker.click()
                menu = page.get_by_role("dialog", name="选择模型")
                expect(menu.get_by_role("option")).to_have_count(2)
                menu_text = menu.inner_text()
                assert "SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR" not in menu_text
                assert "live-synthetic-shared-id" not in menu_text
                assert "live-synthetic-provider-searchable" not in menu_text
                bounds = menu.evaluate(
                    "node => {const r=node.getBoundingClientRect(),v=visualViewport; "
                    "return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,"
                    "vleft:v.offsetLeft,vright:v.offsetLeft+v.width,vtop:v.offsetTop,"
                    "vbottom:v.offsetTop+v.height}}"
                )
                assert bounds["left"] >= bounds["vleft"] - 1
                assert bounds["right"] <= bounds["vright"] + 1
                assert bounds["top"] >= bounds["vtop"] - 1
                assert bounds["bottom"] <= bounds["vbottom"] + 1
                _assert_no_horizontal_overflow(page)
                screenshot = screenshot_dir / f"live-model-picker-{suffix}.png"
                page.screenshot(path=str(screenshot), full_page=True)
                screenshots.append(screenshot)

                page.goto(
                    f"{live_origin.rstrip('/')}/app/settings?section=models",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                page.get_by_text("模型目录", exact=True).wait_for(state="visible", timeout=30000)
                assert "SYNTHETIC_PLATFORM_MODEL_MUST_NOT_APPEAR" not in page.locator("body").inner_text()
                assert "可先使用平台模型" not in page.locator("body").inner_text()
                screenshot = screenshot_dir / f"live-model-settings-{suffix}.png"
                page.screenshot(path=str(screenshot), full_page=True)
                screenshots.append(screenshot)
                context.close()
        finally:
            browser.close()

    assert blocked == [], f"Live synthetic smoke attempted a network write: {blocked}"
    if blocked_telemetry:
        print(
            "Aborted same-origin Cloudflare RUM telemetry POSTs (not business writes): "
            f"{blocked_telemetry}"
        )
    return screenshots


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Public mobile UI smoke with isolated guest or synthetic model-picker mode."
    )
    parser.add_argument("--live-origin", required=True, help="Origin of the already deployed/running web UI")
    parser.add_argument("--browser-path", help="Optional standalone Chromium executable path")
    parser.add_argument(
        "--mode",
        choices=("guest", "model-picker"),
        default="guest",
        help="guest preserves the anonymous smoke; model-picker stubs /me and /models with synthetic data",
    )
    parser.add_argument(
        "--screenshot-dir",
        help="Output directory; defaults to a private OS temp directory outside the repository",
    )
    args = parser.parse_args()
    output = (
        Path(args.screenshot_dir).resolve()
        if args.screenshot_dir
        else Path(tempfile.mkdtemp(prefix="rxy-mobile-public-smoke-")).resolve()
    )
    shots = (
        _public_live_smoke(args.live_origin, args.browser_path, output)
        if args.mode == "guest"
        else _model_picker_live_smoke(args.live_origin, args.browser_path, output)
    )
    print(f"{args.mode} smoke passed. No account/email/model writes were allowed.")
    print(f"Screenshot directory: {output}")
    for shot in shots:
        print(shot)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
