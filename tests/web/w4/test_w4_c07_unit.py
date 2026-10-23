"""WEB-W4-C07. A fresh Windows install can start connect, and unverified OS stays unverified."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

_SECRET = "local-web-secret-value-32bytes!!"
REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "packages" / "rxycode-runner"
for entry in (
    REPO,
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _connect_script(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "rxycode-connect.exe"
    return venv / "bin" / "rxycode-connect"


def test_w4_c07_contract(tmp_path: Path) -> None:
    """Installing the runner into a new venv starts the outbound device socket."""
    from rxycode_runner.desktop.capabilities import release_status
    from rxycode_server.devices.gateway import serve_in_thread

    windows = release_status({"windows"})
    assert windows["windows"] == "supported"
    assert windows["macos"] == "unverified"
    assert windows["linux"] == "unverified"
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=120)
    python = _venv_python(venv)
    installed = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(RUNNER)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    script = _connect_script(venv)
    assert script.is_file()
    gateway = serve_in_thread(secret=_SECRET)
    browser = gateway.browser_session("tenant-a")
    csrf = "csrf-token-value-for-c07"
    issued = httpx.post(
        f"{gateway.http}/api/v1/devices/pairings",
        headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
        cookies={"rxy_session": browser, "rxy_csrf": csrf},
        timeout=5,
    )
    issued.raise_for_status()
    process = subprocess.Popen(
        [
            str(script),
            "connect",
            "--url",
            gateway.ws,
            "--code",
            issued.json()["code"],
            "--device-id",
            "desk-c07",
            "--os-name",
            "Windows",
            "--capability",
            "click",
            "--heartbeat-seconds",
            "0.2",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not gateway.session_id("desk-c07"):
            time.sleep(0.05)
        detail = ""
        if process.poll() is not None:
            out, err = process.communicate(timeout=5)
            detail = (out or "") + (err or "")
        assert gateway.session_id("desk-c07"), detail or process.poll()
        assert gateway.scope("desk-c07") == "device"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        gateway.close()


def test_w4_c07_negative() -> None:
    """A Windows-only run does not mark macOS or Linux supported."""
    from rxycode_runner.desktop.capabilities import release_status

    labels = release_status({"windows"})
    assert labels["macos"] == "unverified"
    assert labels["linux"] == "unverified"
    assert labels["macos"] != "supported"
    assert labels["linux"] != "supported"
    assert "supported" not in labels["macos"]
    assert "supported" not in labels["linux"]
