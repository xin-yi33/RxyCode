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
    from rxycode_worker.supervisor import attempt_tool

    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    note = tmp_path / "note.txt"
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    _attempt_a, call_id = _ids()
    attempt_b = f"att_{uuid4().hex}"
    try:
        first = attempt_tool(
            None, _attempt_a, "write", {"path": str(note), "text": "once"}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id,
        )
        second = attempt_tool(
            None, attempt_b, "write", {"path": str(note), "text": "once"}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id,
        )
        assert first["state"] == "completed"
        assert first["result"] == "once"
        assert second["state"] == "completed"
        assert second["result"] == "once"
        assert note.read_text(encoding="utf-8") == "once"
        call_left = f"call_{uuid4().hex}"
        call_right = f"call_{uuid4().hex}"
        found: dict[str, object] = {}

        def one(name: str, call: str, path: Path, text: str) -> None:
            found[name] = attempt_tool(
                None, f"att_{uuid4().hex}", "write", {"path": str(path), "text": text}, None,
                gateway=gateway, device_id="desk-1", call_id=call,
            )

        pair = (
            threading.Thread(target=one, args=("left", call_left, left, "A")),
            threading.Thread(target=one, args=("right", call_right, right, "B")),
        )
        for item in pair:
            item.start()
        for item in pair:
            item.join(10)
        assert found["left"]["result"] == "A"
        assert found["right"]["result"] == "B"
        assert left.read_text(encoding="utf-8") == "A"
        assert right.read_text(encoding="utf-8") == "B"
        work = REPO / "tests" / "web" / "w4" / "_bash_c04"
        work.mkdir(parents=True, exist_ok=True)
        marker = work / "bash-mark.txt"
        script = work / "mark.py"
        script.write_text(
            "from pathlib import Path\n"
            f"p = Path({str(marker)!r})\n"
            "old = p.read_text(encoding='utf-8') if p.exists() else ''\n"
            "p.write_text(old + 'x', encoding='utf-8')\n",
            encoding="utf-8",
        )
        from core.safety.approval import get_approval_broker

        stop_approver = threading.Event()

        def _approve() -> None:
            while not stop_approver.is_set():
                broker = get_approval_broker()
                if broker is None or not hasattr(broker, "wait_for_request"):
                    time.sleep(0.05)
                    continue
                approval_id = broker.wait_for_request(0.2)
                if approval_id:
                    broker.resolve(approval_id, "approved")

        threading.Thread(target=_approve, daemon=True).start()
        command = "cmd /c python mark.py"
        bash_call = f"call_{uuid4().hex}"
        bash_args = {"command": command, "workdir": str(work), "timeout": 30}
        browser = gateway.browser_session("tenant-a")
        csrf = "csrf-token-value-for-c04"
        posted = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": bash_call,
                "tool": "bash",
                "args": bash_args,
            },
            timeout=30,
        )
        posted.raise_for_status()
        first_bash = posted.json()
        again = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": bash_call,
                "tool": "bash",
                "args": bash_args,
            },
            timeout=30,
        )
        second_bash = again.json()
        assert first_bash["state"] == "completed", first_bash
        assert second_bash["result"] == first_bash["result"]
        assert marker.read_text(encoding="utf-8") == "x"
        slow = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "command": "cmd /c python -c \"import time; time.sleep(3)\"",
                    "workdir": str(work),
                    "timeout": 1,
                },
            },
            timeout=30,
        )
        assert slow.json()["state"] == "recovery_required"
        zero_started = time.time()
        zero = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "command": "cmd /c python -c \"import time; time.sleep(3)\"",
                    "workdir": str(work),
                    "timeout": 0,
                },
            },
            timeout=30,
        )
        assert time.time() - zero_started < 2.5
        assert zero.json()["state"] == "recovery_required"
        outsider = gateway.browser_session("tenant-b")
        denied = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": outsider, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "write",
                "args": {"path": str(note), "text": "nope"},
            },
            timeout=10,
        )
        assert denied.status_code == 404
        assert note.read_text(encoding="utf-8") == "once"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")
        from core.safety.approval import set_approval_broker
        if "stop_approver" in locals():
            stop_approver.set()
        set_approval_broker(None)
        bash_dir = REPO / "tests" / "web" / "w4" / "_bash_c04"
        if bash_dir.exists():
            for child in bash_dir.iterdir():
                if child.is_file():
                    child.unlink()
            bash_dir.rmdir()


def test_w4_c04_negative(tmp_path: Path) -> None:
    """A lost result ack stays unknown and does not write again."""
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.remote.client import reset_stop
    from rxycode_runner.transport.tool_rpc import cancel_started, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.supervisor import attempt_tool, cancel_device_tool

    target = tmp_path / "side.txt"
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    attempt_id, call_id = _ids()
    try:
        dropped = attempt_tool(
            None, attempt_id, "write", {"mode": "write", "path": str(target)}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id, ack=False,
        )
        assert dropped["state"] == "unacked"
        assert target.read_text(encoding="utf-8") == "W"
        retried = attempt_tool(
            None, f"att_{uuid4().hex}", "write", {"mode": "write", "path": str(target)}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id,
        )
        assert retried["state"] == "recovery_required"
        assert target.read_text(encoding="utf-8") == "W"
        request_stop()
        thread.join(5)
        clear_local_tools("desk-1")
        reset_stop()
        restarted = _pair(gateway)
        thread = restarted
        after_restart = attempt_tool(
            None, f"att_{uuid4().hex}", "write", {"mode": "write", "path": str(target)}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id,
        )
        assert after_restart["state"] == "recovery_required"
        assert target.read_text(encoding="utf-8") == "W"
        cancel_attempt, cancel_call = _ids()
        cancelled = cancel_device_tool(
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
