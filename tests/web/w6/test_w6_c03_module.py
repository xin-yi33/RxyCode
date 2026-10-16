"""WEB-W6-C03. Authorized handoff continues one agent session, not user Chrome."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
for _entry in (REPO, _RUNNER, REPO / "tests" / "web" / "w6"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def test_w6_c03_integration() -> None:
    """A handoff click authorizes the same agent session and leaves Chrome alone."""
    from test_w6_c03_unit import start_page
    from rxycode_runner.browser.session_manager import (
        authorize_handoff,
        close_session,
        continue_session,
        navigate_click,
        open_agent_context,
        read_storage,
        request_user_cookies,
        snapshot,
    )

    token = "rxy-hand-" + uuid.uuid4().hex
    server, url = start_page(token)
    root = Path(tempfile.mkdtemp(prefix="rxy-w6c03-mod-"))
    user_chrome = root / "Google" / "Chrome" / "User Data"
    secret_path = user_chrome / "Default" / "Cookies"
    secret_path.parent.mkdir(parents=True)
    secret = b"CHROME-SECRET-" + uuid.uuid4().hex.encode("ascii")
    secret_path.write_bytes(secret)
    before = sorted(str(path.relative_to(user_chrome)) for path in user_chrome.rglob("*") if path.is_file())
    agent_dir = root / "agent-profile"
    preview_dir = root / "preview-profile"
    opened: list[str] = []
    try:
        agent = open_agent_context(profile_dir=agent_dir, kind="agent")
        preview = open_agent_context(profile_dir=preview_dir, kind="preview")
        assert agent["status"] == "open"
        assert preview["status"] == "open"
        assert agent["profile_kind"] == "agent"
        assert preview["profile_kind"] == "preview"
        assert Path(agent["profile_dir"]) != Path(preview["profile_dir"])
        opened.extend([str(agent["session_id"]), str(preview["session_id"])])
        blocked = continue_session(session_id=str(agent["session_id"]))
        assert blocked["status"] == "refused"
        assert token not in blocked.get("dom", "")
        pending = _render(session_id=str(agent["session_id"]), authorized=False)
        assert 'aria-label="browser-handoff"' in pending
        assert 'data-authorized="false"' in pending
        assert f'data-session="{agent["session_id"]}"' in pending
        assert "授权接管" in pending
        assert "<iframe" not in pending.lower()
        assert secret.decode("ascii") not in pending
        clicked = navigate_click(session_id=str(agent["session_id"]), url=url, selector="#go")
        assert clicked["status"] == "ok"
        assert token in clicked["dom"]
        preview_hit = navigate_click(
            session_id=str(preview["session_id"]),
            url=url,
            selector="#missing",
        )
        assert preview_hit["status"] != "ok"
        assert read_storage(session_id=str(preview["session_id"]), key="rxy-marker")["value"] in ("", None)
        granted = authorize_handoff(session_id=str(agent["session_id"]), authorized=True)
        assert granted["status"] == "authorized"
        assert granted["shared"] is False
        continued = continue_session(session_id=str(agent["session_id"]))
        assert continued["status"] == "ok"
        assert continued["session_id"] == agent["session_id"]
        assert continued["profile_kind"] == "agent"
        assert token in continued["dom"]
        assert read_storage(session_id=str(agent["session_id"]), key="rxy-marker")["value"] == token
        live = _render(session_id=str(agent["session_id"]), authorized=True)
        assert 'data-authorized="true"' in live
        assert "agent session continued" in live
        assert "user Chrome data is not shared" in live
        cookies = request_user_cookies(authorized=True, user_chrome_dir=user_chrome)
        assert cookies["shared"] is False
        assert secret.decode("ascii") not in str(cookies)
        public = navigate_click(
            session_id=str(agent["session_id"]),
            url="https://example.com/",
            selector="a",
        )
        assert public["status"] == "ok", public
        shot = snapshot(session_id=str(agent["session_id"]))
        assert shot["status"] == "ok"
        blob = (shot["dom"] + shot.get("title", "") + shot["url"]).lower()
        assert "iana.org" in blob or "example domain" in blob
        assert secret.decode("ascii") not in blob
        assert secret_path.read_bytes() == secret
        after = sorted(
            str(path.relative_to(user_chrome))
            for path in user_chrome.rglob("*")
            if path.is_file()
        )
        assert after == before
        for session_id in opened:
            close_session(session_id=session_id)
        opened.clear()
        for cookies_file in agent_dir.rglob("Cookies"):
            assert secret not in cookies_file.read_bytes()
        _assert_wheel_contains_session_manager()
    finally:
        for session_id in opened:
            close_session(session_id=session_id)
        server.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def _assert_wheel_contains_session_manager() -> None:
    """The installed wheel contains the browser session manager."""
    out = Path(tempfile.mkdtemp(prefix="rxy-w6c03-wheel-"))
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(out),
            str(REPO),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    wheels = list(out.glob("*.whl"))
    assert wheels
    names: set[str] = set()
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as bundle:
            names.update(bundle.namelist())
    assert "rxycode_runner/browser/session_manager.py" in names
    assert "rxycode_runner/browser/__init__.py" in names


def _render(*, session_id: str, authorized: bool) -> str:
    if not BUN.is_file():
        pytest.fail("bun is not installed")
    env = os.environ.copy()
    env["RXY_SESSION"] = session_id
    env["RXY_AUTHORIZED"] = "true" if authorized else "false"
    component = REPO / "apps" / "web" / "src" / "features" / "browser" / "BrowserHandoff.tsx"
    env["RXY_COMPONENT"] = str(component)
    script = r"""
import { createRequire } from "module"
import { pathToFileURL } from "url"
const require = createRequire(pathToFileURL(process.env.RXY_COMPONENT).href)
const React = require(require.resolve("react", { paths: [process.cwd() + "/apps/web"] }))
const { renderToStaticMarkup } = require(require.resolve("react-dom/server", { paths: [process.cwd() + "/apps/web"] }))
const { BrowserHandoff } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const html = renderToStaticMarkup(React.createElement(BrowserHandoff, {
  sessionId: process.env.RXY_SESSION,
  authorized: process.env.RXY_AUTHORIZED === "true",
}))
process.stdout.write(html)
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c03-ui-")) / "render.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [str(BUN), str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
    assert rendered.returncode == 0, rendered.stderr
    json.dumps({"session_id": session_id, "authorized": authorized})
    return rendered.stdout
