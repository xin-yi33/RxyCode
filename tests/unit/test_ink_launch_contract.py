from __future__ import annotations

import sys
from unittest.mock import Mock

import click
import pytest

from RxyCode.RxyCode1_1_0 import entrypoint, main


def test_console_entrypoint_keeps_ink_as_the_default(monkeypatch):
    cli_main = Mock()
    monkeypatch.setattr(entrypoint.cli, "main", cli_main)
    monkeypatch.setattr(sys, "argv", ["rxycode"])

    entrypoint.main()

    cli_main.assert_called_once_with(args=[], prog_name="rxycode")


def test_api_readiness_probe_sends_bearer_token(monkeypatch):
    captured_request = None

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        nonlocal captured_request
        captured_request = request
        assert timeout == 2
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert main._wait_for_api_ready(8765, token="test-token", timeout=0.1)
    assert captured_request is not None
    assert captured_request.full_url == "http://127.0.0.1:8765/status"
    assert captured_request.get_header("Authorization") == "Bearer test-token"


def test_missing_node_fails_before_starting_api(monkeypatch):
    api_started = False

    def fake_api_server(**kwargs):
        nonlocal api_started
        api_started = True

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.api_server.run_api_server",
        fake_api_server,
    )
    monkeypatch.setattr("shutil.which", lambda executable: None)

    with pytest.raises(click.ClickException, match="Node.js 20 or newer"):
        main._launch_ink_tui(model=None, port=8765)

    assert not api_started


def test_ink_process_nonzero_exit_is_propagated(monkeypatch):
    process = Mock(pid=1234)
    process.wait.return_value = 7
    process.poll.return_value = 7

    monkeypatch.setattr(main, "_find_available_port", lambda port: port)
    monkeypatch.setattr(main, "_wait_for_api_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.api_server.run_api_server",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("shutil.which", lambda executable: "node" if executable == "node" else None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)

    with pytest.raises(click.ClickException, match="exited with status 7"):
        main._launch_ink_tui(model=None, port=8765)


def test_cli_has_no_legacy_python_frontend_option():
    option_names = {
        name
        for parameter in main.cli.params
        for name in parameter.opts + parameter.secondary_opts
    }

    assert "--python" not in option_names


def test_main_has_no_legacy_frontend_controller():
    assert not hasattr(main, "RxyCodeApp")


def test_tui_module_only_exposes_backend_output_adapter():
    from RxyCode.RxyCode1_1_0.utils import tui

    assert not hasattr(tui, "RxyCodeTextualApp")
    assert not hasattr(tui, "RxyCodeFallbackTUI")
    assert not hasattr(tui, "create_tui")
