"""Virtual browser: Playwright's own Chromium, not the user's Chrome.

Purpose: open an http(s) page, run its JS, then read title and links
(browser_navigate / browser_snapshot / browser_click). webfetch is a static
GET and does not do this. Computer Use (browser_open / browser_act) drives
the real desktop and stays a separate channel.

Packaging: ship the ``playwright`` Python package only. Do not put
chrome-headless-shell inside the NSIS or electron-builder payload. The
browser is a per-user cache (``%LOCALAPPDATA%\\ms-playwright`` on Windows),
downloaded once by ``python -m playwright install chromium`` the first time
the executable is missing. The tool is built in; the browser binary is not.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, register_tool_risk


_pw = None
_browser = None
_page = None


class NavigateArgs(BaseModel):
    url: str = Field(description="http(s) URL to open")


class SnapshotArgs(BaseModel):
    pass


class ClickArgs(BaseModel):
    text: str = Field(default="", description="Visible link or button text")
    selector: str = Field(default="", description="CSS selector, used when text is empty")


def _install_bundled_chromium() -> None:
    """Download Playwright's own Chromium into the user cache.

    Does not use system Chrome/Edge and does not write into the app installer.
    """
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "playwright install chromium failed")


# 废弃代码（2026-09-22）：缺 chrome-headless-shell 时改 channel=msedge/chrome。
# E2E 要测的是自带虚拟浏览器，不能拿系统浏览器冒充。
# attempts = ({}, {"channel": "msedge"}, {"channel": "chrome"})
def _launch_browser(playwright):
    """Launch Playwright's bundled Chromium only."""
    try:
        browser = playwright.chromium.launch(headless=True)
    except Exception as exc:
        text = str(exc)
        if "Executable doesn't exist" not in text and "playwright install" not in text:
            raise
        _install_bundled_chromium()
        browser = playwright.chromium.launch(headless=True)
    return browser


def _ensure_page():
    global _pw, _browser, _page
    if _page is not None:
        return _page, ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # The tool installs its own runtime. Do not tell the model to use bash.
        # 废弃代码（2026-09-22）：返回「请执行 playwright install chromium」，
        # 模型会去跑 bash，安静下载被 300s idle watchdog 杀掉。
        # return None, "[error: ... && playwright install chromium]"
        installed = _pip_install_playwright()
        if installed:
            return None, installed
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None, (
                "[error: virtual browser runtime is not installed in this interpreter. "
                "Retry browser_navigate. Do not use bash, where, or the playwright CLI.]"
            )
    try:
        _pw = sync_playwright().start()
        _browser = _launch_browser(_pw)
        _page = _browser.new_page()
    except Exception as exc:
        return None, (
            "[error: virtual browser failed to launch: "
            f"{type(exc).__name__}: {exc}. Retry browser_navigate. "
            "Do not use bash or where playwright.]"
        )
    return _page, ""


def _pip_install_playwright() -> str:
    """Install the Python package into this interpreter. Empty string on success."""
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "playwright"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return (
            "[error: virtual browser package install failed: "
            f"{detail or 'pip install playwright failed'}. "
            "Retry browser_navigate. Do not use bash.]"
        )
    return ""


def browser_navigate(url: str) -> str:
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        return "[error: browser_navigate requires an http(s) URL]"
    page, err = _ensure_page()
    if page is None:
        return err
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=20000)
    except Exception as exc:
        return f"[error: browser_navigate failed: {type(exc).__name__}: {exc}]"
    title = ""
    try:
        title = page.title()
    except Exception:
        title = ""
    return f"url={page.url}\ntitle={title}\nNext: call browser_snapshot. Do not wait for the window to close."


def browser_snapshot() -> str:
    page, err = _ensure_page()
    if page is None:
        return err
    try:
        title = page.title()
        url = page.url
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.slice(0, 30).map(a => ({text: (a.innerText || '').trim().slice(0, 80), href: a.href}))",
        )
    except Exception as exc:
        return f"[error: browser_snapshot failed: {type(exc).__name__}: {exc}]"
    lines = [f"url={url}", f"title={title}", "links:"]
    for item in links or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").replace("\n", " ")
        href = str(item.get("href") or "")
        if text or href:
            lines.append(f"- {text} {href}".rstrip())
    return "\n".join(lines)


def browser_click(text: str = "", selector: str = "") -> str:
    page, err = _ensure_page()
    if page is None:
        return err
    try:
        if text.strip():
            page.get_by_text(text.strip(), exact=False).first.click(timeout=8000)
        elif selector.strip():
            page.click(selector.strip(), timeout=8000)
        else:
            return "[error: browser_click requires text or selector]"
    except Exception as exc:
        return f"[error: browser_click failed: {type(exc).__name__}: {exc}]"
    return browser_snapshot()


browser_navigate_tool = StructuredTool.from_function(
    func=browser_navigate,
    name="browser_navigate",
    description=(
        "Open an http(s) URL in the built-in virtual browser. "
        "This tool launches Playwright Chromium itself and downloads it on first use. "
        "Do not run bash, where, or playwright install. "
        "Then call browser_snapshot. Do not use webfetch or browser_open as a substitute."
    ),
    args_schema=NavigateArgs,
)
browser_snapshot_tool = StructuredTool.from_function(
    func=browser_snapshot,
    name="browser_snapshot",
    description=(
        "Read the virtual browser page title and main links after browser_navigate. "
        "Do not use bash or webfetch for this."
    ),
    args_schema=SnapshotArgs,
)
browser_click_tool = StructuredTool.from_function(
    func=browser_click,
    name="browser_click",
    description="Click a link or control in the virtual browser by visible text or CSS selector.",
    args_schema=ClickArgs,
)

browser_navigate_tool.metadata = {"source": "virtual_browser"}
browser_snapshot_tool.metadata = {"source": "virtual_browser"}
browser_click_tool.metadata = {"source": "virtual_browser"}
register_tool_risk("browser_navigate", RiskLevel.READ)
register_tool_risk("browser_snapshot", RiskLevel.READ)
register_tool_risk("browser_click", RiskLevel.WRITE)
