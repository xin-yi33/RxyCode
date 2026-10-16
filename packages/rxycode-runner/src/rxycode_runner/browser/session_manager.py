"""Isolated agent and preview browser contexts.

U24 tool names stay in tools/virtual_browser.py. Computer Use browser_open
stays in core/cu/browser.py. This module does not attach to the user's Chrome
and does not call webfetch.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SESSIONS: dict[str, "Session"] = {}
_HANDOFF: dict[str, tuple[Any, Any]] = {}
_PROFILE_KIND: dict[str, str] = {}
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
    if _user_browser_dir(target) or _foreign_browser_profile(target):
        return _refused("user Chrome data is not shared")
    key = _profile_key(target)
    stored = _stored_kind(target)
    previous = stored or _PROFILE_KIND.get(key, "")
    if previous and previous != kind:
        return _refused("agent and preview profiles must stay distinct")
    for existing in _SESSIONS.values():
        if _profile_key(existing.profile_dir) == key:
            return _refused("browser profile is already open")
    target.mkdir(parents=True, exist_ok=True)
    _write_kind(target, kind)
    try:
        playwright, context, page = _launch(target)
    except Exception as exc:
        return _refused(f"browser launch failed: {type(exc).__name__}: {exc}")
    session_id = "br-" + uuid.uuid4().hex[:12]
    _PROFILE_KIND[key] = kind
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


def present_handoff(*, agent_session_id: str, url: str) -> dict[str, object]:
    """Open the handoff page. Its button is the only grant for this session."""
    agent = _SESSIONS.get(agent_session_id)
    if agent is None:
        return _refused("unknown browser session")
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        return _refused("browser requires an http(s) URL")
    playwright = _driver()
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    def grant(requested: str) -> bool:
        if requested != agent_session_id:
            return False
        result = authorize_handoff(session_id=agent_session_id, authorized=True)
        return result.get("status") == "authorized"

    try:
        page.expose_function("rxyAuthorizeHandoff", grant)
        page.goto(target, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("button", timeout=10000)
    except Exception as exc:
        browser.close()
        return _refused(f"handoff page failed: {type(exc).__name__}: {exc}")
    _HANDOFF[agent_session_id] = (browser, page)
    return _view(agent, status="open")


def run_on_handoff_page(*, agent_session_id: str, action: Any) -> dict[str, object]:
    """Let the caller perform the user action. This function does not click."""
    pair = _HANDOFF.get(agent_session_id)
    agent = _SESSIONS.get(agent_session_id)
    if pair is None or agent is None:
        return _refused("handoff is not open")
    _browser, page = pair
    try:
        action(page)
        dom = page.content()
    except Exception as exc:
        return _refused(f"handoff action failed: {type(exc).__name__}: {exc}")
    status = "authorized" if agent.authorized else "open"
    return _view(agent, status=status, dom=dom, url=page.url, title=_title_page(page))


def close_handoff_page(*, agent_session_id: str) -> None:
    handoff = _HANDOFF.pop(agent_session_id, None)
    if handoff is None:
        return
    browser, _page = handoff
    try:
        browser.close()
    except Exception:
        pass


def close_session(*, session_id: str) -> None:
    handoff = _HANDOFF.pop(session_id, None)
    if handoff is not None:
        browser, _page = handoff
        try:
            browser.close()
        except Exception:
            pass
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        _stop_driver_when_idle()
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


def _driver() -> Any:
    global _PLAYWRIGHT
    from playwright.sync_api import sync_playwright

    if _PLAYWRIGHT is None:
        _PLAYWRIGHT = sync_playwright().start()
    return _PLAYWRIGHT


def _launch(profile_dir: Path) -> tuple[Any, Any, Any]:
    """One sync driver can own several persistent profiles. A second driver fails."""
    global _PLAYWRIGHT
    created = _PLAYWRIGHT is None
    playwright = _driver()
    try:
        context = _start_context(playwright, profile_dir)
    except Exception:
        if created:
            playwright.stop()
            _PLAYWRIGHT = None
        raise
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


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


_KIND_FILE = "rxy-profile-kind"
_CHROME_FILES = (
    Path("Local State"),
    Path("Default") / "Preferences",
    Path("Default") / "Network" / "Cookies",
    Path("Default") / "Cookies",
)


def _profile_key(path: Path) -> str:
    return str(_safe_resolve(path)).lower()


def _stored_kind(path: Path) -> str:
    marker = _safe_resolve(path) / _KIND_FILE
    if not marker.is_file():
        return ""
    return marker.read_text(encoding="utf-8").strip()


def _write_kind(path: Path, kind: str) -> None:
    marker = path / _KIND_FILE
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == kind:
        return
    marker.write_text(kind + "\n", encoding="utf-8")


def _foreign_browser_profile(path: Path) -> bool:
    """An existing Chrome profile has no kind marker written by this manager."""
    resolved = _safe_resolve(path)
    if (resolved / _KIND_FILE).is_file():
        return False
    return any((resolved / rel).exists() for rel in _CHROME_FILES)


def _user_browser_dir(path: Path) -> bool:
    """Refuse the real profile and any symlink or junction that points at it."""
    candidates = [path]
    for resolver in (_safe_resolve, _safe_realpath):
        candidates.append(resolver(path))
    for candidate in candidates:
        if _looks_like_user_browser(candidate) or _is_known_user_data(candidate):
            return True
    return False


def _looks_like_user_browser(path: Path) -> bool:
    text = str(path).replace("/", "\\").lower()
    if "user data" not in text:
        return False
    names = ("chrome", "edge", "chromium", "brave")
    return any(name in text for name in names)


def _is_known_user_data(path: Path) -> bool:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return False
    roots = (
        Path(local) / "Google" / "Chrome" / "User Data",
        Path(local) / "Microsoft" / "Edge" / "User Data",
        Path(local) / "Chromium" / "User Data",
        Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data",
    )
    try:
        resolved = _safe_resolve(path)
    except OSError:
        return False
    for root in roots:
        try:
            known = _safe_resolve(root)
        except OSError:
            continue
        if resolved == known or known in resolved.parents:
            return True
    return False


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _safe_realpath(path: Path) -> Path:
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return path


def _title(session: Session) -> str:
    return _title_page(session.page)


def _title_page(page: Any) -> str:
    try:
        return str(page.title())
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
