"""GX14 capability hard boundary at the tool-registry layer.

Ask/Edit/Agent maps to no_tools/edit_only/full. Orthogonal to GX2 approval
presets and to B5 mode=plan (capability is checked first; protocol error, not
a plan-mode blocked tool result).
Never lives under appserver/handlers/.
"""

from __future__ import annotations

CAPABILITIES = ("no_tools", "edit_only", "full")
EDIT_ONLY_DENIED = ("bash", "delete", "git", "shell", "exec")


class CapabilityDenied(Exception):
    def __init__(self, message: str, *, code: str = "capability_denied") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_capability(value: str | None) -> str:
    if value in (None, ""):
        return "full"
    cap = str(value)
    if cap not in CAPABILITIES:
        raise CapabilityDenied(f"invalid capability: {cap}", code="invalid_capability")
    return cap


def allow_tool(capability: str | None, tool_name: str) -> None:
    cap = normalize_capability(capability)
    name = str(tool_name or "").strip().lower()
    if cap == "full":
        return
    if cap == "no_tools":
        raise CapabilityDenied(f"no_tools forbids {tool_name}", code="capability_denied")
    denied = any(name == item or name.startswith(item + ".") or name.startswith(item + ":") or name.startswith(item + "_") for item in EDIT_ONLY_DENIED)
    if denied:
        raise CapabilityDenied(
            f"edit_only forbids {tool_name}",
            code="capability_denied",
        )


class ToolRegistryCapability:
    """Session-scoped capability; default full."""

    def __init__(self) -> None:
        self._caps: dict[str, str] = {}

    def set_session(self, session_id: str, capability: str | None) -> str:
        cap = normalize_capability(capability)
        self._caps[session_id] = cap
        return cap

    def get(self, session_id: str) -> str:
        return self._caps.get(session_id) or "full"

    def check(self, session_id: str, tool_name: str) -> None:
        allow_tool(self.get(session_id), tool_name)
