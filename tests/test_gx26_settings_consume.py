"""GX26-B path A: consume B10 settings. No second settings store."""

from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer
from appserver.settings import SettingsService
from protocol.requests import SettingsGetRequest, SettingsSetRequest


def test_settings_methods_exist() -> None:
    assert SettingsGetRequest.model_fields["method"].default == "settings/get"
    assert SettingsSetRequest.model_fields["method"].default == "settings/set"


def test_single_settings_service() -> None:
    server = AppServer(stub=True)
    assert isinstance(server._settings, SettingsService)


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
