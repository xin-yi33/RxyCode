"""WEB-W1-C05. Existing CLI help stays, and web help says it is not delivered."""
from __future__ import annotations

from click.testing import CliRunner

from RxyCode.RxyCode1_1_0.main import cli


def test_w1_c05_integration():
    """rxycode --help keeps gui/config, and web --help states the reserved command."""
    runner = CliRunner()
    top = runner.invoke(cli, ["--help"])
    assert top.exit_code == 0, top.output
    assert "gui" in top.output
    assert "config" in top.output
    assert "--model" in top.output
    web = runner.invoke(cli, ["web", "--help"])
    assert web.exit_code == 0, web.output
    assert "connect" in web.output
    assert "not delivered" in web.output.casefold()
    connect = runner.invoke(cli, ["web", "connect", "--help"])
    assert connect.exit_code == 0, connect.output
    assert "not implemented" in connect.output.casefold()
