"""Computer Use tool surface (PP40–PP42). Independent of agent_v2.

SPDX of the extended MCP: MIT — GitHub API ``license.spdx_id`` for
iFurySt/open-codex-computer-use on 2026-09-13. Source is not vendored.
"""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

OCU_SPDX = "MIT"
OCU_UPSTREAM = "https://github.com/iFurySt/open-codex-computer-use"
OCU_SERVER_NAME = "open-computer-use"

# Keep ocu names. Do not rename to computer_use_1 (PP40).
OBSERVE_TOOLS: tuple[str, ...] = ("list_apps", "get_app_state")
ACTION_TOOLS: tuple[str, ...] = (
    "click",
    "perform_secondary_action",
    "scroll",
    "drag",
    "type_text",
    "press_key",
    "set_value",
)
OCU_TOOLS: tuple[str, ...] = OBSERVE_TOOLS + ACTION_TOOLS
BROWSER_TOOLS: tuple[str, ...] = (
    "browser_open",
    "browser_snapshot",
    "browser_act",
)
# Prefix-stable append order when the capability is on.
CU_TOOL_ORDER: tuple[str, ...] = OCU_TOOLS + BROWSER_TOOLS

BROWSER_APP_CANDIDATES: tuple[str, ...] = (
    "msedge",
    "msedge.exe",
    "chrome",
    "chrome.exe",
    "firefox",
    "firefox.exe",
    "Google Chrome",
    "Microsoft Edge",
    "Chromium",
)

TOOL_RISK: dict[str, RiskLevel] = {
    "list_apps": RiskLevel.READ,
    "get_app_state": RiskLevel.READ,
    "browser_snapshot": RiskLevel.READ,
    "click": RiskLevel.DANGER,
    "perform_secondary_action": RiskLevel.DANGER,
    "scroll": RiskLevel.WRITE,
    "drag": RiskLevel.DANGER,
    "type_text": RiskLevel.DANGER,
    "press_key": RiskLevel.DANGER,
    "set_value": RiskLevel.DANGER,
    "browser_open": RiskLevel.WRITE,
    "browser_act": RiskLevel.DANGER,
}

# When-to-use copy is the highest-leverage harness fix (agent-runtime pairing).
TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_apps": (
        "Computer Use observe (step 1). List running desktop apps with OS "
        "accessibility facts (AX/UIA/AT-SPI), not a guess. Call this before "
        "click/type. Do not use for reading source files (use ls/grep). "
        "Default-off capability. The tool stays visible; calling it while "
        "Computer Use is off asks the user to enable it. full_auto enables "
        "and runs without a dialog. Do not use for reading source files."
    ),
    "get_app_state": (
        "Computer Use observe (step 2). Return the accessibility tree of one app "
        "(source=accessibility). Prefer element_index from this tree over pixel "
        "coordinates. Do not request a screenshot unless the tree is empty or "
        "the user asked to verify pixels. After every click/type, call this "
        "again to verify. Not a substitute for webfetch on a URL you can GET."
    ),
    "click": (
        "Computer Use act. Click an accessibility element_index from the latest "
        "get_app_state, or x/y only when the tree has no target. Then verify "
        "with get_app_state. Requires Computer Use first-run approval."
    ),
    "perform_secondary_action": (
        "Computer Use act. Accessibility action (focus, show menu, …) on an "
        "element_index. Prefer this over pixel clicks when the tree exposes the "
        "action. Then verify with get_app_state."
    ),
    "scroll": (
        "Computer Use act. Scroll inside an element or at coordinates. Prefer "
        "element_index. Then verify with get_app_state."
    ),
    "drag": (
        "Computer Use act. Drag between coordinates inside one app window. "
        "Last resort when accessibility has no drag action. Then verify."
    ),
    "type_text": (
        "Computer Use act. Type into the focused field of the target app. "
        "Click the field first if it is not focused; use set_value for an "
        "unfocused named field. Then verify with get_app_state."
    ),
    "press_key": (
        "Computer Use act. Press a key or combo (Return, BackSpace, ctrl+c). "
        "Then verify with get_app_state."
    ),
    "set_value": (
        "Computer Use act. Set the value of an accessibility text field without "
        "pixel-clicking. Prefer this over type_text for unfocused inputs. "
        "Then verify with get_app_state."
    ),
    "browser_open": (
        "Browser use. Open a URL in the system browser (Chrome/Edge if present). "
        "Use this instead of list_apps+click for web tasks. Then call "
        "browser_snapshot. Do not tell the user to open the link themselves. "
        "webfetch is better for a single public GET with no login/JS."
    ),
    "browser_snapshot": (
        "Browser use observe. Accessibility snapshot of the front browser "
        "tab/window. Prefer this over screenshots and over CSS/XPath. Use "
        "returned element refs/indexes with browser_act. Loop: snapshot → "
        "act → snapshot."
    ),
    "browser_act": (
        "Browser use act. One click/type/press/scroll against the latest "
        "browser_snapshot. Prefer element_index. Combines click/type/press so "
        "web tasks need fewer tools. Then call browser_snapshot to verify."
    ),
}
