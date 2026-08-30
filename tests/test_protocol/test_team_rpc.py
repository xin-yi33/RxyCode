"""F18b team/* RPC."""

from __future__ import annotations

from pathlib import Path

from RxyCode.RxyCode1_1_0.appserver.team_routes import (
    team_group_rename,
    team_groups,
    team_install_rpc,
    team_list,
    team_set_active,
)
from RxyCode.RxyCode1_1_0.core.agents.importer import write_sample_package
from RxyCode.RxyCode1_1_0.core.agents.registry import TeamRegistry
from RxyCode.RxyCode1_1_0.protocol.requests import (
    TeamGroupRenameRequest,
    TeamGroupsRequest,
    TeamInstallRequest,
    TeamListRequest,
    TeamSetActiveRequest,
)
from RxyCode.RxyCode1_1_0.protocol.schema import export_schema


def test_team_list_is_l1_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    write_sample_package(tmp_path / "teams" / "shown", name="shown")
    TeamRegistry(root=tmp_path / "teams")
    payload = team_list()
    row = payload["teams"][0]
    assert "summary" in row
    assert "位角色" in row["summary"]
    assert isinstance(row.get("members"), list)
    assert isinstance(row.get("stages"), list)
    assert isinstance(row.get("extra"), dict)


def test_install_reuses_f18_two_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    first = team_install_rpc({"name": "rpc-team"})
    assert "ASK_CONFIRM" in first["message"]
    second = team_install_rpc({"name": "rpc-team", "confirm": True, "group": "other"})
    assert "installed" in second["message"]


def test_set_active_idempotent_and_allows_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    write_sample_package(tmp_path / "teams" / "hidden", name="hidden", disable_model=True)
    TeamRegistry(root=tmp_path / "teams")
    first = team_set_active({"session_id": "s", "team_id": "hidden"})
    assert first["ok"] and first["changed"] is True
    again = team_set_active({"session_id": "s", "team_id": "hidden"})
    assert again["ok"] and again["changed"] is False
    missing = team_set_active({"session_id": "s", "team_id": "nope"})
    assert missing["ok"] is False


def test_builtin_rename_and_unknown_are_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    TeamRegistry(root=tmp_path / "teams")
    payload = team_group_rename({"old": "other", "new": "x"})
    assert payload["ok"] is False
    groups = team_groups()
    assert any(g["builtin"] for g in groups["groups"])


def test_five_methods_are_in_schema() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "TeamListRequest",
        "TeamGroupsRequest",
        "TeamGroupRenameRequest",
        "TeamInstallRequest",
        "TeamSetActiveRequest",
    ):
        assert name in defs
    assert TeamListRequest().method == "team/list"
    assert TeamGroupsRequest().method == "team/groups"
    assert TeamInstallRequest(name="x").method == "team/install"
    assert TeamGroupRenameRequest(old="a", new="b").method == "team/group_rename"
    assert TeamSetActiveRequest(session_id="s", team_id="t").method == "team/set_active"


def test_no_appserver_handlers_dir() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "appserver" / "handlers").exists()
