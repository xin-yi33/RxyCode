"""WEB-W4-C03. Pairing shows the device, and a bad handshake cannot run tools."""

from __future__ import annotations

import logging
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


def _capture_logs() -> tuple[logging.Handler, list[str]]:
    found: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            found.append(record.getMessage())

    handler = _Grab()
    for name in ("rxycode_runner.remote.client", "rxycode_server.devices.gateway"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    return handler, found


def test_w4_c03_contract() -> None:
    """A local connect with an authorized pairing shows device, OS, and capability."""
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import request_stop, reset_stop, tls_context_for
    from rxycode_server.devices.gateway import serve_in_thread

    import ssl

    context = tls_context_for("wss://cloud.example/api/v1/devices/socket")
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True

    handler, lines = _capture_logs()
    gateway = serve_in_thread()
    reset_stop()
    thread: threading.Thread | None = None
    try:
        opened = httpx.post(
            f"{gateway.http}/api/v1/devices/browser-sessions",
            json={"tenant_id": "tenant-a"},
            timeout=5,
        )
        opened.raise_for_status()
        browser = opened.json()["token"]
        issued = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers={"Authorization": f"Bearer {browser}"},
            timeout=5,
        )
        issued.raise_for_status()
        code = issued.json()["code"]
        holder: dict[str, object] = {}

        def launch() -> None:
            holder["result"] = CliRunner().invoke(
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
        listed: list[dict[str, object]] = []
        deadline = time.time() + 10
        while time.time() < deadline:
            response = httpx.get(
                f"{gateway.http}/api/v1/devices",
                headers={"Authorization": f"Bearer {browser}"},
                timeout=5,
            )
            response.raise_for_status()
            listed = response.json()["devices"]
            if listed:
                break
            time.sleep(0.05)
        assert listed == [
            {
                "id": "desk-1",
                "os": "Windows",
                "capabilities": ["click"],
                "scope": "device",
                "online": True,
            }
        ]
        device_token = gateway.client_token("desk-1")
        assert device_token
        assert device_token != browser
        denied = httpx.get(
            f"{gateway.http}/api/v1/devices",
            headers={"Authorization": f"Bearer {device_token}"},
            timeout=5,
        )
        assert denied.status_code == 401
        assert device_token not in "\n".join(lines)
        assert gateway.writer_count("desk-1") == 1
    finally:
        request_stop()
        if thread is not None:
            thread.join(5)
        gateway.close()
        for name in ("rxycode_runner.remote.client", "rxycode_server.devices.gateway"):
            logging.getLogger(name).removeHandler(handler)


def test_w4_c03_negative() -> None:
    """An expired pairing code and a wrong token are refused without tool permission."""
    from click.testing import CliRunner
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import reset_stop
    from rxycode_server.devices.gateway import serve_in_thread

    reset_stop()
    clock = {"now": 1_000.0}
    gateway = serve_in_thread(clock=lambda: clock["now"], pairing_ttl=5)
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
        clock["now"] = 1_010.0
        expired = CliRunner().invoke(
            cli,
            ["connect", "--url", gateway.ws, "--code", code, "--device-id", "desk-1"],
        )
        assert expired.exit_code != 0
        assert "PAIRING_EXPIRED" in expired.output
        wrong = CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,
                "--token",
                "not-a-device-token",
                "--device-id",
                "desk-1",
            ],
        )
        assert wrong.exit_code != 0
        assert "BAD_TOKEN" in wrong.output
        version = CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,
                "--code",
                code,
                "--device-id",
                "desk-1",
                "--protocol-version",
                "9.9.9",
            ],
        )
        assert version.exit_code != 0
        assert "BAD_VERSION" in version.output
        listed = httpx.get(
            f"{gateway.http}/api/v1/devices",
            headers={"Authorization": f"Bearer {browser}"},
            timeout=5,
        )
        assert listed.json()["devices"] == []
        assert gateway.tool_permission("desk-1") is False
    finally:
        gateway.close()
