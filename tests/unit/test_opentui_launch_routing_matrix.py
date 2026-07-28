"""OpenTUI vs Ink launch routing matrices."""

from __future__ import annotations

import itertools

import click
import pytest

from RxyCode.RxyCode1_1_0 import main


_PREFS = ("ink", "opentui", "", "INK", " OpenTUI ")
_BUN = (None, "/fake/bun")
_READY = (True, False)


@pytest.mark.parametrize(
    ("pref", "bun", "ready", "expected"),
    [
        ("ink", None, False, "ink"),
        ("ink", "/fake/bun", True, "ink"),
        ("", None, True, "ink"),
        ("", "/fake/bun", True, "opentui"),
        ("", "/fake/bun", False, "ink"),
        ("opentui", "/fake/bun", True, "opentui"),
    ],
)
def test_resolve_tui_backend_matrix(monkeypatch, pref: str, bun, ready, expected: str):
    if pref.strip():
        monkeypatch.setenv("RXYCODE_TUI", pref)
    else:
        monkeypatch.delenv("RXYCODE_TUI", raising=False)
    monkeypatch.setattr(main, "_bun_executable", lambda: bun)
    monkeypatch.setattr(main, "_opentui_ready", lambda: ready)
    assert main._resolve_tui_backend() == expected


@pytest.mark.parametrize(
    ("ready",),
    [(False,), (True,)],
)
def test_opentui_forced_without_bun_errors(monkeypatch, ready: bool):
    monkeypatch.setenv("RXYCODE_TUI", "opentui")
    monkeypatch.setattr(main, "_bun_executable", lambda: None)
    monkeypatch.setattr(main, "_opentui_ready", lambda: ready)
    with pytest.raises(click.ClickException, match="requires Bun"):
        main._resolve_tui_backend()


@pytest.mark.parametrize("bun", ("/fake/bun", "C:/tools/bun.exe"))
def test_opentui_forced_without_app_errors(monkeypatch, bun: str):
    monkeypatch.setenv("RXYCODE_TUI", "opentui")
    monkeypatch.setattr(main, "_bun_executable", lambda: bun)
    monkeypatch.setattr(main, "_opentui_ready", lambda: False)
    with pytest.raises(click.ClickException, match="frontend/opentui-app"):
        main._resolve_tui_backend()


@pytest.mark.parametrize(
    ("env_value", "bun", "ready"),
    itertools.product(_PREFS, _BUN, _READY),
)
def test_resolve_never_raises_unless_forced_opentui(monkeypatch, env_value: str, bun, ready: bool):
    stripped = env_value.strip().lower()
    monkeypatch.setenv("RXYCODE_TUI", env_value)
    monkeypatch.setattr(main, "_bun_executable", lambda: bun)
    monkeypatch.setattr(main, "_opentui_ready", lambda: ready)
    if stripped == "opentui" and (not bun or not ready):
        with pytest.raises(click.ClickException):
            main._resolve_tui_backend()
    else:
        backend = main._resolve_tui_backend()
        assert backend in {"ink", "opentui"}
