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
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import bind_local_tools, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.runner_client import RunnerClient

    writes: list[str] = []

    def execute(args: dict[str, object], *, cancel: threading.Event) -> str:
        del cancel
        target = tmp_path / "note.txt"
        target.write_text("once", encoding="utf-8")
        writes.append(str(args["marker"]))
        return "once"

    bind_local_tools(
        device_id="desk-1",
        journal=RemoteJournalAdapter(ToolExecutionJournal(tmp_path / "journal")),
        execute=execute,
    )
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    client = RunnerClient()
    _attempt_a, call_id = _ids()
    attempt_b = f"att_{uuid4().hex}"
    try:
        first = client.invoke(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=_attempt_a,
            tool="write",
            args={"marker": "a"},
        )
        second = client.invoke(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_b,
            tool="write",
            args={"marker": "a"},
        )
        assert first.state == "completed"
        assert first.result == "once"
        assert second.state == "completed"
        assert second.result == "once"
        assert writes == ["a"]
        assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "once"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")


def test_w4_c04_negative(tmp_path: Path) -> None:
    """A lost result ack stays unknown and does not write again."""
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import bind_local_tools, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.runner_client import RunnerClient

    target = tmp_path / "side.txt"
    writes: list[int] = []
    started = threading.Event()

    def execute(args: dict[str, object], *, cancel: threading.Event) -> str:
        if args.get("mode") == "cancel":
            started.set()
            cancel.wait(3)
            return "stopped"
        writes.append(1)
        previous = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(previous + "W", encoding="utf-8")
        return "W"

    bind_local_tools(
        device_id="desk-1",
        journal=RemoteJournalAdapter(ToolExecutionJournal(tmp_path / "journal")),
        execute=execute,
    )
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway)
    client = RunnerClient()
    attempt_id, call_id = _ids()
    try:
        dropped = client.invoke(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"mode": "write"},
            ack=False,
        )
        assert dropped.state == "unacked"
        assert target.read_text(encoding="utf-8") == "W"
        retried = client.invoke(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=f"att_{uuid4().hex}",
            tool="write",
            args={"mode": "write"},
        )
        assert retried.state == "recovery_required"
        assert writes == [1]
        assert target.read_text(encoding="utf-8") == "W"
        cancel_attempt, cancel_call = _ids()
        cancelled = client.invoke_and_cancel(
            gateway=gateway,
            device_id="desk-1",
            call_id=cancel_call,
            attempt_id=cancel_attempt,
            tool="write",
            args={"mode": "cancel"},
            started=started,
        )
        assert cancelled.state == "cancelled"
        assert target.read_text(encoding="utf-8") == "W"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")
