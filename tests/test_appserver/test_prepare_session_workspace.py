from __future__ import annotations

from pathlib import Path

import pytest

from appserver.workspace import PathBoundaryError, prepare_session_workspace


def test_recent_rxycode_dir_is_created_and_not_registered_as_project(tmp_path: Path) -> None:
    recent = tmp_path / ".RxyCode"
    assert recent.exists() is False
    path, register_as_project = prepare_session_workspace(recent)
    assert path == recent.resolve()
    assert recent.is_dir()
    assert register_as_project is False


def test_existing_project_folder_is_registered(tmp_path: Path) -> None:
    project = tmp_path / "paper"
    project.mkdir()
    path, register_as_project = prepare_session_workspace(project)
    assert path == project.resolve()
    assert register_as_project is True


def test_missing_project_folder_still_fails(tmp_path: Path) -> None:
    missing = tmp_path / "missing-project"
    with pytest.raises(PathBoundaryError) as exc:
        prepare_session_workspace(missing)
    assert exc.value.code == "PATH_NOT_FOUND"
