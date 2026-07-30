from __future__ import annotations

import click
import pytest

from RxyCode.RxyCode1_1_0 import main


def test_resolve_tui_backend_forces_ink(monkeypatch):
    monkeypatch.setenv("RXYCODE_TUI", "ink")
    monkeypatch.setattr(main, "_bun_executable", lambda: "/fake/bun")
    monkeypatch.setattr(main, "_opentui_ready", lambda: True)
    assert main._resolve_tui_backend() == "ink"


def test_resolve_tui_backend_forces_opentui_without_bun_errors(monkeypatch):
    monkeypatch.setenv("RXYCODE_TUI", "opentui")
    monkeypatch.setenv("RXYCODE_SKIP_BUN_INSTALL", "1")
    monkeypatch.setattr(main, "_bun_executable", lambda: None)
    monkeypatch.setattr(main, "_opentui_ready", lambda: True)
    with pytest.raises(click.ClickException, match="required by the OpenTUI|requires Bun|Bun"):
        main._resolve_tui_backend()


def test_resolve_tui_backend_forces_opentui_without_app_errors(monkeypatch):
    monkeypatch.setenv("RXYCODE_TUI", "opentui")
    monkeypatch.setattr(main, "_bun_executable", lambda: "/fake/bun")
    monkeypatch.setattr(main, "_opentui_ready", lambda: False)
    with pytest.raises(click.ClickException, match="frontend/opentui-app"):
        main._resolve_tui_backend()


def test_resolve_tui_backend_defaults_to_opentui_when_bun_ready(monkeypatch):
    monkeypatch.delenv("RXYCODE_TUI", raising=False)
    monkeypatch.setattr(main, "_bun_executable", lambda: "/fake/bun")
    monkeypatch.setattr(main, "_opentui_ready", lambda: True)
    assert main._resolve_tui_backend() == "opentui"


def test_resolve_tui_backend_defaults_to_ink_without_bun(monkeypatch):
    monkeypatch.delenv("RXYCODE_TUI", raising=False)
    monkeypatch.setenv("RXYCODE_SKIP_BUN_INSTALL", "1")
    monkeypatch.setattr(main, "_bun_executable", lambda: None)
    monkeypatch.setattr(main, "_opentui_ready", lambda: True)
    assert main._resolve_tui_backend() == "ink"
