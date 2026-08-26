"""License + security gate for GitHub skills/MCP bound to expert roles.

LC13/LC17: SPDX from GitHub API, then the skill-directory LICENSE.
LC8: MCP drafts stay disabled. LC16: no SessionStart injection.
"""

from __future__ import annotations

import re
from typing import Iterable

ALLOWED_SPDX = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "0BSD",
        "Unlicense",
    }
)
DENIED_SPDX = frozenset(
    {
        "GPL-2.0",
        "GPL-3.0",
        "GPL-2.0-only",
        "GPL-3.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-or-later",
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-SA-3.0",
        "NOASSERTION",
        "Other",
    }
)

_UNPINNED_INSTALL = re.compile(
    r"(?:npx\s+-y\b|npm\s+exec\s+-y\b|uvx\s+\S+|curl\s+[^\n|]+\|\s*(?:ba)?sh)",
    re.IGNORECASE,
)
_SESSION_START = re.compile(r"\bSessionStart\b")
_AUTO_APPROVE = re.compile(r"\bauto[-_]?approve\b", re.IGNORECASE)
_REMOTE_PIPE = re.compile(r"\bwget\s+[^\n|]+\|\s*(?:ba)?sh", re.IGNORECASE)


def spdx_allowed(spdx: str | None) -> bool:
    """Return True only for a clean, redistributable SPDX id (LC17)."""
    if spdx is None:
        return False
    text = str(spdx).strip()
    if not text or text in DENIED_SPDX:
        return False
    return text in ALLOWED_SPDX


def scan_skill_markdown(text: str) -> list[str]:
    """Static security findings. Empty list means the text may be vendored."""
    findings: list[str] = []
    body = text or ""
    if _SESSION_START.search(body):
        findings.append("SessionStart hook injection is forbidden (LC16)")
    if _UNPINNED_INSTALL.search(body):
        findings.append("unpinned npx -y / uvx / curl|sh installer")
    if _AUTO_APPROVE.search(body):
        findings.append("MCP auto-approve is forbidden (LC8)")
    if _REMOTE_PIPE.search(body):
        findings.append("remote script piped to a shell")
    return findings


def should_vendor(*, spdx: str | None, text: str) -> tuple[bool, list[str]]:
    """Combine license + content gates. MCP processes are never auto-started."""
    reasons: list[str] = []
    if not spdx_allowed(spdx):
        reasons.append(f"license not redistributable: {spdx!r}")
    reasons.extend(scan_skill_markdown(text))
    return (not reasons, reasons)


def mcp_default_disabled(server_names: Iterable[str]) -> dict[str, bool]:
    """Every declared MCP server starts disabled (LC8)."""
    return {str(name): False for name in server_names if str(name).strip()}
