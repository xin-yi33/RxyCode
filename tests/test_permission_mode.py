"""GX2-B: UI presets mapped onto B7 policy via approval/mode_set."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from appserver.permission import PRESET_TO_B7, PermissionStore
from appserver.server import AppServer
from protocol.requests import (
    ApprovalFullAccessEnableRequest,
    ApprovalModeSetRequest,
    PermissionSetRequest,
)


def test_mode_set_request_uses_preset_not_mode() -> None:
    req = ApprovalModeSetRequest(preset="ask")
    dumped = req.model_dump()
    assert dumped["method"] == "approval/mode_set"
    assert dumped["preset"] == "ask"
    assert "mode" not in dumped
    ignored = ApprovalModeSetRequest.model_validate({"preset": "auto", "mode": "full"})
    assert ignored.preset == "auto"
    assert not hasattr(ignored, "mode") or getattr(ignored, "mode", None) is None
    with pytest.raises(ValidationError):
        ApprovalModeSetRequest.model_validate({"preset": "maybe"})


def test_preset_maps_to_existing_b7_policies() -> None:
    assert PRESET_TO_B7 == {
        "ask": "ask_for_each_risky_action",
        "auto": "allow_scoped_actions",
        "full": "full_access",
    }
    store = PermissionStore(persistent=False)
    store.set_profile("allow_scoped_actions")
    assert store.snapshot()["profile_id"] == "allow_scoped_actions"


def test_b7_has_no_full_access_enable_field() -> None:
    store = PermissionStore(persistent=False)
    with pytest.raises(PermissionError):
        store.set_profile("full_access")
    assert PermissionSetRequest.model_fields["method"].default == "permission/set"


def test_default_ask_and_full_rejected_until_enabled() -> None:
    store = PermissionStore(persistent=False)
    asked = store.apply_ui_preset("ask")
    assert asked == {
        "preset": "ask",
        "effective_policy": "ask_for_each_risky_action",
        "writable_roots": [],
    }
    with pytest.raises(PermissionError, match="full_access_not_enabled"):
        store.apply_ui_preset("full")
    enabled = store.enable_full_access(actor="settings-user", source="settings")
    assert enabled["enabled"] is True
    assert enabled["actor"] == "settings-user"
    full = store.apply_ui_preset("full")
    assert full["preset"] == "full"
    assert full["effective_policy"] == "full_access"


def test_restart_clears_full_and_high_risk_preset(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    first = PermissionStore(path, persistent=True)
    first.enable_full_access(actor="u")
    first.apply_ui_preset("full")
    assert first.active_policy() == "full_access"
    second = PermissionStore(path, persistent=True)
    assert second.ui_preset == "ask"
    assert second.active_policy() != "full_access"
    with pytest.raises(PermissionError, match="full_access_not_enabled"):
        second.apply_ui_preset("full")


def test_auto_does_not_persist_as_restart_profile(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    first = PermissionStore(path, persistent=True)
    first.apply_ui_preset("auto")
    assert first.active_policy() == "allow_scoped_actions"
    second = PermissionStore(path, persistent=True)
    assert second.ui_preset == "ask"


@pytest.mark.asyncio
async def test_appserver_mode_set_rpc(monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "approval/mode_set", "params": {"preset": "ask"}}
    )
    ok = next(item["result"] for item in sent if item.get("id") == 1 and "result" in item)
    assert ok["preset"] == "ask"
    assert ok["effective_policy"] == "ask_for_each_risky_action"
    assert "writable_roots" in ok

    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "approval/mode_set", "params": {"preset": "full"}}
    )
    err = next(item["error"] for item in sent if item.get("id") == 2 and "error" in item)
    assert err["data"]["error_code"] == "full_access_not_enabled"

    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "approval/full_access_enable",
            "params": {"actor": "tester", "source": "settings"},
        }
    )
    unlocked = next(item["result"] for item in sent if item.get("id") == 3)
    assert unlocked["enabled"] is True

    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "approval/mode_set", "params": {"preset": "full"}}
    )
    full = next(item["result"] for item in sent if item.get("id") == 4)
    assert full["effective_policy"] == "full_access"
    assert ApprovalFullAccessEnableRequest(actor="tester").method == "approval/full_access_enable"
