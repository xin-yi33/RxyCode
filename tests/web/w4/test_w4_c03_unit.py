"""WEB-W4-C03. Pairing shows the device, and a bad handshake cannot run tools."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import httpx
from click.testing import CliRunner

_SECRET = "local-web-secret-value-32bytes!!"
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


def _authorized(gateway: object, tenant_id: str = "tenant-a") -> tuple[str, dict[str, str], dict[str, str]]:
    token = gateway.browser_session(tenant_id)  # type: ignore[attr-defined]
    csrf = "csrf-token-value-for-c03"
    cookies = {"rxy_session": token, "rxy_csrf": csrf}
    headers = {"Origin": gateway.http, "X-CSRF-Token": csrf}  # type: ignore[attr-defined]
    return token, cookies, headers


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
    gateway = serve_in_thread(secret=_SECRET)
    reset_stop()
    thread: threading.Thread | None = None
    try:
        browser, cookies, headers = _authorized(gateway)
        forged = httpx.post(f"{gateway.http}/api/v1/devices/pairings", timeout=5)
        assert forged.status_code == 403
        unsigned = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers=headers,
            cookies={"rxy_csrf": cookies["rxy_csrf"]},
            timeout=5,
        )
        assert unsigned.status_code == 401
        issued = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers=headers,
            cookies=cookies,
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
                cookies=cookies,
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
            cookies={"rxy_session": device_token},
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
    from rxycode_runner.remote.client import request_stop, reset_stop
    from rxycode_server.devices.gateway import serve_in_thread

    reset_stop()
    plain = CliRunner().invoke(
        cli,
        ["connect", "--url", "ws://cloud.example/socket", "--code", "code", "--device-id", "desk-1"],
    )
    assert plain.exit_code != 0
    assert "TLS_REQUIRED" in plain.output
    clock = {"now": 1_000.0}
    gateway = serve_in_thread(secret=_SECRET, clock=lambda: clock["now"], pairing_ttl=5)
    thread: threading.Thread | None = None
    try:
        _browser, cookies, headers = _authorized(gateway)
        issued = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers=headers,
            cookies=cookies,
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
            cookies=cookies,
            timeout=5,
        )
        assert listed.json()["devices"] == []
        assert gateway.tool_permission("desk-1") is False
        owned_code = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers=headers,
            cookies=cookies,
            timeout=5,
        ).json()["code"]
        reset_stop()
        holder: dict[str, object] = {}

        def launch() -> None:
            holder["result"] = CliRunner().invoke(
                cli,
                [
                    "connect",
                    "--url",
                    gateway.ws,
                    "--code",
                    owned_code,
                    "--device-id",
                    "desk-owned",
                    "--os-name",
                    "Windows",
                    "--heartbeat-seconds",
                    "0.2",
                ],
            )

        thread = threading.Thread(target=launch)
        thread.start()
        deadline = time.time() + 10
        while time.time() < deadline and not gateway.session_id("desk-owned"):
            time.sleep(0.05)
        assert gateway.session_id("desk-owned")
        kept_session = gateway.session_id("desk-owned")
        kept_token = gateway.client_token("desk-owned")
        other = gateway.browser_session("tenant-b")
        other_cookies = {"rxy_session": other, "rxy_csrf": cookies["rxy_csrf"]}
        stolen_code = httpx.post(
            f"{gateway.http}/api/v1/devices/pairings",
            headers=headers,
            cookies=other_cookies,
            timeout=5,
        ).json()["code"]
        stolen = CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,
                "--code",
                stolen_code,
                "--device-id",
                "desk-owned",
                "--os-name",
                "Windows",
            ],
        )
        assert stolen.exit_code != 0
        assert "DEVICE_OWNED" in stolen.output
        assert gateway.session_id("desk-owned") == kept_session
        assert gateway.token_accepted(kept_token) is True
    finally:
        request_stop()
        if thread is not None:
            thread.join(5)
        gateway.close()
