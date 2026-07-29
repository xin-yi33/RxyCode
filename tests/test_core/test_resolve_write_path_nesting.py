"""resolve_write_path must not double-nest output/date directories."""
from __future__ import annotations

from pathlib import Path

from RxyCode.RxyCode1_1_0.core.session_runtime import (
    _strip_redundant_output_prefix,
    bind_session,
    reset_session_binding,
    resolve_write_path,
    set_working_directory,
)


def test_strip_redundant_output_date_prefix(tmp_path):
    output_dir = tmp_path / "output" / "2026-07-28"
    output_dir.mkdir(parents=True)
    relative = Path("output") / "2026-07-28" / "parkour_game.html"
    stripped = _strip_redundant_output_prefix(relative, output_dir)
    assert stripped == Path("parkour_game.html")


def test_resolve_write_path_no_double_nest(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Force dated output dir
    dated = tmp_path / "data" / "output" / "2026-07-28"
    dated.mkdir(parents=True)

    token = bind_session("write-path-test")
    try:
        set_working_directory(workspace)
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.core.session_runtime.get_output_dir",
            lambda: dated,
        )
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.config.settings.get_output_dir",
            lambda: dated,
        )
        resolved = resolve_write_path("output/2026-07-28/parkour_game.html")
        assert resolved == (dated / "parkour_game.html").resolve()
        assert "output" not in resolved.relative_to(dated).parts
    finally:
        reset_session_binding(token)


def test_resolve_write_path_bare_name(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    dated = tmp_path / "data" / "output" / "2026-07-28"
    dated.mkdir(parents=True)
    token = bind_session("write-path-bare")
    try:
        set_working_directory(workspace)
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.core.session_runtime.get_output_dir",
            lambda: dated,
        )
        resolved = resolve_write_path("parkour_game.html")
        assert resolved == (dated / "parkour_game.html").resolve()
    finally:
        reset_session_binding(token)
