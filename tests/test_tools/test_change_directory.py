"""cd 自救通道：工作区降级到 scratch 时允许 cd 到真实项目目录（2026-09-23）。"""
from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.session_runtime import (
    bind_session,
    reset_session_binding,
    set_working_directory,
)
from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory


def test_cd_into_project_outside_workspace_root_allowed(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)

    token = bind_session("cd-self-rescue")
    try:
        set_working_directory(scratch)
        result = change_directory(str(project))
        assert result.startswith("Changed directory to:"), result
        assert "escapes execution.workspace_root" not in result
    finally:
        reset_session_binding(token)


def test_cd_into_plain_dir_outside_workspace_and_home_rejected(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()

    token = bind_session("cd-reject")
    try:
        set_working_directory(scratch)
        result = change_directory(str(plain))
        assert "escapes execution.workspace_root" in result, result
    finally:
        reset_session_binding(token)


def test_cd_inside_workspace_root_still_allowed(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    inner = scratch / "inner"
    inner.mkdir(parents=True)

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.config.settings.load_config",
        lambda: {
            "execution": {
                "sandbox_mode": "workspace",
                "workspace_root": str(scratch),
            }
        },
    )
    token = bind_session("cd-inside")
    try:
        set_working_directory(scratch)
        result = change_directory(str(inner))
        assert result.startswith("Changed directory to:"), result
    finally:
        reset_session_binding(token)
