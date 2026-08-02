"""JSON-RPC approval broker for appserver stdio transport."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from ..core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
    from .runtime import get_bound_session_id
except ImportError:
    from core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
    from appserver.runtime import get_bound_session_id


SendServerRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class JsonRpcApproval(ApprovalBroker):
    """Appserver approval channel.

    Publishes ``approval/request`` as a JSON-RPC server request on stdout and
    waits for the client ``result`` on stdin (resolved by ``AppServer``).
    """

    def __init__(
        self,
        send_request: SendServerRequest,
        *,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self._send_request = send_request
        self.timeout = timeout

    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        session_id = get_bound_session_id()
        try:
            payload = await asyncio.wait_for(
                self._send_request(
                    "approval/request",
                    {
                        "session_id": session_id,
                        "request_id": request.approval_id,
                        "risk_level": request.risk.name,
                        "action": request.tool_name,
                        "details": {"args": request.args_summary},
                    },
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return ApprovalDecision.REJECTED

        decision_name = str(payload.get("decision", "rejected"))
        try:
            return ApprovalDecision(decision_name)
        except ValueError:
            return ApprovalDecision.REJECTED