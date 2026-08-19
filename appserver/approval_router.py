"""GX2 approval presentation router: card vs modal, request_id idempotency.

Consumes B7 risk classification. Does not invent a second permission model.
Never lives under appserver/handlers/.
"""

from __future__ import annotations

from typing import Any

HIGH_RISK_LEVELS = frozenset({"high", "danger", "DANGER", "HIGH"})
HIGH_RISK_MARKERS = (
    "rm",
    "remove-item",
    "del /",
    "delete",
    ".env",
    "mkfs",
    "format",
    "drop table",
)


class ApprovalRouterError(Exception):
    def __init__(self, message: str, *, code: str = "approval_router") -> None:
        super().__init__(message)
        self.code = code


class ApprovalRouter:
    """Single source for which channel presents one approval request_id."""

    def __init__(self) -> None:
        self._channel: dict[str, str] = {}
        self._handled: dict[str, str] = {}

    def is_high_risk(self, *, risk: str = "", action: str = "") -> bool:
        if str(risk or "") in HIGH_RISK_LEVELS:
            return True
        text = str(action or "").lower()
        return any(marker in text for marker in HIGH_RISK_MARKERS)

    def route(
        self,
        request_id: str,
        *,
        risk: str = "",
        preset: str = "ask",
        action: str = "",
    ) -> str:
        rid = str(request_id or "").strip()
        if not rid:
            raise ApprovalRouterError("request_id required", code="invalid_request")
        if self.is_high_risk(risk=risk, action=action):
            channel = "modal"
        elif str(preset or "ask") == "ask":
            channel = "card"
        else:
            channel = "card"
        existing = self._channel.get(rid)
        if existing is not None:
            return existing
        self._channel[rid] = channel
        return channel

    def respond(self, request_id: str, action: str) -> dict[str, Any]:
        rid = str(request_id or "").strip()
        verb = str(action or "").strip().lower()
        if verb not in {"allow", "deny", "cancel"}:
            raise ApprovalRouterError("action must be allow, deny, or cancel", code="invalid_action")
        if rid in self._handled:
            raise ApprovalRouterError("request_id already handled", code="already_handled")
        if rid not in self._channel:
            self._channel[rid] = "card"
        self._handled[rid] = verb
        return {
            "request_id": rid,
            "action": verb,
            "channel": self._channel[rid],
        }

    def channel_for(self, request_id: str) -> str | None:
        return self._channel.get(str(request_id or "").strip())
