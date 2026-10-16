"""WEB-W4-C04. A repeated call_id replays the result and does not run twice."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

_SECRET = "local-web-secret-value-32bytes!!"
REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
for entry in (str(REPO), str(_RUNNER), str(_WORKER), str(_SERVER)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _ids() -> tuple[str, str]:
    return f"att_{uuid4().hex}", f"call_{uuid4().hex}"


def _pair(gateway: object) -> threading.Thread:
    from click.testing import CliRunner
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import reset_stop

    reset_stop()
    browser = gateway.browser_session("tenant-a")  # type: ignore[attr-defined]
    csrf = "csrf-token-value-for-c04"
    cookies = {"rxy_session": browser, "rxy_csrf": csrf}
    headers = {"Origin": gateway.http, "X-CSRF-Token": csrf}  # type: ignore[attr-defined]
    issued = httpx.post(
        f"{gateway.http}/api/v1/devices/pairings",  # type: ignore[attr-defined]
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
                gateway.ws,  # type: ignore[attr-defined]
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
    deadline = time.time() + 10
    while time.time() < deadline and not gateway.session_id("desk-1"):  # type: ignore[attr-defined]
        time.sleep(0.05)
    if not gateway.session_id("desk-1"):  # type: ignore[attr-defined]
        raise AssertionError(holder.get("result"))
    return thread


def test_w4_c04_contract(tmp_path: Path) -> None:
    """A second invoke of a completed call returns the first result."""
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.runner_client import dispatch_device_call

    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    note = tmp_path / "note.txt"
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    _attempt_a, call_id = _ids()
    attempt_b = f"att_{uuid4().hex}"
    try:
        first = dispatch_device_call(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=_attempt_a,
            tool="write",
            args={"path": str(note), "text": "once"},
        )
        second = dispatch_device_call(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_b,
            tool="write",
            args={"path": str(note), "text": "once"},
        )
        assert first.state == "completed"
        assert first.result == "once"
        assert second.state == "completed"
        assert second.result == "once"
        assert note.read_text(encoding="utf-8") == "once"
        call_left = f"call_{uuid4().hex}"
        call_right = f"call_{uuid4().hex}"
        found: dict[str, object] = {}

        def one(name: str, call: str, path: Path, text: str) -> None:
            found[name] = dispatch_device_call(
                gateway=gateway,
                device_id="desk-1",
                call_id=call,
                attempt_id=f"att_{uuid4().hex}",
                tool="write",
                args={"path": str(path), "text": text},
            )

        pair = (
            threading.Thread(target=one, args=("left", call_left, left, "A")),
            threading.Thread(target=one, args=("right", call_right, right, "B")),
        )
        for item in pair:
            item.start()
        for item in pair:
            item.join(10)
        assert getattr(found["left"], "result", None) == "A"
        assert getattr(found["right"], "result", None) == "B"
        assert left.read_text(encoding="utf-8") == "A"
        assert right.read_text(encoding="utf-8") == "B"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")


def test_w4_c04_negative(tmp_path: Path) -> None:
    """A lost result ack stays unknown and does not write again."""
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import cancel_started, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.runner_client import dispatch_device_call, dispatch_device_cancel

    target = tmp_path / "side.txt"
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    attempt_id, call_id = _ids()
    try:
        dropped = dispatch_device_call(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"mode": "write", "path": str(target)},
            ack=False,
        )
        assert dropped.state == "unacked"
        assert target.read_text(encoding="utf-8") == "W"
        retried = dispatch_device_call(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=f"att_{uuid4().hex}",
            tool="write",
            args={"mode": "write", "path": str(target)},
        )
        assert retried.state == "recovery_required"
        assert target.read_text(encoding="utf-8") == "W"
        cancel_attempt, cancel_call = _ids()
        cancelled = dispatch_device_cancel(
            gateway=gateway,
            device_id="desk-1",
            call_id=cancel_call,
            attempt_id=cancel_attempt,
            tool="write",
            args={"mode": "cancel", "path": str(target)},
            started=cancel_started(),
        )
        assert cancelled.state == "cancelled"
        assert target.read_text(encoding="utf-8") == "W"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")
