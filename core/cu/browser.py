"""Browser-use wrappers on top of Computer Use. Not a Chromium embed (PP80)."""

from __future__ import annotations

import json
import re
import webbrowser
from typing import Any, Callable
from urllib.parse import urlparse

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from RxyCode.RxyCode1_1_0.core.safety.policy import register_tool_risk

from .spec import BROWSER_APP_CANDIDATES, TOOL_DESCRIPTIONS, TOOL_RISK

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

CallFn = Callable[[str, dict[str, Any]], str]


def _looks_like_browser(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return any(candidate.lower() in lowered for candidate in BROWSER_APP_CANDIDATES)


def pick_browser_app(list_apps_payload: str) -> str | None:
    """Choose a running Chrome/Edge/Firefox name from list_apps JSON/text."""
    text = list_apps_payload or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    names: list[str] = []
    if isinstance(parsed, dict):
        rows = parsed.get("apps") or parsed.get("applications") or parsed.get("windows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    names.append(str(row.get("app") or row.get("name") or row.get("title") or ""))
                elif isinstance(row, str):
                    names.append(row)
    elif isinstance(parsed, list):
        for row in parsed:
            if isinstance(row, dict):
                names.append(str(row.get("app") or row.get("name") or row.get("title") or ""))
            elif isinstance(row, str):
                names.append(row)
    if not names:
        for line in text.splitlines():
            names.append(line.strip())
    for name in names:
        if _looks_like_browser(name):
            return name
    return None


def _validate_http_url(url: str) -> str | None:
    candidate = (url or "").strip()
    if not candidate:
        return None
    if not _URL_RE.match(candidate):
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


class BrowserOpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., description="http(s) URL to open in the system browser")


class BrowserSnapshotArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str | None = Field(
        default=None,
        description="Optional app name from list_apps. Omit to auto-pick Chrome/Edge.",
    )


class BrowserActArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(..., description="click | type | press | scroll")
    app: str | None = Field(default=None, description="Browser app name; omit to auto-pick")
    element_index: str | int | None = Field(
        default=None,
        description="Index from the latest browser_snapshot accessibility tree",
    )
    x: int | None = None
    y: int | None = None
    text: str | None = Field(default=None, description="Text for action=type")
    key: str | None = Field(default=None, description="Key for action=press, e.g. Return")
    pages: float | None = Field(default=None, description="Scroll pages; positive=down")


def _strip_screenshots(payload: str) -> str:
    """Drop screenshot/base64 blobs so browser snapshots stay a11y-cheap."""
    text = (payload or "").strip()
    if not text:
        return payload
    try:
        parsed, _end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return payload
    if not isinstance(parsed, dict):
        return payload
    for key in (
        "screenshot",
        "screenshot_png",
        "screenshotPng",
        "image",
        "image_base64",
        "png",
        "overlay",
    ):
        parsed.pop(key, None)
    return json.dumps(parsed, ensure_ascii=False)


def make_browser_tools(*, call: CallFn, approved: bool) -> list[StructuredTool]:
    def _require_approved() -> str | None:
        if approved:
            return None
        return (
            "[error: computer-use first-run approval required. "
            "Set computer_use.approved=true (or RXYCODE_COMPUTER_USE_APPROVED=1) "
            "after reviewing desktop control risk.]"
        )

    def _resolve_app(explicit: str | None) -> tuple[str | None, str]:
        if explicit:
            return explicit, ""
        listed = call("list_apps", {})
        picked = pick_browser_app(listed)
        if picked:
            return picked, listed
        return None, listed

    def browser_open(url: str) -> str:
        denied = _require_approved()
        if denied:
            return denied
        target = _validate_http_url(url)
        if target is None:
            return "[error: browser_open requires an http(s) URL]"
        opened = webbrowser.open(target, new=2)
        # 废弃代码（2026-09-22）：打开系统浏览器后立刻 browser_snapshot()。
        # 那条快照走 computer-use MCP；MCP 未连接时整段返回失败，
        # 即使窗口已经打开。页面标题和链接由虚拟浏览器 browser_snapshot 读取。
        # snapshot = browser_snapshot(app=None)
        return (
            f"opened={opened} url={target}\n"
            "System browser window opened. Call browser_snapshot for the title "
            "and links. Do not wait for the user to close the window.\n"
        )

    def browser_snapshot(app: str | None = None) -> str:
        resolved, listed = _resolve_app(app)
        if resolved is None:
            return (
                "[error: no running Chrome/Edge/Firefox. Call browser_open first. "
                f"list_apps={listed[:2000]}]"
            )
        state = call(
            "get_app_state",
            {"app": resolved, "include_screenshot": False},
        )
        if state.startswith("[error:"):
            state = call("get_app_state", {"app": resolved})
        return _strip_screenshots(state)

    def browser_act(
        action: str,
        app: str | None = None,
        element_index: str | int | None = None,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        key: str | None = None,
        pages: float | None = None,
    ) -> str:
        denied = _require_approved()
        if denied:
            return denied
        resolved, listed = _resolve_app(app)
        if resolved is None:
            return (
                "[error: no running browser app for browser_act. "
                f"list_apps={listed[:2000]}]"
            )
        kind = (action or "").strip().lower()
        args: dict[str, Any] = {"app": resolved}
        if element_index is not None:
            args["element_index"] = element_index
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        if kind == "click":
            result = call("click", args)
        elif kind in {"type", "type_text"}:
            if not text:
                return "[error: browser_act action=type requires text]"
            args["text"] = text
            result = call("type_text", args)
        elif kind in {"press", "press_key"}:
            if not key:
                return "[error: browser_act action=press requires key]"
            args["key"] = key
            result = call("press_key", args)
        elif kind == "scroll":
            if pages is not None:
                args["pages"] = pages
            result = call("scroll", args)
        else:
            return "[error: browser_act action must be click, type, press, or scroll]"
        verified = call("get_app_state", {"app": resolved})
        return result + "\n--- verify ---\n" + _strip_screenshots(verified)

    tools = [
        StructuredTool(
            name="browser_open",
            description=TOOL_DESCRIPTIONS["browser_open"],
            func=browser_open,
            args_schema=BrowserOpenArgs,
            metadata={"source": "computer_use", "cu_kind": "browser"},
        ),
        StructuredTool(
            name="browser_snapshot",
            description=TOOL_DESCRIPTIONS["browser_snapshot"],
            func=browser_snapshot,
            args_schema=BrowserSnapshotArgs,
            metadata={"source": "computer_use", "cu_kind": "browser"},
        ),
        StructuredTool(
            name="browser_act",
            description=TOOL_DESCRIPTIONS["browser_act"],
            func=browser_act,
            args_schema=BrowserActArgs,
            metadata={"source": "computer_use", "cu_kind": "browser"},
        ),
    ]
    for tool in tools:
        register_tool_risk(tool.name, TOOL_RISK[tool.name])
    return tools
