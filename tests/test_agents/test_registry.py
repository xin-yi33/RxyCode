"""F18 TeamRegistry scan / groups / route index."""

from __future__ import annotations

from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.agents.importer import write_sample_package
from RxyCode.RxyCode1_1_0.core.agents.registry import (
    DESCRIPTION_LIMIT,
    TeamRegistry,
    TeamRegistryError,
    model_may_see,
    route_blurb,
)
from RxyCode.RxyCode1_1_0.core.agents.spec import validate_team


def test_scan_rejects_invalid_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    bad = tmp_path / "teams" / "bad"
    bad.mkdir(parents=True)
    (bad / "team.yaml").write_text("name: bad\n", encoding="utf-8")
    with pytest.raises(TeamRegistryError):
        TeamRegistry(root=tmp_path / "teams")


def test_groups_delete_moves_to_other(tmp_path: Path) -> None:
    root = tmp_path / "teams"
    write_sample_package(root / "demo", name="demo")
    registry = TeamRegistry(root=root)
    registry.assign_group("demo", "labs")
    assert "demo" in registry.groups["labs"]
    registry.delete_group("labs")
    assert "demo" in registry.groups["other"]
    with pytest.raises(TeamRegistryError):
        registry.delete_group("other")
    with pytest.raises(TeamRegistryError):
        registry.rename_group("builtin", "x")
    registry.assign_group("demo", "labs")
    registry.rename_group("labs", "studio")
    assert "demo" in registry.groups["studio"]


def test_disable_model_invocation_hidden_from_auto(tmp_path: Path) -> None:
    root = tmp_path / "teams"
    write_sample_package(root / "hidden", name="hidden", disable_model=True)
    write_sample_package(root / "shown", name="shown")
    registry = TeamRegistry(root=root)
    visible = {t.name for t in registry.auto_visible()}
    assert "shown" in visible
    assert "hidden" not in visible
    hidden = registry.records["hidden"].team
    assert not model_may_see(hidden)
    assert len(route_blurb(hidden)) <= DESCRIPTION_LIMIT
    validate_team(hidden)
    assert "ecosystem.category" in hidden.extra


def test_builtin_software_dev_is_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    registry = TeamRegistry(root=tmp_path / "teams")
    assert "software_dev" in registry.records
    assert registry.records["software_dev"].group == "builtin"
    assert "software_dev" in registry.groups["builtin"]


def test_f18_surface_does_not_import_agent_event() -> None:
    from pathlib import Path

    import RxyCode.RxyCode1_1_0.core.agents.registry as registry_mod

    text = Path(registry_mod.__file__).read_text(encoding="utf-8")
    assert "AgentEvent" not in text
