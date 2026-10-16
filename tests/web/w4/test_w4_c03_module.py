"""WEB-W4-C03. A dropped cloud socket reconnects as a new session at the same scope."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
for entry in (str(_RUNNER), str(_SERVER)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def test_w4_c03_integration() -> None:
    """After the cloud socket drops, reconnect uses a new session and the same scope."""
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import request_stop, reset_stop
    from rxycode_server.devices.gateway import serve_in_thread

    gateway = serve_in_thread()
    reset_stop()
    thread: threading.Thread | None = None
    try:
        opened = httpx.post(
            f"{gateway.http}/api/v1/devices/browser-sessions",
            json={"tenant_id": "tenant-a"},
            timeout=5,
        )
        browser = opened.json()["token"]
        issued = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers={"Authorization": f"Bearer {browser}"},
            timeout=5,
        )
        code = issued.json()["code"]

        def launch() -> None:
            CliRunner().invoke(
                cli,
                [
                    "connect",
                    "--url",
                    gateway.ws,
                    "--code",
                    code,
                    "--device-id",
                    "desk-1",
                    "--os-name",
                    "Windows",
                    "--capability",
                    "click",
                    "--heartbeat-seconds",
                    "0.2",
                ],
            )

        thread = threading.Thread(target=launch)
        thread.start()
        first = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            first = gateway.session_id("desk-1")
            if first:
                break
            time.sleep(0.05)
        assert first
        first_token = gateway.client_token("desk-1")
        gateway.drop()
        second = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            second = gateway.session_id("desk-1")
            if second and second != first:
                break
            time.sleep(0.05)
        assert second
        assert second != first
        assert gateway.scope("desk-1") == "device"
        assert gateway.client_token("desk-1") != first_token
        assert gateway.token_accepted(first_token) is False
        assert gateway.writer_count("desk-1") == 1
    finally:
        request_stop()
        if thread is not None:
            thread.join(5)
        gateway.close()
