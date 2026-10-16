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
        stop_approver = threading.Event()

        def _approve() -> None:
            while not stop_approver.is_set():
                try:
                    pending = httpx.get(
                        f"{gateway.http}/api/v1/devices/desk-1/approvals/pending",
                        cookies={"rxy_session": browser},
                        timeout=3,
                    )
                except httpx.HTTPError:
                    continue
                if pending.status_code != 200:
                    continue
                approval_id = str(pending.json().get("approval_id") or "")
                if not approval_id:
                    continue
                httpx.post(
                    f"{gateway.http}/api/v1/devices/desk-1/approvals/{approval_id}",
                    headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
                    cookies={"rxy_session": browser, "rxy_csrf": csrf},
                    json={"decision": "approved"},
                    timeout=5,
                )

        command = "cmd /c python mark.py"
        bash_call = f"call_{uuid4().hex}"
        bash_args = {"command": command, "workdir": str(work), "timeout": 30}
        browser = gateway.browser_session("tenant-a")
        csrf = "csrf-token-value-for-c04"
        approver = threading.Thread(target=_approve, daemon=True)
        approver.start()
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
        stop_approver.set()
        approver.join(5)
        from RxyCode.RxyCode1_1_0.core.safety.approval import get_approval_broker
        from rxycode_worker.runner_client import reply_wait_seconds

        broker = get_approval_broker()
        assert broker is not None and float(broker.timeout) >= 120
        assert reply_wait_seconds({"timeout": 0}) >= 135
        delay_mark = work / "bash-delay.txt"
        (work / "delay.py").write_text(
            "from pathlib import Path\n"
            f"p = Path({str(delay_mark)!r})\n"
            "old = p.read_text(encoding='utf-8') if p.exists() else ''\n"
            "p.write_text(old + 'd', encoding='utf-8')\n",
            encoding="utf-8",
        )

        def _approve_after_five() -> None:
            time.sleep(6)
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    pending = httpx.get(
                        f"{gateway.http}/api/v1/devices/desk-1/approvals/pending",
                        cookies={"rxy_session": browser},
                        timeout=3,
                    )
                except httpx.HTTPError:
                    continue
                if pending.status_code != 200:
                    continue
                approval_id = str(pending.json().get("approval_id") or "")
                if not approval_id:
                    continue
                httpx.post(
                    f"{gateway.http}/api/v1/devices/desk-1/approvals/{approval_id}",
                    headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
                    cookies={"rxy_session": browser, "rxy_csrf": csrf},
                    json={"decision": "approved"},
                    timeout=5,
                )
                return

        threading.Thread(target=_approve_after_five, daemon=True).start()
        delay_started = time.time()
        delayed = httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "command": "cmd /c python delay.py",
                    "workdir": str(work),
                    "timeout": 30,
                },
            },
            timeout=40,
        )
        delay_body = delayed.json()
        assert delayed.status_code == 200, delayed.text
        assert delay_body["state"] == "completed" and time.time() - delay_started >= 5, (
            round(time.time() - delay_started, 3),
            delay_body,
        )
        assert delay_mark.read_text(encoding="utf-8") == "d"
        abandoned = work / "bash-abandoned.txt"
        (work / "abandon.py").write_text(
            "from pathlib import Path\n"
            f"p = Path({str(abandoned)!r})\n"
            "old = p.read_text(encoding='utf-8') if p.exists() else ''\n"
            "p.write_text(old + 'z', encoding='utf-8')\n",
            encoding="utf-8",
        )
        abandon_call = f"call_{uuid4().hex}"
        abandon_holder: dict[str, object] = {}

        def _post_abandon() -> None:
            abandon_holder["response"] = httpx.post(
                f"{gateway.http}/api/v1/devices/desk-1/invocations",
                headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
                cookies={"rxy_session": browser, "rxy_csrf": csrf},
                json={
                    "attempt_id": f"att_{uuid4().hex}",
                    "call_id": abandon_call,
                    "tool": "bash",
                    "args": {
                        "command": "cmd /c python abandon.py",
                        "workdir": str(work),
                        "timeout": 30,
                    },
                },
                timeout=40,
            )

        threading.Thread(target=_post_abandon, daemon=True).start()
        late_approval = ""
        seen_pending = time.time() + 15
        while time.time() < seen_pending and not late_approval:
            try:
                pending = httpx.get(
                    f"{gateway.http}/api/v1/devices/desk-1/approvals/pending",
                    cookies={"rxy_session": browser},
                    timeout=3,
                )
            except httpx.HTTPError:
                continue
            if pending.status_code == 200:
                late_approval = str(pending.json().get("approval_id") or "")
            else:
                time.sleep(0.1)
        assert late_approval
        gateway.send_tool(
            "desk-1",
            {"type": "cancel", "device_id": "desk-1", "call_id": abandon_call},
        )
        time.sleep(0.5)
        httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/approvals/{late_approval}",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={"decision": "approved"},
            timeout=5,
        )
        wait_abandon = time.time() + 15
        while time.time() < wait_abandon and "response" not in abandon_holder:
            time.sleep(0.1)
        assert "response" in abandon_holder
        abandon_response = abandon_holder["response"]
        assert abandon_response.status_code == 200, abandon_response.text
        assert abandon_response.json()["state"] in {"cancelled", "recovery_required"}
        time.sleep(2)
        assert not abandoned.exists()
        pair_marks = {"left": work / "bash-left.txt", "right": work / "bash-right.txt"}
        pair_calls: dict[str, str] = {}
        for name, mark, piece in (("left", pair_marks["left"], "L"), ("right", pair_marks["right"], "R")):
            (work / f"{name}.py").write_text(
                "from pathlib import Path\n"
                f"p = Path({str(mark)!r})\n"
                "old = p.read_text(encoding='utf-8') if p.exists() else ''\n"
                f"p.write_text(old + {piece!r}, encoding='utf-8')\n",
                encoding="utf-8",
            )
            pair_calls[name] = f"call_{uuid4().hex}"
        pair_holder: dict[str, httpx.Response] = {}

        def _post_pair(name: str) -> None:
            pair_holder[name] = httpx.post(
                f"{gateway.http}/api/v1/devices/desk-1/invocations",
                headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
                cookies={"rxy_session": browser, "rxy_csrf": csrf},
                json={
                    "attempt_id": f"att_{uuid4().hex}",
                    "call_id": pair_calls[name],
                    "tool": "bash",
                    "args": {
                        "command": f"cmd /c python {name}.py",
                        "workdir": str(work),
                        "timeout": 30,
                    },
                },
                timeout=40,
            )

        for name in ("left", "right"):
            threading.Thread(target=_post_pair, args=(name,), daemon=True).start()
        paired: dict[str, str] = {}
        pair_deadline = time.time() + 15
        while time.time() < pair_deadline and len(paired) < 2:
            try:
                pending = httpx.get(
                    f"{gateway.http}/api/v1/devices/desk-1/approvals/pending",
                    cookies={"rxy_session": browser},
                    timeout=3,
                )
            except httpx.HTTPError:
                continue
            if pending.status_code != 200:
                time.sleep(0.05)
                continue
            body = pending.json()
            command = str((body.get("args") or {}).get("command") or "")
            approval_id = str(body.get("approval_id") or "")
            if "left.py" in command and approval_id:
                paired["left"] = approval_id
            elif "right.py" in command and approval_id:
                paired["right"] = approval_id
        assert set(paired) == {"left", "right"}, paired
        gateway.send_tool(
            "desk-1",
            {"type": "cancel", "device_id": "desk-1", "call_id": pair_calls["left"]},
        )
        time.sleep(0.5)
        httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/approvals/{paired['right']}",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={"decision": "approved"},
            timeout=5,
        )
        httpx.post(
            f"{gateway.http}/api/v1/devices/desk-1/approvals/{paired['left']}",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={"decision": "approved"},
            timeout=5,
        )
        pair_wait = time.time() + 20
        while time.time() < pair_wait and len(pair_holder) < 2:
            time.sleep(0.1)
        assert set(pair_holder) == {"left", "right"}
        assert pair_holder["right"].status_code == 200, pair_holder["right"].text
        assert pair_holder["right"].json()["state"] == "completed", pair_holder["right"].text
        assert pair_marks["right"].read_text(encoding="utf-8") == "R"
        assert pair_holder["left"].json()["state"] in {"cancelled", "recovery_required"}
        time.sleep(1)
        assert not pair_marks["left"].exists()
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
