"""GX28-B path A: consume F18b team/*. Do not invent team RPC."""

from __future__ import annotations

from pathlib import Path

from protocol.requests import (
    TeamGroupRenameRequest,
    TeamGroupsRequest,
    TeamInstallRequest,
    TeamListRequest,
    TeamSetActiveRequest,
)


def test_team_methods_exist() -> None:
    assert TeamListRequest.model_fields["method"].default == "team/list"
    assert TeamGroupsRequest.model_fields["method"].default == "team/groups"
    assert TeamGroupRenameRequest.model_fields["method"].default == "team/group_rename"
    assert TeamInstallRequest.model_fields["method"].default == "team/install"
    assert TeamSetActiveRequest.model_fields["method"].default == "team/set_active"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
