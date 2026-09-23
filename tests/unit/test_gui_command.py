"""rxycode gui command tests (Phase 4 desktop quick entry).

The gui command must:
- resolve the desktop executable from: explicit --desktop-dir, then
  ~/.rxycode/desktop, then PATH (rxycode-desktop).
- fall back to launching frontend/desktop-app with npm run dev when no
  packaged desktop is found.
- never touch the CLI path (rxycode stays the CLI entry).
"""

from __future__ import annotations

import os

import click
import pytest
from click.testing import CliRunner

from RxyCode.RxyCode1_1_0 import main


def test_resolve_desktop_exe_explicit_dir(tmp_path, monkeypatch):
    exe = tmp_path / "rxycode-desktop.exe"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)  # packaged builds are executable; os.access(X_OK) gates resolution
    resolved = main._resolve_desktop_executable(desktop_dir=str(tmp_path))
    assert resolved == str(exe)


def test_resolve_desktop_exe_inside_portable_zip_wrapper(tmp_path):
    """Official win.zip extracts to RxyCode.Desktop-<ver>-win/rxycode-desktop.exe."""
    wrapper = tmp_path / "RxyCode.Desktop-1.3.0-win"
    wrapper.mkdir()
    exe = wrapper / "rxycode-desktop.exe"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    assert main._resolve_desktop_executable(desktop_dir=str(tmp_path)) == str(exe)
    assert main._resolve_desktop_executable(desktop_dir=str(wrapper)) == str(exe)
    assert main._resolve_desktop_executable(desktop_dir=str(exe)) == str(exe)


def test_resolve_desktop_exe_default_dir(monkeypatch, tmp_path):
    home = tmp_path / "home"
    desktop = home / ".rxycode" / "desktop"
    desktop.mkdir(parents=True)
    exe = desktop / "rxycode-desktop.exe"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    resolved = main._resolve_desktop_executable()
    assert resolved == str(exe)


def test_resolve_desktop_exe_missing_returns_none(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert main._resolve_desktop_executable() is None


def test_resolve_desktop_exe_posix_name(monkeypatch, tmp_path):
    desktop = tmp_path / ".rxycode" / "desktop"
    desktop.mkdir(parents=True)
    exe = desktop / "rxycode-desktop"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    resolved = main._resolve_desktop_executable()
    assert resolved == str(exe)


def test_resolve_desktop_exe_portable_zip_wrapper(tmp_path):
    """v1.3.0 win zip extracts to RxyCode.Desktop-<ver>-win/rxycode-desktop.exe."""
    wrapper = tmp_path / "RxyCode.Desktop-1.3.0-win"
    wrapper.mkdir()
    exe = wrapper / "rxycode-desktop.exe"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    assert main._resolve_desktop_executable(desktop_dir=str(wrapper)) == str(exe)
    dropped = tmp_path / "desktop"
    dropped.mkdir()
    nested = dropped / "RxyCode.Desktop-1.3.0-win"
    nested.mkdir()
    nested_exe = nested / "rxycode-desktop.exe"
    nested_exe.write_text("", encoding="utf-8")
    nested_exe.chmod(0o755)
    assert main._resolve_desktop_executable(desktop_dir=str(dropped)) == str(nested_exe)


def test_resolve_desktop_exe_macos_app_bundle(tmp_path):
    macos_dir = tmp_path / "RxyCode Desktop.app" / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    exe = macos_dir / "RxyCode Desktop"
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    assert main._resolve_desktop_executable(desktop_dir=str(tmp_path)) == str(exe)
    parent = tmp_path / "dropped"
    bundled = parent / "RxyCode Desktop.app" / "Contents" / "MacOS"
    bundled.mkdir(parents=True)
    nested_exe = bundled / "RxyCode Desktop"
    nested_exe.write_text("", encoding="utf-8")
    nested_exe.chmod(0o755)
    assert main._resolve_desktop_executable(desktop_dir=str(parent)) == str(nested_exe)


def test_resolve_desktop_exe_appimage_and_direct_file(tmp_path):
    image = tmp_path / "rxycode-desktop-1.3.0.AppImage"
    image.write_text("", encoding="utf-8")
    image.chmod(0o644)
    assert main._resolve_desktop_executable(desktop_dir=str(tmp_path)) == str(image)
    assert main._resolve_desktop_executable(desktop_dir=str(image)) == str(image)


def test_packaged_desktop_popen_spec_prepares_linux_appimage(tmp_path, monkeypatch):
    image = tmp_path / "rxycode-desktop-1.3.0.AppImage"
    image.write_text("", encoding="utf-8")
    image.chmod(0o644)
    monkeypatch.delenv("APPIMAGE_EXTRACT_AND_RUN", raising=False)
    cmd, env = main._packaged_desktop_popen_spec(str(image))
    assert cmd == [str(image)]
    assert env["APPIMAGE_EXTRACT_AND_RUN"] == "1"
    if os.name != "nt":
        assert image.stat().st_mode & 0o111


def test_packaged_desktop_popen_spec_leaves_windows_exe_env_alone(tmp_path, monkeypatch):
    exe = tmp_path / "rxycode-desktop.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.delenv("APPIMAGE_EXTRACT_AND_RUN", raising=False)
    cmd, env = main._packaged_desktop_popen_spec(str(exe))
    assert cmd == [str(exe)]
    assert "APPIMAGE_EXTRACT_AND_RUN" not in env


def test_gui_without_packaged_or_sources_points_to_release(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_resolve_desktop_executable", lambda d=None: None)
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))

    with pytest.raises(click.ClickException) as exc:
        main.gui.callback(desktop_dir=None)

    message = str(exc.value)
    assert "does not include the Electron app" in message
    assert f"releases/tag/v{main.__version__}" in message
    assert "RXYCODE_DESKTOP_DIR" in message
    assert "RxyCode.Desktop-" in message


def test_gui_falls_back_to_dev_without_packaged_build(monkeypatch, tmp_path):
    """No packaged desktop -> dev fallback must spawn npm in desktop-app."""
    import subprocess

    spawned: list[list[str]] = []

    def _fake_popen(cmd, **kwargs):
        spawned.append(cmd)
        return type("P", (), {"wait": lambda self: 0, "terminate": lambda self: None})()

    monkeypatch.setattr(main, "_resolve_desktop_executable", lambda d=None: None)
    monkeypatch.setattr(main, "_npm_executable", lambda: "/fake/npm")
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    # Invoke the underlying command callback (the click-wrapped object is a
    # Command instance; its .callback is the plain function).
    main.gui.callback(desktop_dir=str(tmp_path / "missing"))
    assert spawned and spawned[0][-2:] == ["run", "dev"]


@pytest.mark.parametrize("command", ["GUI", "Gui", "gUi"])
def test_gui_subcommand_is_case_insensitive(monkeypatch, command):
    """Desktop launch aliases must not alter option values or command behavior."""
    import subprocess

    spawned: list[list[str]] = []

    def _fake_popen(cmd, **kwargs):
        spawned.append(cmd)
        return type("P", (), {"wait": lambda self: 0, "terminate": lambda self: None})()

    monkeypatch.setattr(main, "_resolve_desktop_executable", lambda d=None: None)
    monkeypatch.setattr(main, "_npm_executable", lambda: "/fake/npm")
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = CliRunner().invoke(main.cli, [command])

    assert result.exit_code == 0, result.output
    assert spawned and spawned[0][-2:] == ["run", "dev"]
