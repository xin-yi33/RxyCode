"""GX2-B: card vs modal routing and request_id idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.approval_router import ApprovalRouter, ApprovalRouterError
from appserver.server import AppServer


def test_no_handlers_package() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "appserver" / "handlers").exists()


def test_ask_non_high_risk_uses_card() -> None:
    router = ApprovalRouter()
    assert router.route("r1", risk="write", preset="ask", action="write README.md") == "card"


def test_high_risk_always_modal() -> None:
    router = ApprovalRouter()
    assert router.route("r2", risk="high", preset="ask", action="ls") == "modal"
    assert router.route("r3", risk="low", preset="ask", action="rm -rf /") == "modal"
    assert router.route("r4", risk="write", preset="full", action="edit .env") == "modal"


def test_same_request_id_stays_on_one_channel() -> None:
    router = ApprovalRouter()
    first = router.route("same", risk="write", preset="ask", action="write")
    second = router.route("same", risk="high", preset="ask", action="rm -rf /")
    assert first == second == "card"


def test_respond_allow_deny_cancel_and_idempotent() -> None:
    router = ApprovalRouter()
    router.route("rid", risk="write", preset="ask", action="write")
    first = router.respond("rid", "allow")
    assert first["action"] == "allow"
    assert first["channel"] == "card"
    with pytest.raises(ApprovalRouterError, match="request_id already handled"):
        router.respond("rid", "deny")


def test_invalid_card_action() -> None:
    router = ApprovalRouter()
    with pytest.raises(ApprovalRouterError):
        router.respond("x", "maybe")


def test_appserver_uses_router() -> None:
    server = AppServer(stub=True)
    assert server.route_approval("a1", risk="write", action="write foo.py") == "card"
    assert server.route_approval("a2", action="Remove-Item -Recurse") == "modal"
    again = server.route_approval("a1", risk="high", action="rm")
    assert again == "card"
