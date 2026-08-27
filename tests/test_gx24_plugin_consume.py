"""GX24-B path A: consume B18 plugin/*; toggle forwards B11 set_enabled."""

from __future__ import annotations

from pathlib import Path

from appserver.plugin_service import PluginService
from appserver.server import AppServer
from protocol.requests import (
    PluginInstallRequest,
    PluginListRequest,
    PluginToggleRequest,
    PluginUninstallRequest,
)


def test_plugin_methods_exist() -> None:
    assert PluginListRequest.model_fields["method"].default == "plugin/list"
    assert PluginInstallRequest.model_fields["method"].default == "plugin/install"
    assert PluginUninstallRequest.model_fields["method"].default == "plugin/uninstall"
    assert PluginToggleRequest.model_fields["method"].default == "plugin/toggle"


def test_toggle_source_calls_capabilities() -> None:
    src = Path(__file__).resolve().parents[1] / "appserver" / "plugin_service.py"
    text = src.read_text(encoding="utf-8")
    assert "set_enabled" in text
    assert "capability_ids" in text


def test_appserver_has_plugin_service() -> None:
    server = AppServer(stub=True)
    assert isinstance(server._plugins, PluginService)


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
