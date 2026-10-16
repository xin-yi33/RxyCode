"""Isolated agent and preview browser contexts.

U24 tool names stay in tools/virtual_browser.py. Computer Use browser_open
stays in core/cu/browser.py. This module does not attach to the user's Chrome
and does not call webfetch.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SESSIONS: dict[str, "Session"] = {}
_PLAYWRIGHT: Any = None


@dataclass
class Session:
    session_id: str
    profile_dir: Path
    kind: str
    authorized: bool
    playwright: Any
    context: Any
    page: Any


def open_agent_context(*, profile_dir: str | Path, kind: str) -> dict[str, object]:
    """Open a persistent Chromium profile that is not the user's browser."""
    if kind not in {"agent", "preview"}:
        return _refused("profile kind must be agent or preview")
    target = Path(profile_dir)
    if _user_browser_dir(target):
        return _refused("user Chrome data is not shared")
    target.mkdir(parents=True, exist_ok=True)
    try:
        playwright, context, page = _launch(target)
    except Exception as exc:
        return _refused(f"browser launch failed: {type(exc).__name__}: {exc}")
    session_id = "br-" + uuid.uuid4().hex[:12]
    _SESSIONS[session_id] = Session(
        session_id=session_id,
        profile_dir=target,
        kind=kind,
        authorized=False,
        playwright=playwright,
        context=context,
        page=page,
    )
    return _view(
        _SESSIONS[session_id],
        status="open",
    )


def navigate_click(*, session_id: str, url: str, selector: str) -> dict[str, object]:
    """Open an http(s) URL and click. The DOM comes from that page."""
    session = _SESSIONS.get(session_id)
    if session is None:
        return _refused("unknown browser session")
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        return _refused("browser requires an http(s) URL")
    try:
        session.page.goto(target, wait_until="domcontentloaded", timeout=20000)
        session.page.click(selector, timeout=15000)
    except Exception as exc:
        return _refused(f"navigate/click failed: {type(exc).__name__}: {exc}")
    return _view(
        session,
        dom=session.page.content(),
        url=session.page.url,
        title=_title(session),
    )


def read_storage(*, session_id: str, key: str) -> dict[str, object]:
    session = _SESSIONS.get(session_id)
    if session is None:
        return _refused("unknown browser session")
    try:
        value = session.page.evaluate(
            "(name) => window.localStorage.getItem(name) || ''",
            key,
        )
    except Exception as exc:
        return _refused(f"storage read failed: {type(exc).__name__}: {exc}")
    return _view(session, value=value or "")


def request_user_cookies(*, authorized: bool, user_chrome_dir: str | Path) -> dict[str, object]:
    """Never read or copy the user's Chrome profile, authorized or not."""
    del authorized, user_chrome_dir
    return _refused("user Chrome data is not shared")


def authorize_handoff(*, session_id: str, authorized: bool) -> dict[str, object]:
    session = _SESSIONS.get(session_id)
    if session is None:
        return _refused("unknown browser session")
    if not authorized:
        session.authorized = False
        return _refused("handoff is not authorized")
    session.authorized = True
    return _view(session, status="authorized")


def continue_session(*, session_id: str) -> dict[str, object]:
    """Return the same agent page only after an explicit handoff."""
    session = _SESSIONS.get(session_id)
    if session is None:
        return _refused("unknown browser session")
    if not session.authorized:
        return _refused("handoff is not authorized")
    try:
        dom = session.page.content()
        url = session.page.url
        title = _title(session)
    except Exception as exc:
        return _refused(f"continue failed: {type(exc).__name__}: {exc}")
    return _view(session, dom=dom, url=url, title=title)


def snapshot(*, session_id: str) -> dict[str, object]:
    session = _SESSIONS.get(session_id)
    if session is None:
        return _refused("unknown browser session")
    try:
        dom = session.page.content()
        url = session.page.url
        title = _title(session)
    except Exception as exc:
        return _refused(f"snapshot failed: {type(exc).__name__}: {exc}")
    return _view(session, dom=dom, url=url, title=title)


def close_session(*, session_id: str) -> None:
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        return
    try:
        session.context.close()
    except Exception:
        pass
    _stop_driver_when_idle()


def _stop_driver_when_idle() -> None:
    global _PLAYWRIGHT
    if _SESSIONS or _PLAYWRIGHT is None:
        return
    try:
        _PLAYWRIGHT.stop()
    except Exception:
        pass
    _PLAYWRIGHT = None


def _launch(profile_dir: Path) -> tuple[Any, Any, Any]:
    """One sync driver can own several persistent profiles. A second driver fails."""
    global _PLAYWRIGHT
    from playwright.sync_api import sync_playwright

    created = _PLAYWRIGHT is None
    if _PLAYWRIGHT is None:
        _PLAYWRIGHT = sync_playwright().start()
    try:
        context = _start_context(_PLAYWRIGHT, profile_dir)
    except Exception:
        if created:
            _PLAYWRIGHT.stop()
            _PLAYWRIGHT = None
        raise
    page = context.pages[0] if context.pages else context.new_page()
    return _PLAYWRIGHT, context, page


def _start_context(playwright: Any, profile_dir: Path) -> Any:
    kwargs = {
        "headless": True,
        "viewport": {"width": 800, "height": 600},
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    try:
        return playwright.chromium.launch_persistent_context(str(profile_dir), **kwargs)
    except Exception as exc:
        text = str(exc)
        missing = "Executable doesn't exist" in text or "playwright install" in text
        if not missing:
            raise
        _install_chromium()
        return playwright.chromium.launch_persistent_context(str(profile_dir), **kwargs)


def _install_chromium() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "playwright install chromium failed")


def _user_browser_dir(path: Path) -> bool:
    text = str(path).replace("/", "\\").lower()
    if "user data" not in text:
        return False
    names = ("chrome", "edge", "chromium", "brave")
    return any(name in text for name in names)


def _title(session: Session) -> str:
    try:
        return session.page.title()
    except Exception:
        return ""


def _refused(reason: str) -> dict[str, object]:
    return {
        "status": "refused",
        "shared": False,
        "reason": reason,
        "session_id": "",
        "profile_dir": "",
        "profile_kind": "",
        "dom": "",
        "url": "",
        "title": "",
        "value": "",
    }


def _view(session: Session, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "status": "ok",
        "shared": False,
        "reason": "",
        "session_id": session.session_id,
        "profile_dir": str(session.profile_dir),
        "profile_kind": session.kind,
        "dom": "",
        "url": "",
        "title": "",
        "value": "",
    }
    body.update(extra)
    return body
