"""GX25-B path A: consume B14 cli/list|install|launch. cli: stays out of tools registry."""

from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer
from protocol.requests import CliInstallRequest, CliLaunchRequest, CliListRequest


def test_cli_methods_exist() -> None:
    assert CliListRequest.model_fields["method"].default == "cli/list"
    assert CliInstallRequest.model_fields["method"].default == "cli/install"
    assert CliLaunchRequest.model_fields["method"].default == "cli/launch"


def test_cli_prefix_not_in_tools_registry() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = root / "tools" / "registry.py"
    text = registry.read_text(encoding="utf-8") if registry.exists() else ""
    assert "cli:" not in text


def test_appserver_has_cli_hub() -> None:
    server = AppServer(stub=True)
    assert server._cli_hub is not None


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
