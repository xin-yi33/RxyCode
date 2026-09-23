"""Classify shell commands that launch a GUI instead of finishing in the shell.

Opening a document is OS-launch success, not "the user closed the window".
``bash`` must not ``communicate()`` until Word/Notepad/Typora exits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .open_file import PREVIEWABLE_EXTENSIONS

LaunchKind = Literal["open_preview", "detach"]

_TOKEN = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_WAIT_FLAGS = frozenset({"/wait", "-wait"})
_CMD_FLAGS = frozenset({"/c", "/s", "/q", "/d", "/k"})
_PS_META = frozenset(
    {
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "-noprofile",
        "-nologo",
        "-noninteractive",
        "-command",
        "-c",
        "-file",
    }
)
_LAUNCH_VERBS = frozenset(
    {
        "start",
        "xdg-open",
        "gio",
        "explorer",
        "explorer.exe",
        "start-process",
        "invoke-item",
        "ii",
        "open",
    }
)
_GUI_BINS = frozenset(
    {
        "notepad",
        "notepad.exe",
        "wordpad",
        "wordpad.exe",
        "write",
        "write.exe",
        "winword",
        "winword.exe",
        "excel",
        "excel.exe",
        "powerpnt",
        "powerpnt.exe",
        "acrord32",
        "acrord32.exe",
        "acrobat",
        "acrobat.exe",
        "typora",
        "typora.exe",
        "code",
        "code.exe",
        "devenv",
        "devenv.exe",
        "mspaint",
        "mspaint.exe",
        "msedge",
        "msedge.exe",
        "chrome",
        "chrome.exe",
        "firefox",
        "firefox.exe",
        "hh",
        "hh.exe",
        "onenote",
        "onenote.exe",
        "photos",
        "photos.exe",
    }
)


@dataclass(frozen=True)
class LaunchPlan:
    kind: LaunchKind
    path: str | None = None
    command: str = ""
    reason: str = ""


def tokenize_shell(command: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN.finditer((command or "").strip()):
        if match.group(1) is not None:
            tokens.append(match.group(1))
        elif match.group(2) is not None:
            tokens.append(match.group(2))
        else:
            tokens.append(match.group(3) or "")
    return tokens


def _basename(token: str) -> str:
    name = token.replace("\\", "/").rstrip("/").split("/")[-1]
    return name.casefold()


def _strip_wrappers(tokens: list[str]) -> list[str]:
    if not tokens:
        return tokens
    head = _basename(tokens[0])
    rest = tokens[1:]
    if head in {"cmd", "cmd.exe"}:
        while rest and rest[0].casefold() in _CMD_FLAGS:
            rest = rest[1:]
        return rest
    if head in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        while rest and rest[0].casefold() in _PS_META:
            rest = rest[1:]
        return rest
    return tokens


def _looks_like_path(token: str) -> bool:
    if not token:
        return False
    folded = token.casefold()
    if folded in _WAIT_FLAGS:
        return False
    if "\\" in token or "/" in token:
        return True
    if len(token) >= 3 and token[1] == ":":
        return True
    if "." in token:
        return True
    return False


def _previewable_path(token: str) -> str | None:
    if not _looks_like_path(token):
        return None
    name = token.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return None
    suffix = "." + name.rsplit(".", 1)[-1].casefold()
    if suffix in PREVIEWABLE_EXTENSIONS:
        return token
    return None


def classify_shell_launch(command: str) -> LaunchPlan | None:
    """Return a launch plan, or None to run the command as a normal foreground shell."""
    raw = (command or "").strip()
    if not raw:
        return None
    tokens = _strip_wrappers(tokenize_shell(raw))
    if not tokens:
        return None
    lowered = [tok.casefold() for tok in tokens]
    if (
        any(flag in lowered for flag in ("/wait", "-wait", "--wait"))
        or "-W" in tokens
        or "-nonewwindow" in lowered
    ):
        # Explicit wait-for-app or same-console start. Leave as a foreground shell.
        return None

    verb = _basename(tokens[0])
    if verb == "start" and "/b" in lowered:
        # ``start /b`` keeps a console job in the same shell; do not detach it.
        return None
    if verb == "gio":
        # Only ``gio open …`` is a launcher; ``gio list`` stays foreground.
        if len(tokens) < 2 or tokens[1].casefold() != "open":
            return None
    if verb not in _LAUNCH_VERBS and verb not in _GUI_BINS:
        return None

    candidate = ""
    for token in reversed(tokens):
        if token.casefold() in _WAIT_FLAGS or token in {"", '""'}:
            continue
        if token.startswith("/") and len(token) <= 6:
            continue
        if token.startswith("-") and len(token) <= 4:
            continue
        candidate = token
        break

    preview = _previewable_path(candidate) if candidate else None
    if preview and verb in _LAUNCH_VERBS:
        return LaunchPlan(
            kind="open_preview",
            path=preview,
            command=raw,
            reason="previewable-file",
        )
    return LaunchPlan(kind="detach", command=raw, reason=f"gui-launch:{verb}")
